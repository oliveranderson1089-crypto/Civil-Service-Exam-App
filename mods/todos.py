"""共享待办：互相监督，每人独立打勾。


"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import _mark_study, current_user, get_db, uid
from mods.team import _my_team, _team_members

bp = Blueprint("todos", __name__)


def _todo_members(db):
    """互监成员 = 我所在队的成员；没组队就是空。"""
    t = _my_team(db)
    return _team_members(db, t) if t else []


def _sync_todo_done(db, tid, member_ids):
    """所有成员都打勾 → 整条标记完成（推送脚本与排序依赖 done 字段）。"""
    got = {r[0] for r in db.execute("SELECT user_id FROM shared_todo_done WHERE todo_id=?", (tid,))}
    all_done = bool(member_ids) and set(member_ids) <= got
    if all_done:
        db.execute("UPDATE shared_todos SET done=1, done_at=datetime('now','localtime') WHERE id=?", (tid,))
    else:
        db.execute("UPDATE shared_todos SET done=0, done_at=NULL WHERE id=?", (tid,))


@bp.get("/api/shared_todos")
def shared_todos_list():
    db = get_db()
    team = _my_team(db)
    members = _team_members(db, team) if team else []
    if not team:
        return jsonify({"items": [], "members": [], "me": current_user()["username"],
                        "me_id": uid(), "no_team": True})
    rows = db.execute("SELECT * FROM shared_todos WHERE team_id=? ORDER BY done, id DESC LIMIT 200",
                      (team,)).fetchall()
    marks, by = {}, {}
    for r in db.execute("SELECT todo_id, user_id, by_name FROM shared_todo_done"):
        marks.setdefault(r["todo_id"], []).append(r["user_id"])
        by.setdefault(r["todo_id"], {})[str(r["user_id"])] = r["by_name"] or ""
    items = []
    for r in rows:
        d = dict(r)
        d["done_ids"] = marks.get(r["id"], [])
        d["done_by_map"] = by.get(r["id"], {})   # {被确认人id: 确认人}
        d["is_plan"] = (r["source"] == "plan")   # 来自备考规划的条目，前端加标记
        items.append(d)
    return jsonify({"items": items, "members": members,
                    "me": current_user()["username"], "me_id": uid()})


@bp.post("/api/shared_todos")
def shared_todos_add():
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入内容"}), 400
    db = get_db()
    team = _my_team(db)
    if not team:
        return jsonify({"error": "先组队才能加共享待办"}), 400
    cur = db.execute("INSERT INTO shared_todos(text,created_by,team_id) VALUES(?,?,?)",
                     (text[:200], current_user()["username"], team))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@bp.post("/api/shared_todos/<int:tid>/toggle")
def shared_todos_toggle(tid):
    """body: {user_id} —— 交叉确认：只能给**搭档**打勾，不能给自己打勾。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM shared_todos WHERE id=?", (tid,)).fetchone():
        return jsonify({"error": "未找到"}), 404
    members = _todo_members(db)
    mids = [m["id"] for m in members]
    me = uid()
    if me not in mids:
        return jsonify({"error": "你还没组队，先去互监待办里搜账号组队"}), 403
    if len(mids) < 2:
        return jsonify({"error": "组队里还没有搭档，先邀请一个搭档"}), 400
    who = int((request.get_json(silent=True) or {}).get("user_id") or 0)
    if who not in mids:
        return jsonify({"error": "不是互监成员"}), 400
    if who == me:
        return jsonify({"error": "不能给自己打勾，等搭档来确认 🤝"}), 403
    name = next(m["name"] for m in members if m["id"] == who)
    hit = db.execute("SELECT by_user FROM shared_todo_done WHERE todo_id=? AND user_id=?",
                     (tid, who)).fetchone()
    if hit:
        # 谁确认的谁才能撤销（防止互相把对方的确认取消掉）
        if hit["by_user"] and hit["by_user"] != me:
            return jsonify({"error": "这个勾是别人确认的，只有确认人能撤销"}), 403
        db.execute("DELETE FROM shared_todo_done WHERE todo_id=? AND user_id=?", (tid, who))
        on = False
    else:
        db.execute("INSERT OR IGNORE INTO shared_todo_done(todo_id,user_id,username,by_user,by_name) "
                   "VALUES(?,?,?,?,?)", (tid, who, name, me, current_user()["username"]))
        on = True
        # 被确认完成的人（who）今天算学习过了（组队期间互监也计入学习天数）
        _mark_study(db, who, datetime.now().strftime("%Y-%m-%d"))
    _sync_todo_done(db, tid, mids)
    db.commit()
    rows = db.execute("SELECT user_id, by_name FROM shared_todo_done WHERE todo_id=?", (tid,)).fetchall()
    return jsonify({"done": on, "user_id": who, "done_ids": [r["user_id"] for r in rows]})


@bp.delete("/api/shared_todos/<int:tid>")
def shared_todos_del(tid):
    db = get_db()
    db.execute("DELETE FROM shared_todo_done WHERE todo_id=?", (tid,))
    db.execute("DELETE FROM shared_todos WHERE id=?", (tid,))
    db.commit()
    return jsonify({"ok": True})
