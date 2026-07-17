"""好友 / 云盘 / 聊天。

三块放一起是因为它们真的缠在一起：drive_send 把网盘文件发进聊天、
chat 的文件又能存回网盘、两者都要先是好友。硬拆成三个文件只会让
互相 import 绕圈，不如认下这个内聚。

_notify_chat 的 SSE 只是「即时亮一下」的加速通道：消息本身已经落
chat_msgs、通知已进 notifications，推送丢了浏览器重连就能拉回。
"""
import json
import os
import threading
import time
import uuid

from flask import Blueprint, Response, jsonify, request, send_file

from core import UPLOADS, get_db, log, uid, uname

bp = Blueprint("social", __name__)


def _drive_dir(user_id):
    d = os.path.join(UPLOADS, "drive", str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


def _are_friends(db, a, b):
    return bool(db.execute("SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (a, b)).fetchone())


# ---- 好友 ----
@bp.get("/api/friends")
def friends_list():
    db = get_db()
    rows = db.execute(
        "SELECT u.id, u.username, u.avatar FROM friends f JOIN users u ON u.id=f.friend_id "
        "WHERE f.user_id=? ORDER BY u.username", (uid(),)).fetchall()
    nreq = db.execute("SELECT COUNT(*) FROM friend_reqs WHERE to_uid=? AND status='pending'",
                      (uid(),)).fetchone()[0]
    friends = [{"id": r["id"], "username": r["username"],
                "avatar": ("/skin/%d/%s" % (r["id"], r["avatar"])) if r["avatar"] else ""} for r in rows]
    return jsonify({"friends": friends, "n_req": nreq})


@bp.get("/api/friends/search")
def friends_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"users": []})
    db = get_db()
    rows = db.execute(
        "SELECT id, username FROM users WHERE (username LIKE ? OR CAST(id AS TEXT)=?) AND id<>? LIMIT 20",
        ("%" + q + "%", q, uid())).fetchall()
    out = []
    for r in rows:
        st = "add"                      # 可添加（自己已被 SQL 的 id<>? 排除）
        if _are_friends(db, uid(), r["id"]):
            st = "friend"
        elif db.execute("SELECT 1 FROM friend_reqs WHERE from_uid=? AND to_uid=? AND status='pending'",
                        (uid(), r["id"])).fetchone():
            st = "sent"
        out.append({"id": r["id"], "username": r["username"], "state": st})
    return jsonify({"users": out})


@bp.post("/api/friends/request")
def friends_request():
    data = request.get_json(silent=True) or {}
    to = int(data.get("to") or 0)
    db = get_db()
    if not to or to == uid() or not db.execute("SELECT 1 FROM users WHERE id=?", (to,)).fetchone():
        return jsonify({"error": "用户不存在"}), 400
    if _are_friends(db, uid(), to):
        return jsonify({"error": "已经是好友了"}), 400
    # 对方已经给我发过 → 直接互相成为好友
    rev = db.execute("SELECT id FROM friend_reqs WHERE from_uid=? AND to_uid=? AND status='pending'",
                     (to, uid())).fetchone()
    if rev:
        _add_friend(db, uid(), to)
        db.execute("UPDATE friend_reqs SET status='accepted' WHERE id=?", (rev["id"],))
        db.commit()
        return jsonify({"ok": True, "friend": True})
    db.execute("INSERT INTO friend_reqs(from_uid,to_uid,msg) VALUES(?,?,?)",
               (uid(), to, (data.get("msg") or "").strip()[:60]))
    db.commit()
    _notify_chat(to, {"type": "friend"})                 # 对方好友请求红点即时亮
    return jsonify({"ok": True})


def _add_friend(db, a, b):
    db.execute("INSERT OR IGNORE INTO friends(user_id,friend_id) VALUES(?,?)", (a, b))
    db.execute("INSERT OR IGNORE INTO friends(user_id,friend_id) VALUES(?,?)", (b, a))


@bp.get("/api/friends/requests")
def friends_requests():
    db = get_db()
    rows = db.execute(
        "SELECT r.id, r.from_uid, u.username, r.msg, r.created_at FROM friend_reqs r "
        "JOIN users u ON u.id=r.from_uid WHERE r.to_uid=? AND r.status='pending' ORDER BY r.id DESC",
        (uid(),)).fetchall()
    return jsonify({"requests": [dict(r) for r in rows]})


@bp.post("/api/friends/requests/<int:rid>")
def friends_req_act(rid):
    action = (request.get_json(silent=True) or {}).get("action")
    db = get_db()
    r = db.execute("SELECT * FROM friend_reqs WHERE id=? AND to_uid=? AND status='pending'",
                   (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "请求不存在"}), 404
    if action == "accept":
        _add_friend(db, uid(), r["from_uid"])
        db.execute("UPDATE friend_reqs SET status='accepted' WHERE id=?", (rid,))
    else:
        db.execute("UPDATE friend_reqs SET status='rejected' WHERE id=?", (rid,))
    db.commit()
    if action == "accept":
        _notify_chat(r["from_uid"], {"type": "friend"})  # 通过了 → 对方好友列表即时更新
    return jsonify({"ok": True})


@bp.delete("/api/friends/<int:fid>")
def friends_del(fid):
    db = get_db()
    db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
               (uid(), fid, fid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---- 云盘 ----
DRIVE_MAX = 200 * 1024 * 1024        # 单文件上限 200MB


def _drive_row(r):
    d = dict(r)
    d["is_dir"] = bool(d.get("is_dir"))
    return d


@bp.get("/api/drive")
def drive_list():
    folder = (request.args.get("folder") or "").strip().strip("/")
    db = get_db()
    rows = db.execute(
        "SELECT id, folder, name, ext, mime, size, is_dir, source, created_at FROM drive_files "
        "WHERE owner_id=? AND folder=? ORDER BY is_dir DESC, id DESC", (uid(), folder)).fetchall()
    used = db.execute("SELECT COALESCE(SUM(size),0) FROM drive_files WHERE owner_id=?",
                      (uid(),)).fetchone()[0]
    return jsonify({"folder": folder, "items": [_drive_row(r) for r in rows], "used": used})


@bp.post("/api/drive")
def drive_upload():
    folder = (request.form.get("folder") or "").strip().strip("/")
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > DRIVE_MAX:
        return jsonify({"error": "文件超过 200MB"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    stored = uuid.uuid4().hex + ext
    f.save(os.path.join(_drive_dir(uid()), stored))
    db = get_db()
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
        "VALUES(?,?,?,?,?,?,?,0,'drive')",
        (uid(), folder, f.filename, stored, ext, f.mimetype or "", size))
    db.commit()
    return jsonify(_drive_row(db.execute("SELECT * FROM drive_files WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.post("/api/drive/folder")
def drive_mkdir():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip().strip("/")[:40]
    parent = (data.get("parent") or "").strip().strip("/")
    if not name or "/" in name:
        return jsonify({"error": "文件夹名不合法"}), 400
    path = (parent + "/" + name) if parent else name
    db = get_db()
    if db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? AND is_dir=1",
                  (uid(), parent, name)).fetchone():
        return jsonify({"error": "已有同名文件夹"}), 400
    db.execute("INSERT INTO drive_files(owner_id,folder,name,is_dir,source) VALUES(?,?,?,1,'drive')",
               (uid(), parent, name))
    db.commit()
    return jsonify({"ok": True, "path": path})


@bp.get("/api/drive/<int:fid>/download")
def drive_download(fid):
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0",
                   (fid, uid())).fetchone()
    if not r:
        return "文件不存在", 404
    return send_file(os.path.join(_drive_dir(uid()), r["stored_name"]),
                     as_attachment=True, download_name=r["name"],
                     mimetype=r["mime"] or "application/octet-stream")


@bp.delete("/api/drive/<int:fid>")
def drive_del(fid):
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=?", (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "不存在"}), 404
    if r["is_dir"]:
        # 删文件夹：连里面的一起删（folder 前缀匹配）
        sub = r["name"] if not r["folder"] else (r["folder"] + "/" + r["name"])
        kids = db.execute("SELECT stored_name FROM drive_files WHERE owner_id=? AND "
                          "(folder=? OR folder LIKE ?)", (uid(), sub, sub + "/%")).fetchall()
        for k in kids:
            if k["stored_name"]:
                try:
                    os.remove(os.path.join(_drive_dir(uid()), k["stored_name"]))
                except Exception:
                    log.debug("删网盘文件失败（残留不影响功能）", exc_info=True)
        db.execute("DELETE FROM drive_files WHERE owner_id=? AND (folder=? OR folder LIKE ?)",
                   (uid(), sub, sub + "/%"))
    elif r["stored_name"]:
        try:
            os.remove(os.path.join(_drive_dir(uid()), r["stored_name"]))
        except Exception:
            log.debug("删网盘文件失败（残留不影响功能）", exc_info=True)
    db.execute("DELETE FROM drive_files WHERE id=?", (fid,))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/drive/<int:fid>/send")
def drive_send(fid):
    """把云盘里的一个文件发给某个好友（走聊天）。"""
    to = int((request.get_json(silent=True) or {}).get("to") or 0)
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "文件不存在"}), 404
    if not _are_friends(db, uid(), to):
        return jsonify({"error": "对方不是你的好友"}), 400
    me = uid()
    mid = _chat_send_file(db, me, to, r["name"], r["stored_name"], r["size"], r["mime"], _drive_dir(me))
    myname = uname(db, me)
    _chat_center_notify(db, to, me, myname, "[文件] " + (r["name"] or ""), mid or 0)
    db.commit()
    _notify_chat(to, {"type": "msg", "from": me, "name": myname,
                      "preview": "[文件] " + (r["name"] or "")})     # 提交后再秒推
    return jsonify({"ok": True})


# ---- 聊天 ----
def _chat_copy_to_drive(db, to, name, src_dir, stored_name, ext, mime, size):
    """收到的文件也放进收件人云盘的「聊天文件」文件夹里，方便他保存/转存。"""
    dst = uuid.uuid4().hex + (ext or "")
    try:
        import shutil
        shutil.copyfile(os.path.join(src_dir, stored_name), os.path.join(_drive_dir(to), dst))
    except Exception:
        return None
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
        "VALUES(?,?,?,?,?,?,?,0,'chat')", (to, "聊天文件", name, dst, ext, mime or "", size))
    return cur.lastrowid


def _chat_send_file(db, frm, to, name, stored_name, size, mime, src_dir):
    ext = os.path.splitext(name)[1].lower()
    fid_to = _chat_copy_to_drive(db, to, name, src_dir, stored_name, ext, mime, size)
    kind = "image" if (mime or "").startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".gif", ".webp") else "file"
    cur = db.execute(
        "INSERT INTO chat_msgs(from_uid,to_uid,kind,file_id,file_name,file_size,file_mime) "
        "VALUES(?,?,?,?,?,?,?)", (frm, to, kind, fid_to, name, size, mime or ""))
    # 通知放到调用方 commit 之后（见 chat_send/drive_send），否则对方可能在提交前就来拉、扑空
    return cur.lastrowid


@bp.get("/api/chat/conversations")
def chat_convos():
    db = get_db()
    me = uid()
    convos = []
    total_unread = 0
    for r in db.execute("SELECT friend_id FROM friends WHERE user_id=?", (me,)).fetchall():
        fid = r["friend_id"]
        last = db.execute(
            "SELECT * FROM chat_msgs WHERE (from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?) "
            "ORDER BY id DESC LIMIT 1", (me, fid, fid, me)).fetchone()
        unread = db.execute("SELECT COUNT(*) FROM chat_msgs WHERE from_uid=? AND to_uid=? AND read_at IS NULL",
                            (fid, me)).fetchone()[0]
        total_unread += unread
        prev = ""
        if last:
            prev = last["body"] if last["kind"] == "text" else ("[图片]" if last["kind"] == "image" else "[文件] " + (last["file_name"] or ""))
        convos.append({"id": fid, "username": uname(db, fid), "avatar": _uavatar(db, fid),
                       "preview": prev[:30],
                       "time": (last["created_at"] if last else ""), "unread": unread,
                       "last_id": last["id"] if last else 0})
    convos.sort(key=lambda c: -(c["last_id"]))
    # 文件传输助手（和自己的会话，跨设备传文件/暂存），永远置顶
    slast = db.execute("SELECT * FROM chat_msgs WHERE from_uid=? AND to_uid=? ORDER BY id DESC LIMIT 1",
                       (me, me)).fetchone()
    sprev = ""
    if slast:
        sprev = slast["body"] if slast["kind"] == "text" else ("[图片]" if slast["kind"] == "image" else "[文件] " + (slast["file_name"] or ""))
    convos.insert(0, {"id": me, "username": "文件传输助手", "avatar": "", "self": True,
                      "preview": sprev[:30], "time": (slast["created_at"] if slast else ""),
                      "unread": 0, "last_id": (slast["id"] if slast else 0)})
    return jsonify({"conversations": convos, "unread": total_unread})


@bp.get("/api/chat/<int:fid>")
def chat_history(fid):
    db = get_db()
    me = uid()
    if fid != me and not _are_friends(db, me, fid):   # fid==me = 文件传输助手
        return jsonify({"error": "不是好友"}), 403
    after = int(request.args.get("after") or 0)
    rows = db.execute(
        "SELECT * FROM chat_msgs WHERE ((from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?)) AND id>? "
        "ORDER BY id LIMIT 200", (me, fid, fid, me, after)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "mine": r["from_uid"] == me, "kind": r["kind"],
                    "body": r["body"] or "", "file_id": r["file_id"], "file_name": r["file_name"],
                    "file_size": r["file_size"], "time": r["created_at"]})
    # 把对方发来的标记已读
    db.execute("UPDATE chat_msgs SET read_at=datetime('now','localtime') "
               "WHERE from_uid=? AND to_uid=? AND read_at IS NULL", (fid, me))
    # 读了这个会话 → 清掉它在消息中心/通知栏里堆积的那几条 chat 通知
    db.execute("DELETE FROM notifications WHERE user_id=? AND kind='chat' AND link=?",
               (me, "chatroom:%d" % fid))
    db.commit()
    fname = "文件传输助手" if fid == me else uname(db, fid)
    return jsonify({"messages": out, "me": me, "friend": fname,
                    "friend_avatar": _uavatar(db, fid), "me_avatar": _uavatar(db, me)})


@bp.post("/api/chat/<int:fid>")
def chat_send(fid):
    db = get_db()
    me = uid()
    if fid != me and not _are_friends(db, me, fid):   # fid==me 即「文件传输助手」，自己发给自己
        return jsonify({"error": "不是好友"}), 403
    # 文件消息（multipart）
    if request.files.get("file"):
        f = request.files["file"]
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > DRIVE_MAX:
            return jsonify({"error": "文件超过 200MB"}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        stored = uuid.uuid4().hex + ext
        # 发送方也留一份在自己云盘「聊天文件」，并作为源
        f.save(os.path.join(_drive_dir(me), stored))
        db.execute("INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
                   "VALUES(?,?,?,?,?,?,?,0,'chat')", (me, "聊天文件", f.filename, stored, ext, f.mimetype or "", size))
        mid = _chat_send_file(db, me, fid, f.filename, stored, size, f.mimetype or "", _drive_dir(me))
        myname = uname(db, me)
        if fid != me:                                 # 文件传输助手(自己)不给自己发通知
            _chat_center_notify(db, fid, me, myname, "[文件] " + (f.filename or ""), mid or 0)
        db.commit()
        _notify_chat(fid, {"type": "msg", "from": me, "name": myname,
                           "preview": "[文件] " + (f.filename or "")})   # 提交后再秒推（跨设备同步）
        return jsonify({"ok": True})
    # 文本消息
    body = (request.get_json(silent=True) or {}).get("body", "").strip()
    if not body:
        return jsonify({"error": "空消息"}), 400
    cur = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,kind,body) VALUES(?,?,'text',?)",
                     (me, fid, body[:4000]))
    myname = uname(db, me)
    if fid != me:
        _chat_center_notify(db, fid, me, myname, body[:80], cur.lastrowid)
    db.commit()
    _notify_chat(fid, {"type": "msg", "from": me, "name": myname,
                       "preview": body[:60]})           # 秒推给对方（自己的其它设备也会同步）
    return jsonify({"ok": True})


@bp.get("/api/chat/file/<int:fid>")
def chat_file(fid):
    """下载/查看聊天里的文件。消息里存的是收件人云盘那一份的 id，所以**发送方**看自己发的图
    时 owner_id 不等于自己 —— 改成：只要你是这条消息的收发双方之一，就放行，并从文件真正的
    所有者目录里取。"""
    db = get_db()
    me = uid()
    r = db.execute("SELECT * FROM drive_files WHERE id=?", (fid,)).fetchone()
    if not r:
        return "文件不存在", 404
    owner = r["owner_id"]
    if owner != me:                    # 不是自己云盘里的 → 必须是自己参与的聊天引用了它
        party = db.execute("SELECT 1 FROM chat_msgs WHERE file_id=? AND (from_uid=? OR to_uid=?)",
                           (fid, me, me)).fetchone()
        if not party:
            return "无权访问", 403
    inline = request.args.get("inline") == "1"
    return send_file(os.path.join(_drive_dir(owner), r["stored_name"]),
                     as_attachment=not inline, download_name=r["name"],
                     mimetype=r["mime"] or "application/octet-stream")


@bp.get("/api/chat/unread")
def chat_unread():
    n = get_db().execute("SELECT COUNT(*) FROM chat_msgs WHERE to_uid=? AND read_at IS NULL",
                         (uid(),)).fetchone()[0]
    return jsonify({"unread": n})


# ---- 秒推：SSE（服务器→客户端单向推送）----
# waitress 是单进程多线程，所以进程内一个 {用户→若干队列} 的注册表就能跨连接通信：
# 有人给用户 X 发消息 → 往 X 的每个队列塞个信号 → X 那条 SSE 连接立刻把信号推给浏览器 →
# 浏览器马上去拉新消息。发消息本身还是普通 POST，SSE 只负责「叮」一下。
def _uavatar(db, user_id):
    """某用户的头像 URL（公开可读的 /skin 路径）；没设头像返回空串。"""
    r = db.execute("SELECT avatar FROM users WHERE id=?", (user_id,)).fetchone()
    fn = (r["avatar"] if r else "") or ""
    return ("/skin/%d/%s" % (user_id, fn)) if fn else ""


def _chat_center_notify(db, to_uid, from_uid, from_name, preview, mid):
    """给收件人写一条「消息中心」通知：手机 APK 的后台轮询器会据此在系统通知栏弹出。
    每条消息一条（dkey 带 mid，保证唯一、能被轮询器逐条推送）；对方读了会话时统一清掉（见 chat_history）。"""
    db.execute(
        "INSERT OR IGNORE INTO notifications(user_id,kind,dkey,title,body,link) VALUES(?,?,?,?,?,?)",
        (to_uid, "chat", "chat:%d:%d" % (from_uid, mid),
         "%s 发来消息" % from_name, (preview or "你有一条新消息")[:80], "chatroom:%d" % from_uid))


_chat_listeners = {}
_listeners_lock = threading.Lock()


def _notify_chat(user_id, payload):
    with _listeners_lock:
        qs = list(_chat_listeners.get(user_id, ()))
    for q in qs:
        try:
            q.put_nowait(payload)
        except Exception:
            log.warning("聊天推送投递失败：这条消息对端收不到", exc_info=True)


@bp.get("/api/chat/stream")
def chat_stream():
    me = uid()
    if not me:
        return "unauthorized", 401
    import queue as _q
    ch = _q.Queue(maxsize=100)
    with _listeners_lock:
        _chat_listeners.setdefault(me, set()).add(ch)

    def gen():
        try:
            yield "retry: 3000\n\n"          # 断了 3 秒重连
            start = time.time()
            while time.time() - start < 300:  # 一条连接最多活 5 分钟，之后让浏览器重连（防线程泄漏）
                try:
                    payload = ch.get(timeout=20)
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                except _q.Empty:
                    yield ": ping\n\n"        # 心跳：保活 + 探测对端是否断开（写失败就结束）
        finally:
            with _listeners_lock:
                s = _chat_listeners.get(me)
                if s:
                    s.discard(ch)
                    if not s:
                        _chat_listeners.pop(me, None)

    resp = Response(gen(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"      # 别让中间代理缓冲（Connection 头是 hop-by-hop，WSGI 不能设）
    return resp
