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

from core import CFG, UPLOADS, get_db, log, uid, uname
from mods.files import (IMAGE_EXT, INLINE_EXT, OFFICE_EXT, _cacheable,
                        _extract_text, _no_script, _office_to_pdf)

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
# 两个上限都能在 config.json 里调（改完重启服务生效）
DRIVE_MAX = int(CFG.get("drive_max_mb", 200)) * 1024 * 1024        # 单文件上限
DRIVE_QUOTA = int(CFG.get("drive_quota_mb", 2048)) * 1024 * 1024   # 每人云盘总配额


@bp.before_request
def _relax_body_limit():
    """只给「收文件」的两条路放宽请求体上限，其余接口仍受 app.py 的全局 64MB 保护。

    以前这里写着 200MB，app.py 的 MAX_CONTENT_LENGTH 却是 64MB —— 超过 64MB 的文件
    在进到视图函数之前就被 Flask 413 掉了，前端还照着「200MB」提示。表现出来就是
    「云盘传不了大文件」，且报错莫名其妙。现在统一以 DRIVE_MAX 为准。
    """
    if request.method == "POST" and (request.path == "/api/drive"
                                     or request.path.startswith("/api/chat/")):
        request.max_content_length = DRIVE_MAX + 16 * 1024 * 1024   # 留 multipart 边框的余量


# 浏览器自带播放器能直接放的（.mov/.flac 看运气，给了总比不给强）
MEDIA_EXT = {".mp4", ".webm", ".ogv", ".ogg", ".mov", ".m4v",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".opus"}


def _viewable(ext):
    ext = (ext or "").lower()
    return ext in INLINE_EXT or ext in OFFICE_EXT or ext in IMAGE_EXT or ext in MEDIA_EXT


def _drive_row(r):
    d = dict(r)
    d["is_dir"] = bool(d.get("is_dir"))
    d["viewable"] = (not d["is_dir"]) and _viewable(d.get("ext"))
    return d


def _drive_used(db, owner):
    return db.execute("SELECT COALESCE(SUM(size),0) FROM drive_files WHERE owner_id=?",
                      (owner,)).fetchone()[0]


def _ensure_folder_path(db, owner, path):
    """把 'a/b/c' 逐级补出 is_dir 行，返回规整后的路径。

    上传整个文件夹时，中间目录必须先在库里存在：drive_list 是按 folder 精确匹配列的，
    只有 is_dir 行才让人点得进去。缺了它，文件的 folder 指向一个列表里根本看不见的
    目录 —— 传上去了，但用户找不着，等于传丢了。
    """
    parent = ""
    for seg in (path or "").split("/"):
        seg = seg.strip()
        if not seg:
            continue
        if not db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? "
                          "AND is_dir=1", (owner, parent, seg)).fetchone():
            db.execute("INSERT INTO drive_files(owner_id,folder,name,is_dir,source) "
                       "VALUES(?,?,?,1,'drive')", (owner, parent, seg))
        parent = (parent + "/" + seg) if parent else seg
    return parent


# 排序白名单：直接拼进 SQL，所以只认这几个键，不能拿请求参数当列名用
_DRIVE_SORT = {"new": "id DESC", "old": "id ASC", "name": "name COLLATE NOCASE ASC",
               "big": "size DESC", "small": "size ASC"}


@bp.get("/api/drive")
def drive_list():
    """列目录；带 q 时改成**全盘按文件名搜**（搜索时不分目录，结果里带 folder 让人知道在哪）。"""
    folder = (request.args.get("folder") or "").strip().strip("/")
    q = (request.args.get("q") or "").strip()
    order = _DRIVE_SORT.get(request.args.get("sort") or "new", _DRIVE_SORT["new"])
    db = get_db()
    cols = ("SELECT id, folder, name, ext, mime, size, is_dir, source, created_at "
            "FROM drive_files WHERE owner_id=? ")
    if q:
        rows = db.execute(cols + "AND name LIKE ? ESCAPE '\\' ORDER BY is_dir DESC, " + order + " LIMIT 300",
                          (uid(), "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")).fetchall()
    else:
        rows = db.execute(cols + "AND folder=? ORDER BY is_dir DESC, " + order,
                          (uid(), folder)).fetchall()
    return jsonify({"folder": folder, "q": q, "items": [_drive_row(r) for r in rows],
                    "used": _drive_used(db, uid()), "quota": DRIVE_QUOTA, "max_file": DRIVE_MAX})


@bp.get("/api/drive/folders")
def drive_folders():
    """所有文件夹的路径清单，供「移动到…」的目录选择器用。"""
    rows = get_db().execute(
        "SELECT folder, name FROM drive_files WHERE owner_id=? AND is_dir=1", (uid(),)).fetchall()
    paths = sorted((r["folder"] + "/" + r["name"]) if r["folder"] else r["name"] for r in rows)
    return jsonify({"folders": paths})


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
        return jsonify({"error": "文件超过 %d MB" % (DRIVE_MAX // (1024 * 1024))}), 400
    db = get_db()
    if _drive_used(db, uid()) + size > DRIVE_QUOTA:
        return jsonify({"error": "云盘空间不足（配额 %d MB）" % (DRIVE_QUOTA // (1024 * 1024))}), 400
    # 传文件夹时前端把相对目录一并传上来，这里逐级补出中间目录
    folder = _ensure_folder_path(db, uid(), folder)
    name = os.path.basename((f.filename or "").replace("\\", "/")) or "未命名"
    ext = os.path.splitext(name)[1].lower()
    stored = uuid.uuid4().hex + ext
    f.save(os.path.join(_drive_dir(uid()), stored))
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
        "VALUES(?,?,?,?,?,?,?,0,'drive')",
        (uid(), folder, name, stored, ext, f.mimetype or "", size))
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


@bp.get("/api/drive/<int:fid>/view")
def drive_view(fid):
    """内联预览。和 /download 只差一个 as_attachment，但对图片/PDF/视频来说，
    这一个参数决定了是「在页面里直接看」还是「下载下来自己找程序打开」。"""
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "文件不存在"}), 404
    path = os.path.join(_drive_dir(uid()), r["stored_name"] or "")
    if not os.path.exists(path):
        return jsonify({"error": "文件丢失"}), 404
    ext = (r["ext"] or "").lower()
    if request.args.get("text") == "1":         # 阅读模式取纯文字
        return jsonify({"text": _extract_text(path, ext) or ""})
    mime = r["mime"] or ""
    if ext in OFFICE_EXT:                       # Office 浏览器打不开，转 PDF 再给（结果有缓存）
        pdf = _office_to_pdf(path)
        if not pdf:
            return jsonify({"error": "这个格式转不了，下载后再看"}), 415
        path, mime = pdf, "application/pdf"
    elif not _viewable(ext):
        return jsonify({"error": "这个格式不支持预览"}), 415
    # conditional=True 才会响应 Range 请求 —— 没有它，视频只能从头播，拖不动进度条
    return _cacheable(_no_script(send_file(
        path, as_attachment=False, download_name=r["name"],
        mimetype=mime or None, conditional=True)))


@bp.patch("/api/drive/<int:fid>")
def drive_patch(fid):
    """重命名 / 移动。

    文件夹在这套设计里只是一个 folder 字符串，没有父子外键 —— 所以动一个目录，
    必须把它所有子孙的 folder 前缀一起改；漏了就留下一堆指向旧路径的记录，
    它们既不在旧目录（旧目录没了）也不在新目录，等于凭空消失。
    """
    data = request.get_json(silent=True) or {}
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=?", (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "不存在"}), 404
    name = (data.get("name") if data.get("name") is not None else r["name"]) or ""
    name = name.strip().strip("/")[:120]
    folder = data.get("folder")
    folder = r["folder"] if folder is None else folder.strip().strip("/")
    if not name or "/" in name:
        return jsonify({"error": "名字不合法"}), 400
    old = (r["folder"] + "/" + r["name"]) if r["folder"] else r["name"]
    new = (folder + "/" + name) if folder else name
    if r["is_dir"] and (folder == old or folder.startswith(old + "/")):
        return jsonify({"error": "不能把文件夹移到它自己里面"}), 400
    if db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? AND id<>?",
                  (uid(), folder, name, fid)).fetchone():
        return jsonify({"error": "目标位置已有同名的"}), 400
    if folder and folder != r["folder"]:
        _ensure_folder_path(db, uid(), folder)
    db.execute("UPDATE drive_files SET name=?, folder=? WHERE id=?", (name, folder, fid))
    if r["is_dir"] and new != old:
        for k in db.execute("SELECT id, folder FROM drive_files WHERE owner_id=? AND "
                            "(folder=? OR folder LIKE ?)", (uid(), old, old + "/%")).fetchall():
            db.execute("UPDATE drive_files SET folder=? WHERE id=?",
                       (new + k["folder"][len(old):], k["id"]))
    db.commit()
    return jsonify({"ok": True, "name": name, "folder": folder})


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
            return jsonify({"error": "文件超过 %d MB" % (DRIVE_MAX // (1024 * 1024))}), 400
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
    resp = send_file(os.path.join(_drive_dir(owner), r["stored_name"]),
                     as_attachment=not inline, download_name=r["name"],
                     mimetype=r["mime"] or "application/octet-stream")
    # 聊天文件是**别人**发过来的，内联打开时更要挡住里面夹带的脚本
    return _no_script(resp) if inline else resp


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
