"""组队：互监搭档，邀请制。


"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import _bump_sync, _study_stats, get_db, uid, uname

def _my_team(db, u=None):
    """当前用户所在的队 id（一人最多在一个队里）。"""
    u = u or uid()
    r = db.execute("SELECT team_id FROM team_members WHERE user_id=? LIMIT 1", (u,)).fetchone()
    return r["team_id"] if r else None


def _team_members(db, team_id):
    rows = db.execute("SELECT m.user_id, u.username FROM team_members m "
                      "JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.user_id", (team_id,))
    return [{"id": r["user_id"], "name": r["username"]} for r in rows]

bp = Blueprint("team", __name__)


@bp.get("/api/team")
def team_info():
    """我的组队状态 + 收到/发出的申请（前端据此渲染组队 UI）。"""
    db = get_db()
    me = uid()
    team = _my_team(db)
    tinfo = None
    if team:
        tinfo = {"id": team, "members": _team_members(db, team),
                 "partner": next((m for m in _team_members(db, team) if m["id"] != me), None)}
    incoming = [{"id": r["id"], "from_uid": r["from_uid"], "from_name": uname(db, r["from_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE to_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    outgoing = [{"id": r["id"], "to_uid": r["to_uid"], "to_name": uname(db, r["to_uid"]),
                 "kind": r["kind"]} for r in db.execute(
        "SELECT * FROM team_requests WHERE from_uid=? AND status='pending' ORDER BY id DESC", (me,))]
    return jsonify({"team": tinfo, "incoming": incoming, "outgoing": outgoing,
                    "me": uname(db, me), "me_id": me, "study": _study_stats(db, me)})


@bp.get("/api/team/search")
def team_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"users": []})
    db = get_db()
    me = uid()
    like = "%" + q + "%"
    rows = db.execute("SELECT id, username FROM users WHERE (username LIKE ? OR CAST(id AS TEXT)=?) "
                      "AND id<>? ORDER BY id LIMIT 20", (like, q, me)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "name": r["username"], "in_team": bool(_my_team(db, r["id"]))})
    return jsonify({"users": out})


@bp.post("/api/team/request")
def team_request():
    """发组队申请：{to_uid}。"""
    db = get_db()
    me = uid()
    to = int((request.get_json(silent=True) or {}).get("to_uid") or 0)
    if not to or to == me:
        return jsonify({"error": "请选择要组队的账号"}), 400
    if not db.execute("SELECT 1 FROM users WHERE id=?", (to,)).fetchone():
        return jsonify({"error": "账号不存在"}), 404
    if _my_team(db):
        return jsonify({"error": "你已经在一个队里了，先解散才能重新组队"}), 400
    if _my_team(db, to):
        return jsonify({"error": "对方已经组队了"}), 400
    dup = db.execute("SELECT 1 FROM team_requests WHERE kind='join' AND status='pending' "
                     "AND ((from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?))",
                     (me, to, to, me)).fetchone()
    if dup:
        return jsonify({"error": "已经有一条待处理的组队申请了"}), 400
    db.execute("INSERT INTO team_requests(from_uid,to_uid,kind) VALUES(?,?,'join')", (me, to))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True}), 201


@bp.post("/api/team/request/<int:rid>/accept")
def team_accept(rid):
    db = get_db()
    me = uid()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["to_uid"] != me:
        return jsonify({"error": "申请不存在或无权处理"}), 404
    if r["kind"] == "join":
        if _my_team(db) or _my_team(db, r["from_uid"]):
            db.execute("UPDATE team_requests SET status='rejected' WHERE id=?", (rid,))
            db.commit()
            return jsonify({"error": "你或对方已在其它队里，无法组队"}), 400
        tid = db.execute("INSERT INTO teams DEFAULT VALUES").lastrowid
        db.execute("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (tid, r["from_uid"]))
        db.execute("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (tid, me))
        db.execute("UPDATE team_requests SET status='accepted' WHERE id=?", (rid,))
        # 组队成功：把双方今天的规划同步进这个队的互监待办
        today = datetime.now().strftime("%Y-%m-%d")
        for u in (r["from_uid"], me):
            for p in db.execute("SELECT title, minutes FROM plan_items WHERE user_id=? AND date=? ORDER BY seq, id",
                                (u, today)):
                txt = (p["title"] or "").strip()
                if p["minutes"]:
                    txt += "（%d 分钟）" % p["minutes"]
                db.execute("INSERT INTO shared_todos(text,created_by,source,src_uid,plan_date,team_id) "
                           "VALUES(?,?,'plan',?,?,?)", (txt[:200], uname(db, u), u, today, tid))
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "team_id": tid})
    else:  # disband
        tid = r["team_id"]
        _disband_team(db, tid)
        db.execute("UPDATE team_requests SET status='accepted' WHERE id=?", (rid,))
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "disbanded": True})


@bp.post("/api/team/request/<int:rid>/reject")
def team_reject(rid):
    db = get_db()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["to_uid"] != uid():
        return jsonify({"error": "申请不存在或无权处理"}), 404
    db.execute("UPDATE team_requests SET status='rejected' WHERE id=?", (rid,))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True})


@bp.post("/api/team/request/<int:rid>/cancel")
def team_cancel(rid):
    db = get_db()
    r = db.execute("SELECT * FROM team_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not r or r["from_uid"] != uid():
        return jsonify({"error": "申请不存在或无权撤回"}), 404
    db.execute("UPDATE team_requests SET status='cancelled' WHERE id=?", (rid,))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/team/disband")
def team_disband_request():
    """发解散申请给搭档，对方同意才真正解散。"""
    db = get_db()
    me = uid()
    team = _my_team(db)
    if not team:
        return jsonify({"error": "你还没组队"}), 400
    partner = next((m["id"] for m in _team_members(db, team) if m["id"] != me), None)
    if not partner:
        _disband_team(db, team)          # 队里只剩自己，直接散
        db.commit()
        _bump_sync()
        return jsonify({"ok": True, "disbanded": True})
    if db.execute("SELECT 1 FROM team_requests WHERE kind='disband' AND status='pending' AND team_id=?",
                  (team,)).fetchone():
        return jsonify({"error": "已经发过解散申请了，等对方处理"}), 400
    db.execute("INSERT INTO team_requests(from_uid,to_uid,kind,team_id) VALUES(?,?,'disband',?)",
               (me, partner, team))
    db.commit()
    _bump_sync()
    return jsonify({"ok": True})


def _disband_team(db, team_id):
    """真正解散：清掉这个队的成员、共享待办、以及相关的待处理申请。"""
    ids = [r[0] for r in db.execute("SELECT id FROM shared_todos WHERE team_id=?", (team_id,))]
    if ids:
        qs = ",".join("?" * len(ids))
        db.execute("DELETE FROM shared_todo_done WHERE todo_id IN (%s)" % qs, ids)
        db.execute("DELETE FROM shared_todos WHERE team_id=?", (team_id,))
    db.execute("UPDATE team_requests SET status='cancelled' WHERE team_id=? AND status='pending'", (team_id,))
    db.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
    db.execute("DELETE FROM teams WHERE id=?", (team_id,))
