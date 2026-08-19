"""把一段 AI 对话分享给好友/小组，对方能接着往下问。

三个动作：
  分享 → 存一份**快照** + 往聊天里发一张卡片
  查看 → 对方（或我自己）只读地看这份快照
  接着问 → 在他自己名下复制成一条新会话，从此各走各的

为什么是快照不是引用：分享之后原对话还会继续聊，引用等于把后面的话也一起漏出去；
而且对方「接着问」本来就该是他自己的对话，不该往我的历史里写东西。

**带走什么、不带走什么**（隐私边界，改之前先想清楚）：
  带走：用户和助手的正文
  不带走：附件原文、工具轨迹、长期记忆、项目指令与项目资料
这些都是「关于我这个人」的东西，跟这段对话讲了什么无关。

一句话别误解：这么做省下的是**对方重新摸索一遍**的功夫，不是上下文费用 ——
他接着问的时候，这段历史照样每轮进上下文。
"""
import json

from flask import Blueprint, jsonify, request

from core import get_db, uid, uname

bp = Blueprint("aishare", __name__)

MAX_MSGS = 200          # 一份快照最多带多少条
MAX_ONE = 8000          # 单条正文上限（附件全文本来就不带，正常聊天到不了这个数）


def _snapshot(db, cid, owner):
    """把一条会话摊成可分享的快照。返回 (title, [{role, content}]) 或 (None, None)。"""
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, owner)).fetchone()
    if not c:
        return None, None
    rows = db.execute(
        # 只要正文：kind='tool' 是工具轨迹（含我查了自己哪些数据），kind='error' 是失败占位，
        # 两样都不该跟着分享出去
        "SELECT role, content FROM ai_msgs WHERE chat_id=? AND COALESCE(kind,'text')='text' "
        "ORDER BY id LIMIT ?", (cid, MAX_MSGS)).fetchall()
    msgs = [{"role": r["role"], "content": (r["content"] or "")[:MAX_ONE]}
            for r in rows if (r["content"] or "").strip()]
    return (c["title"] or "AI 对话"), msgs


@bp.post("/api/aichat/chats/<int:cid>/share")
def aishare_create(cid):
    """分享这段对话：给每个收件人各存一份快照，并往聊天里发卡片。

    每人一份而不是一份多人共读：读权限就能按 to_uid 直判，不用再维护一张接收人表；
    快照本身也就几十 KB。
    """
    from mods.social import (CARD_KINDS, _chat_center_notify, _chat_center_notify_group,
                             _conv_peers, _direct_conv, _notify_chat, _pick_targets,
                             _reply_to, _sent_reply)
    data = request.get_json(silent=True) or {}
    db, me = get_db(), uid()
    title, msgs = _snapshot(db, cid, me)
    if title is None:
        return jsonify({"error": "会话不存在"}), 404
    if not msgs:
        return jsonify({"error": "这段对话还是空的，没什么可分享的"}), 400
    users, groups = _pick_targets(db, me, data)
    if not users and not groups:
        return jsonify({"error": "选一个好友或小组再发"}), 400

    myname = uname(db, me)
    body = json.dumps(msgs, ensure_ascii=False)
    sub = "%d 条对话 · 可接着问" % len(msgs)
    pushes, n = [], 0

    def _card(to_uid, conv_id):
        cur = db.execute(
            "INSERT INTO ai_shares(owner_id,to_uid,conv_id,title,msgs,n) VALUES(?,?,?,?,?,?)",
            (me, to_uid, conv_id, title, body, len(msgs)))
        return {"kind": "aishare", "id": cur.lastrowid, "title": title[:120], "sub": sub}

    prev_of = lambda p: "[%s] %s" % (CARD_KINDS["aishare"][0], p["title"])

    for to in users:
        conv = _direct_conv(db, me, to)
        payload = _card(to, None)
        cur = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,reply_to) "
                         "VALUES(?,?,?,'card',?,?)",
                         (me, to, conv, json.dumps(payload, ensure_ascii=False),
                          _reply_to(db, me, to)))
        _chat_center_notify(db, to, me, myname, prev_of(payload)[:80], cur.lastrowid)
        pushes.append((to, {"type": "msg", "from": me, "name": myname,
                            "preview": prev_of(payload)[:60]}))
        n += 1
    for gid in groups:
        g = db.execute("SELECT title FROM conversations WHERE id=?", (gid,)).fetchone()
        gname = (g["title"] if g else "小组") or "小组"
        # 小组里 to_uid 留空、conv_id 记小组：读权限按「是不是这个小组的人」判
        payload = _card(None, gid)
        cur = db.execute("INSERT INTO chat_msgs(from_uid,conv_id,kind,body) VALUES(?,?,'card',?)",
                         (me, gid, json.dumps(payload, ensure_ascii=False)))
        for u in _conv_peers(db, gid, me):
            _chat_center_notify_group(db, u, gid, gname,
                                      "%s：%s" % (myname, prev_of(payload)), cur.lastrowid)
            pushes.append((u, {"type": "msg", "group": gid, "name": gname,
                               "preview": "%s：%s" % (myname, prev_of(payload)[:50])}))
        n += 1
    db.commit()
    for to, payload in pushes:          # 提交之后再推：推早了对方回来拉会扑个空
        _notify_chat(to, payload)
    return _sent_reply(n, users, groups)


def _readable(db, sid, me):
    """我能不能看这份快照。自己发的、发给我的、或发进了我在的小组。"""
    r = db.execute("SELECT * FROM ai_shares WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    if r["owner_id"] == me or r["to_uid"] == me:
        return r
    if r["conv_id"]:
        from mods.social import _is_member
        if _is_member(db, r["conv_id"], me):
            return r
    return None


@bp.get("/api/aishare/<int:sid>")
def aishare_get(sid):
    db, me = get_db(), uid()
    r = _readable(db, sid, me)
    if not r:
        return jsonify({"error": "看不到这份分享（可能不是发给你的）"}), 404
    try:
        msgs = json.loads(r["msgs"] or "[]")
    except Exception:
        msgs = []
    return jsonify({"id": r["id"], "title": r["title"], "msgs": msgs,
                    "from": uname(db, r["owner_id"]), "mine": r["owner_id"] == me,
                    "created_at": r["created_at"]})


@bp.post("/api/aishare/<int:sid>/adopt")
def aishare_adopt(sid):
    """「接着问」：把快照复制成**我自己**的一条会话。

    复制而不是挂进对方的会话：从这里开始两边各走各的，我问什么不会回流给分享者。
    """
    db, me = get_db(), uid()
    r = _readable(db, sid, me)
    if not r:
        return jsonify({"error": "看不到这份分享"}), 404
    try:
        msgs = json.loads(r["msgs"] or "[]")
    except Exception:
        msgs = []
    if not msgs:
        return jsonify({"error": "这份分享是空的"}), 400
    cur = db.execute("INSERT INTO ai_chats(user_id,title) VALUES(?,?)",
                     (me, ((r["title"] or "AI 对话")[:30] + " · 来自分享")[:40]))
    nid = cur.lastrowid
    for m in msgs[:MAX_MSGS]:
        role = "user" if m.get("role") == "user" else "assistant"
        db.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,'text')",
                   (nid, role, (m.get("content") or "")[:MAX_ONE]))
    db.commit()
    return jsonify({"id": nid, "n": len(msgs)}), 201
