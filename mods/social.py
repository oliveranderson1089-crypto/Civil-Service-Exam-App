"""好友 / 云盘 / 聊天。

三块放一起是因为它们真的缠在一起：drive_send 把网盘文件发进聊天、
chat 的文件又能存回网盘、两者都要先是好友。硬拆成三个文件只会让
互相 import 绕圈，不如认下这个内聚。

_notify_chat 的 SSE 只是「即时亮一下」的加速通道：消息本身已经落
chat_msgs、通知已进 notifications，推送丢了浏览器重连就能拉回。
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
import zipfile

from flask import Blueprint, Response, jsonify, request, send_file

from werkzeug.security import check_password_hash, generate_password_hash

from core import CFG, DB, UPLOADS, get_db, log, open_db, uid, uname
import aiclient
from mods.ai import ai_chat
from mods.files import (IMAGE_EXT, INLINE_EXT, OFFICE_EXT, _cacheable,
                        _extract_text, _no_script, _office_to_pdf, _remove_blob)

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
DRIVE_QUOTA = int(CFG.get("drive_quota_mb", 20480)) * 1024 * 1024  # 每人云盘总配额（默认 20GB）


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
    # 网格视图据此决定「出缩略图还是出图标」，省得前端自己维护一份后缀表
    _e = (d.get("ext") or "").lower()
    # 视频也出封面（取首帧，要 ffmpeg）；取不到时前端的 onerror 会换回图标
    d["thumb"] = (not d["is_dir"]) and (_e in IMAGE_EXT or _e in MEDIA_EXT)
    return d


def _like_esc(s):
    """转义 LIKE 的通配符。

    子树查询都是 `folder=? OR folder LIKE ?` 配 `前缀/%`。folder 是**用户起的名字**，
    里面的 `_` 和 `%` 在 LIKE 里是通配符 —— 不转义的话，删「a_b」会连「aXb」里的东西
    一起删掉（实测复现过）。带下划线的目录名很常见，比如 xwechat_files。
    用它的地方都要跟上 ESCAPE '\\'。
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _subtree(path):
    """返回子树查询要用的两个参数：(自己, 子孙的 LIKE 前缀)。"""
    return path, _like_esc(path) + "/%"


def _drive_used(db, owner):
    """按**去重后**的实际占用算：同一份内容传两次只在磁盘上存一份，不该收两份的钱。"""
    return db.execute(
        "SELECT COALESCE(SUM(size),0) FROM ("
        "  SELECT DISTINCT stored_name, size FROM drive_files"
        "  WHERE owner_id=? AND is_dir=0 AND stored_name IS NOT NULL AND stored_name<>'')",
        (owner,)).fetchone()[0]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for blk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


def _drop_blob(db, owner, stored_name):
    """删磁盘文件，但**只在没有别的行还引用它的时候**。

    去重让多行共用一个 stored_name。要是照旧无条件 os.remove，删掉其中一行就会把
    另一行的文件也带走 —— 另一行还在列表里好好显示着，点开却是 404。
    调用前请先把要删的行从库里删掉，这里数的是「剩下还有几行在用」。
    """
    if not stored_name:
        return
    if db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND stored_name=? LIMIT 1",
                  (owner, stored_name)).fetchone():
        return                                   # 还有人在用，留着
    # 走 _remove_blob 而不是裸 os.remove：Office 预览会在旁边留一个同名 .pdf 缓存，
    # 只删原件的话那个 PDF 会永远留在磁盘上（没记录引用它，也不计进配额）
    _remove_blob(os.path.join(_drive_dir(owner), stored_name))


def _finish_upload(db, folder, name, tmp, mime):
    """临时文件 → 正式入库。去重、配额、补目录都收在这里，单发上传和分片上传共用一条路。

    返回 (row, None) 或 (None, (json响应, 状态码))。
    """
    size = os.path.getsize(tmp)
    digest = _sha256_file(tmp)
    dup = db.execute("SELECT stored_name FROM drive_files WHERE owner_id=? AND sha256=? "
                     "AND stored_name IS NOT NULL AND stored_name<>'' LIMIT 1",
                     (uid(), digest)).fetchone()
    if dup and not os.path.exists(os.path.join(_drive_dir(uid()), dup["stored_name"])):
        dup = None                               # 库里有记录但磁盘上没了，当没命中
    # 命中去重就不占新磁盘，配额自然也不该再扣一次
    if not dup and _drive_used(db, uid()) + size > DRIVE_QUOTA:
        os.remove(tmp)
        return None, (jsonify({"error": "云盘空间不足（配额 %d MB）"
                               % (DRIVE_QUOTA // (1024 * 1024))}), 400)
    ext = os.path.splitext(name)[1].lower()
    if dup:
        os.remove(tmp)
        stored = dup["stored_name"]
    else:
        stored = uuid.uuid4().hex + ext
        os.replace(tmp, os.path.join(_drive_dir(uid()), stored))
    folder = _ensure_folder_path(db, uid(), folder)
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source,sha256) "
        "VALUES(?,?,?,?,?,?,?,0,'drive',?)",
        (uid(), folder, name, stored, ext, mime or "", size, digest))
    db.commit()
    return db.execute("SELECT * FROM drive_files WHERE id=?", (cur.lastrowid,)).fetchone(), None


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
                          "AND is_dir=1 AND deleted_at IS NULL",
                          (owner, parent, seg)).fetchone():
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
            "FROM drive_files WHERE owner_id=? AND deleted_at IS NULL ")
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
        "SELECT folder, name FROM drive_files WHERE owner_id=? AND is_dir=1 "
        "AND deleted_at IS NULL", (uid(),)).fetchall()
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
    name = os.path.basename((f.filename or "").replace("\\", "/")) or "未命名"
    # 先落到临时名：要先算出 sha256 才知道这份内容是不是已经有了
    tmp = os.path.join(_drive_dir(uid()), ".tmp_" + uuid.uuid4().hex)
    f.save(tmp)
    row, err = _finish_upload(db, folder, name, tmp, f.mimetype)
    if err:
        return err
    return jsonify(_drive_row(row)), 201


@bp.post("/api/drive/instant")
def drive_instant():
    """秒传：前端先报 sha256，服务端已经有这份内容就直接建条记录，一个字节都不用传。

    重复上传同一份资料（换个目录再放一份、或换台设备重传）是最常见的情况，
    这条能把它从「传 200MB」变成「一次 JSON 往返」。
    """
    data = request.get_json(silent=True) or {}
    digest = (data.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return jsonify({"error": "sha256 不合法"}), 400
    name = os.path.basename((data.get("name") or "").replace("\\", "/")) or "未命名"
    folder = (data.get("folder") or "").strip().strip("/")
    db = get_db()
    old = db.execute("SELECT * FROM drive_files WHERE owner_id=? AND sha256=? AND is_dir=0 "
                     "AND stored_name IS NOT NULL AND stored_name<>'' LIMIT 1",
                     (uid(), digest)).fetchone()
    if not old or not os.path.exists(os.path.join(_drive_dir(uid()), old["stored_name"])):
        return jsonify({"hit": False})
    folder = _ensure_folder_path(db, uid(), folder)
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source,sha256) "
        "VALUES(?,?,?,?,?,?,?,0,'drive',?)",
        (uid(), folder, name, old["stored_name"], os.path.splitext(name)[1].lower(),
         old["mime"], old["size"], digest))
    db.commit()
    row = db.execute("SELECT * FROM drive_files WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(_drive_row(row), hit=True)), 201


# ---- 分片上传 ----
# 走 Cloudflare 隧道时请求体有 100MB 硬上限（免费版），单请求再怎么放宽
# max_content_length 都没用 —— 只能切成小块分多次请求送。顺带换来断点续传。
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
CHUNK_TTL = 24 * 3600            # 没传完的会话留一天，之后当垃圾清掉
CHUNK_SLACK = 4 * 1024 * 1024    # 允许比声明大小多出这点（重传同一块时的容差）


def _chunk_dir(owner, upload_id):
    """会话目录。upload_id 只认 32 位十六进制 —— 它来自 URL，不校验就能拿 ../ 跳出去。"""
    if not _HEX32.match(upload_id or ""):
        return None
    return os.path.join(_drive_dir(owner), ".chunks", upload_id)


def _sweep_stale(owner):
    """清掉过期的分片会话，以及上传中断留下的 .tmp_ 暂存件。

    .tmp_ 是 _finish_upload 之前的落脚点：客户端中途断开（关标签页、隧道掉线）就没人
    再管它了 —— 没有任何记录引用它、不计进配额、用户也看不见，只会慢慢把磁盘吃掉。
    """
    now = time.time()
    root = os.path.join(_drive_dir(owner), ".chunks")
    if os.path.isdir(root):
        for d in os.listdir(root):
            p = os.path.join(root, d)
            try:
                if now - os.path.getmtime(p) > CHUNK_TTL:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                log.debug("清理分片残留失败", exc_info=True)
    for f in os.listdir(_drive_dir(owner)):
        if not f.startswith(".tmp_"):
            continue
        p = os.path.join(_drive_dir(owner), f)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > CHUNK_TTL:
                os.remove(p)
        except Exception:
            log.debug("清理上传暂存失败", exc_info=True)


@bp.post("/api/drive/chunk/init")
def chunk_init():
    data = request.get_json(silent=True) or {}
    size = int(data.get("size") or 0)
    name = os.path.basename((data.get("name") or "").replace("\\", "/")) or "未命名"
    folder = (data.get("folder") or "").strip().strip("/")
    if size <= 0 or size > DRIVE_MAX:
        return jsonify({"error": "文件超过 %d MB" % (DRIVE_MAX // (1024 * 1024))}), 400
    db = get_db()
    if _drive_used(db, uid()) + size > DRIVE_QUOTA:
        return jsonify({"error": "云盘空间不足（配额 %d MB）" % (DRIVE_QUOTA // (1024 * 1024))}), 400
    _sweep_stale(uid())
    upload_id = uuid.uuid4().hex
    d = _chunk_dir(uid(), upload_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fp:
        json.dump({"name": name, "folder": folder, "size": size,
                   "mime": data.get("mime") or ""}, fp, ensure_ascii=False)
    return jsonify({"upload_id": upload_id, "received": []}), 201


@bp.get("/api/drive/chunk/<upload_id>")
def chunk_status(upload_id):
    """已经收到哪些块 —— 断点续传靠它，传一半断了重开时接着传。"""
    d = _chunk_dir(uid(), upload_id)
    if not d or not os.path.isdir(d):
        return jsonify({"error": "会话不存在"}), 404
    return jsonify({"received": sorted(int(x) for x in os.listdir(d) if x.isdigit())})


@bp.post("/api/drive/chunk/<upload_id>/<int:idx>")
def chunk_put(upload_id, idx):
    d = _chunk_dir(uid(), upload_id)
    if not d or not os.path.isdir(d):
        return jsonify({"error": "会话不存在"}), 404
    if idx < 0 or idx > 100000:
        return jsonify({"error": "块号不合法"}), 400
    # 暂存也要有上限：init 只校验了「声明的大小」，若不看实际落盘量，客户端可以一直往
    # 会话里灌块，把磁盘写满 —— 这些字节不属于任何记录，_drive_used 也数不到它们。
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as fp:
            declared = int(json.load(fp).get("size") or 0)
    except Exception:
        return jsonify({"error": "会话已损坏，请重传"}), 400
    have = 0
    for x in os.listdir(d):
        if x.isdigit() and x != str(idx):
            have += os.path.getsize(os.path.join(d, x))
    blob = request.files.get("chunk")
    data = blob.read() if blob else request.get_data()
    if have + len(data) > declared + CHUNK_SLACK:
        return jsonify({"error": "传的比说好的多，已中止"}), 400
    with open(os.path.join(d, str(idx)), "wb") as fp:
        fp.write(data)
    return jsonify({"ok": True, "index": idx})


@bp.post("/api/drive/chunk/<upload_id>/done")
def chunk_done(upload_id):
    d = _chunk_dir(uid(), upload_id)
    if not d or not os.path.isdir(d):
        return jsonify({"error": "会话不存在"}), 404
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as fp:
            meta = json.load(fp)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        return jsonify({"error": "会话已损坏，请重传"}), 400
    parts = sorted(int(x) for x in os.listdir(d) if x.isdigit())
    if parts != list(range(len(parts))) or not parts:
        missing = [i for i in range(max(parts) + 1 if parts else 0) if i not in set(parts)]
        return jsonify({"error": "分片不连续，缺第 %s 块" % (missing[:5] or "?")}), 400
    tmp = os.path.join(_drive_dir(uid()), ".tmp_" + uuid.uuid4().hex)
    with open(tmp, "wb") as out:
        for i in parts:
            with open(os.path.join(d, str(i)), "rb") as fp:
                shutil.copyfileobj(fp, out)
    # 拼完对一下大小：少一块、或某块只传了一半，这里能当场发现，不会把半个文件入库
    if os.path.getsize(tmp) != meta.get("size"):
        os.remove(tmp)
        return jsonify({"error": "拼出来的大小和说好的对不上，请重传"}), 400
    row, err = _finish_upload(get_db(), meta.get("folder") or "", meta.get("name") or "未命名",
                              tmp, meta.get("mime") or "")
    shutil.rmtree(d, ignore_errors=True)
    if err:
        return err
    return jsonify(_drive_row(row)), 201


@bp.post("/api/drive/folder")
def drive_mkdir():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip().strip("/")[:40]
    parent = (data.get("parent") or "").strip().strip("/")
    if not name or "/" in name:
        return jsonify({"error": "文件夹名不合法"}), 400
    path = (parent + "/" + name) if parent else name
    db = get_db()
    if db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? AND is_dir=1 "
                  "AND deleted_at IS NULL", (uid(), parent, name)).fetchone():
        return jsonify({"error": "已有同名文件夹"}), 400
    db.execute("INSERT INTO drive_files(owner_id,folder,name,is_dir,source) VALUES(?,?,?,1,'drive')",
               (uid(), parent, name))
    db.commit()
    return jsonify({"ok": True, "path": path})


@bp.get("/api/drive/<int:fid>/download")
def drive_download(fid):
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0 "
                   "AND deleted_at IS NULL", (fid, uid())).fetchone()
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
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0 "
                   "AND deleted_at IS NULL", (fid, uid())).fetchone()
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
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "不存在"}), 404
    name = (data.get("name") if data.get("name") is not None else r["name"]) or ""
    name = name.strip().strip("/")[:120]
    folder = data.get("folder")
    folder = r["folder"] if folder is None else folder.strip().strip("/")
    if not name or "/" in name:
        return jsonify({"error": "名字不合法"}), 400
    # 先把目标路径规整掉（每段去空白、去空段），再拿规整后的去做各项检查 ——
    # 否则「甲/ 乙」会绕过重名检查、也绕过「移进自己」的判断，最后文件落在一个
    # 建都没建过的目录里，列表按 folder 精确匹配，点不进去 = 静默丢失。
    folder = "/".join(seg.strip() for seg in folder.split("/") if seg.strip())
    old = (r["folder"] + "/" + r["name"]) if r["folder"] else r["name"]
    new = (folder + "/" + name) if folder else name
    if r["is_dir"] and (folder == old or folder.startswith(old + "/")):
        return jsonify({"error": "不能把文件夹移到它自己里面"}), 400
    if db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? AND id<>? "
                  "AND deleted_at IS NULL", (uid(), folder, name, fid)).fetchone():
        return jsonify({"error": "目标位置已有同名的"}), 400
    if folder and folder != r["folder"]:
        _ensure_folder_path(db, uid(), folder)      # 规整过了，返回值必然等于 folder
    db.execute("UPDATE drive_files SET name=?, folder=? WHERE id=?", (name, folder, fid))
    if r["is_dir"] and new != old:
        for k in db.execute("SELECT id, folder FROM drive_files WHERE owner_id=? AND "
                            "(folder=? OR folder LIKE ? ESCAPE '\\')",
                            (uid(),) + _subtree(old)).fetchall():
            db.execute("UPDATE drive_files SET folder=? WHERE id=?",
                       (new + k["folder"][len(old):], k["id"]))
    db.commit()
    return jsonify({"ok": True, "name": name, "folder": folder})


# ---- 文件夹打包下载 ----
ZIP_MAX = int(CFG.get("drive_zip_max_mb", 2048)) * 1024 * 1024      # 打包总量上限


def _folder_files(db, owner, path):
    """一个文件夹底下的所有文件，返回 [(zip 里的相对路径, 磁盘路径, 大小)]。"""
    rows = db.execute(
        "SELECT folder, name, stored_name, size FROM drive_files WHERE owner_id=? AND is_dir=0 "
        "AND (folder=? OR folder LIKE ? ESCAPE '\\') AND deleted_at IS NULL "
        "AND stored_name IS NOT NULL AND stored_name<>''",
        (owner,) + _subtree(path)).fetchall()
    base = os.path.dirname(path)            # 让 zip 里的顶层就是这个文件夹本身
    out = []
    for r in rows:
        rel = ((r["folder"] + "/" + r["name"]) if r["folder"] else r["name"])
        if base:
            rel = rel[len(base) + 1:]
        out.append((rel, os.path.join(_drive_dir(owner), r["stored_name"]), r["size"] or 0))
    return out


def _zip_folder(db, owner, r):
    """把一个文件夹打成 zip，返回临时文件路径；超限或空目录返回 (None, 错误响应)。

    写到临时文件而不是全在内存里拼：一个几百 MB 的目录直接进内存，服务端会被一个
    下载请求打垮。调用方负责用完删掉。
    """
    path = (r["folder"] + "/" + r["name"]) if r["folder"] else r["name"]
    items = _folder_files(db, owner, path)
    if not items:
        return None, (jsonify({"error": "这个文件夹是空的，没什么可打包"}), 400)
    total = sum(n for _, _, n in items)
    if total > ZIP_MAX:
        return None, (jsonify({"error": "文件夹太大（%d MB），超过打包上限 %d MB"
                               % (total // (1024 * 1024), ZIP_MAX // (1024 * 1024))}), 413)
    tmp = os.path.join(_drive_dir(owner), ".tmp_zip_" + uuid.uuid4().hex)
    try:
        # ZIP_STORED 不压缩：云盘里多是 pdf/图片/视频，本来就压不动，白费 CPU
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for rel, src, _n in items:
                if os.path.exists(src):
                    z.write(src, rel)
    except Exception:
        log.debug("打包失败", exc_info=True)
        try:
            os.remove(tmp)
        except Exception:
            pass
        return None, (jsonify({"error": "打包失败"}), 500)
    return tmp, None


def _send_temp(path, download_name):
    """发一个临时文件，**先 unlink 再发**。

    POSIX 下已经打开的 fd 在文件被 unlink 之后照样读得完，所以这样既能正常下发、
    又保证磁盘一定回收 —— 哪怕进程中途崩了，内核也会在 fd 关闭时收走。

    原来用 resp.call_on_close 挂回调，实测**回调没被触发**、每下载一次就留一个几百 MB
    的 .tmp_zip_ 在磁盘上。「发完再删」这种依赖回调时机的写法不可靠，unlink 才是硬的。
    """
    size = os.path.getsize(path)
    fp = open(path, "rb")
    try:
        os.remove(path)
    except Exception:
        log.debug("临时 zip 没删掉", exc_info=True)
    resp = _no_script(send_file(fp, as_attachment=True, download_name=download_name,
                                mimetype="application/zip"))
    resp.headers["Content-Length"] = str(size)   # 文件对象拿不到大小，得自己带上
    return resp


@bp.get("/api/drive/<int:fid>/zip")
def drive_zip(fid):
    """整个文件夹打包下载。"""
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=1 "
                   "AND deleted_at IS NULL", (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "文件夹不存在"}), 404
    tmp, err = _zip_folder(db, uid(), r)
    if err:
        return err
    return _send_temp(tmp, r["name"] + ".zip")


# ---- 缩略图（网格视图用）----
THUMB_PX = 320


def _thumb_path(owner, stored):
    return os.path.join(_drive_dir(owner), os.path.splitext(stored)[0] + ".thumb.jpg")


def _video_frame(src, dst):
    """取视频首帧当封面。**没装 ffmpeg 就返回 False**，调用方退回图标 —— 缺个可选依赖
    不该让整个网格视图报错。装了 ffmpeg 之后不用改代码，重启即生效。"""
    try:
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", src, "-frames:v", "1",
                        "-vf", "scale=%d:-1" % THUMB_PX, "-f", "image2", dst],
                       timeout=30, check=True, capture_output=True)
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        log.debug("取视频首帧失败（没装 ffmpeg 就是正常的）", exc_info=True)
        return False


def _make_thumb(src, dst):
    """生成缩略图。失败返回 False —— 调用方退回图标，不要让列表因为一张坏图整个崩掉。"""
    if os.path.splitext(src)[1].lower() in MEDIA_EXT:
        return _video_frame(src, dst)
    try:
        from PIL import Image, ImageOps
        try:                                    # iPhone 的 HEIC
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            log.debug("pillow_heif 没装，HEIC 出不了缩略图", exc_info=True)
        im = Image.open(src)
        im.load()                               # 多帧 GIF 只取第一帧
        im = ImageOps.exif_transpose(im)        # 手机竖拍的照片不转就是躺着的
        if im.mode in ("RGBA", "LA", "P"):      # 透明底转 JPEG 会变黑，先铺白
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
        im.save(dst, "JPEG", quality=82, optimize=True)
        return True
    except Exception:
        log.debug("生成缩略图失败", exc_info=True)
        return False


@bp.get("/api/drive/<int:fid>/thumb")
def drive_thumb(fid):
    """图片缩略图，网格视图靠它。就地缓存成 <uuid>.thumb.jpg，删文件时由 _remove_blob 一并清。"""
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0 "
                   "AND deleted_at IS NULL", (fid, uid())).fetchone()
    ext = (r["ext"] or "").lower() if r else ""
    if not r or not (ext in IMAGE_EXT or ext in MEDIA_EXT):
        return jsonify({"error": "没有缩略图"}), 404
    src = os.path.join(_drive_dir(uid()), r["stored_name"] or "")
    if not os.path.exists(src):
        return jsonify({"error": "文件丢失"}), 404
    dst = _thumb_path(uid(), r["stored_name"])
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        if not _make_thumb(src, dst):
            return jsonify({"error": "这张图生成不了缩略图"}), 415
    return _cacheable(_no_script(send_file(dst, mimetype="image/jpeg")))


# ---- 分享链接 ----
SHARE_DAYS = int(CFG.get("drive_share_days", 7))


def _share_row(r):
    return {"id": r["id"], "token": r["token"], "file_id": r["file_id"],
            "name": r["name"], "size": r["size"], "hits": r["hits"],
            "is_dir": bool(r["is_dir"]), "has_pw": bool(r["pw_hash"]),
            "expires_at": r["expires_at"], "url": "/s/" + r["token"]}


@bp.post("/api/drive/<int:fid>/share")
def drive_share(fid):
    """给一个文件建分享链接。同一个文件已有未过期的链接就复用，别越点越多。"""
    days = int((request.get_json(silent=True) or {}).get("days") or SHARE_DAYS)
    days = max(1, min(days, 365))
    db = get_db()
    pw = ((request.get_json(silent=True) or {}).get("password") or "").strip()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "文件不存在"}), 404
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    old = db.execute("SELECT * FROM drive_shares WHERE owner_id=? AND file_id=? "
                     "AND (expires_at IS NULL OR expires_at > ?)", (uid(), fid, now)).fetchone()
    if old:
        return jsonify(_share_row(dict(old, name=r["name"], size=r["size"])))
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + days * 86400))
    token = secrets.token_urlsafe(24)          # 192 位，猜不出来
    cur = db.execute(
        "INSERT INTO drive_shares(token,file_id,owner_id,expires_at,pw_hash,is_dir) "
        "VALUES(?,?,?,?,?,?)",
        (token, fid, uid(), exp, generate_password_hash(pw) if pw else None, 1 if r["is_dir"] else 0))
    db.commit()
    return jsonify(_share_row({"id": cur.lastrowid, "token": token, "file_id": fid,
                               "name": r["name"], "size": r["size"], "hits": 0,
                               "is_dir": r["is_dir"], "pw_hash": pw or None,
                               "expires_at": exp})), 201


@bp.get("/api/drive/shares")
def drive_shares():
    rows = get_db().execute(
        "SELECT s.*, f.name, f.size FROM drive_shares s JOIN drive_files f ON f.id=s.file_id "
        "WHERE s.owner_id=? AND f.deleted_at IS NULL ORDER BY s.id DESC LIMIT 200",
        (uid(),)).fetchall()
    return jsonify({"shares": [_share_row(r) for r in rows], "days": SHARE_DAYS})


@bp.delete("/api/drive/shares/<int:sid>")
def drive_share_del(sid):
    db = get_db()
    db.execute("DELETE FROM drive_shares WHERE id=? AND owner_id=?", (sid, uid()))
    db.commit()
    return jsonify({"ok": True})


_PW_PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需要访问密码</title>
<style>body{font-family:system-ui,-apple-system,"Noto Sans CJK SC",sans-serif;background:#f4f6fa;
margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}
.c{background:#fff;padding:28px 26px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.08);
width:min(340px,90vw)}h1{font-size:17px;margin:0 0 4px}p{color:#6b7480;font-size:13px;margin:0 0 16px}
input{width:100%%;box-sizing:border-box;padding:10px 12px;border:1px solid #dfe4ec;border-radius:9px;
font-size:15px}button{width:100%%;margin-top:12px;padding:10px;border:0;border-radius:9px;
background:#2f7fe0;color:#fff;font-size:15px;cursor:pointer}.e{color:#c0392b;font-size:13px;margin-top:10px}
</style><div class="c"><h1>%s</h1><p>这个分享需要访问密码</p>
<form method="post"><input type="password" name="pw" placeholder="请输入访问密码" autofocus>
<button type="submit">打开</button></form>%s</div>"""


def _pw_page(name, wrong=False):
    from markupsafe import escape
    return _PW_PAGE % (escape(name), '<div class="e">密码不对，再试一次</div>' if wrong else "")


@bp.route("/s/<token>", methods=["GET", "POST"])
def drive_share_get(token):
    """**不需要登录**的取件口（app.py 的 _is_public 放行了 /s/）。

    正因为不需要登录，这里每一步都得自己查：token 对不对、过没过期、东西还在不在、
    有没有被扔进回收站、要不要密码。一律当附件下发并关进沙箱 —— 公开地址上绝不能
    内联渲染别人上传的 .html。文件夹则现打包成 zip 再给。
    """
    db = get_db()
    s = db.execute("SELECT * FROM drive_shares WHERE token=?", (token,)).fetchone()
    if not s:
        return "链接无效", 404
    if s["expires_at"] and s["expires_at"] <= time.strftime("%Y-%m-%d %H:%M:%S"):
        return "链接已过期", 410
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND deleted_at IS NULL",
                   (s["file_id"],)).fetchone()
    if not r:
        return "文件已被删除", 404
    if s["pw_hash"]:                       # 要密码：GET 给表单，POST 验一下
        pw = (request.form.get("pw") or request.args.get("pw") or "")
        if not check_password_hash(s["pw_hash"], pw):
            return _pw_page(r["name"], wrong=bool(pw)), (401 if pw else 200)
    db.execute("UPDATE drive_shares SET hits=hits+1 WHERE id=?", (s["id"],))
    db.commit()
    if r["is_dir"]:                        # 文件夹 → 现打包
        tmp, err = _zip_folder(db, s["owner_id"], r)
        if err:
            return err
        return _send_temp(tmp, r["name"] + ".zip")
    path = os.path.join(_drive_dir(s["owner_id"]), r["stored_name"] or "")
    if not os.path.exists(path):
        return "文件已丢失", 404
    return _no_script(send_file(path, as_attachment=True, download_name=r["name"],
                                mimetype=r["mime"] or "application/octet-stream"))


def _uniq_name(db, owner, folder, name):
    """同目录重名就叫「x 副本.txt」—— 复制到原地是很常见的操作，不能直接 400 顶回去。"""
    def taken(n):
        return db.execute("SELECT 1 FROM drive_files WHERE owner_id=? AND folder=? AND name=? "
                          "AND deleted_at IS NULL", (owner, folder, n)).fetchone()
    if not taken(name):
        return name
    stem, ext = os.path.splitext(name)
    for i in range(2, 100):
        cand = "%s 副本%s%s" % (stem, "" if i == 2 else str(i), ext)
        if not taken(cand):
            return cand
    return "%s %s%s" % (stem, uuid.uuid4().hex[:6], ext)


@bp.post("/api/drive/<int:fid>/copy")
def drive_copy(fid):
    """复制到另一个目录。

    内容一个字节都不用动：新行沿用同一个 stored_name / sha256，靠去重那套共用磁盘上
    那一份。所以复制是瞬时的、也不吃配额（_drive_used 按 DISTINCT stored_name 算）。
    """
    dest = ((request.get_json(silent=True) or {}).get("folder") or "").strip().strip("/")
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "不存在"}), 404
    src = (r["folder"] + "/" + r["name"]) if r["folder"] else r["name"]
    if r["is_dir"] and (dest == src or dest.startswith(src + "/")):
        return jsonify({"error": "不能把文件夹复制到它自己里面"}), 400
    dest = _ensure_folder_path(db, uid(), dest)
    name = _uniq_name(db, uid(), dest, r["name"])
    if r["is_dir"]:
        newtop = (dest + "/" + name) if dest else name
        db.execute("INSERT INTO drive_files(owner_id,folder,name,is_dir,source) VALUES(?,?,?,1,'drive')",
                   (uid(), dest, name))
        for k in db.execute("SELECT * FROM drive_files WHERE owner_id=? AND "
                            "(folder=? OR folder LIKE ? ESCAPE '\\') AND deleted_at IS NULL",
                            (uid(),) + _subtree(src)).fetchall():
            db.execute(
                "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,"
                "source,sha256) VALUES(?,?,?,?,?,?,?,?,'drive',?)",
                (uid(), newtop + k["folder"][len(src):], k["name"], k["stored_name"], k["ext"],
                 k["mime"], k["size"], k["is_dir"], k["sha256"]))
    else:
        db.execute(
            "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,"
            "source,sha256) VALUES(?,?,?,?,?,?,?,0,'drive',?)",
            (uid(), dest, name, r["stored_name"], r["ext"], r["mime"], r["size"], r["sha256"]))
    db.commit()
    return jsonify({"ok": True, "name": name, "folder": dest}), 201


@bp.delete("/api/drive/<int:fid>")
def drive_del(fid):
    db = get_db()
    # 必须带 deleted_at IS NULL：对已经在回收站里的东西再删一次，会给它重打一个
    # del_batch，于是它和当初一起删的那批脱钩 —— 恢复父文件夹时它不会跟着回来，
    # 而且不报错（搜索结果里同时选中父目录和它的子文件，批量删除就会这样）。
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "不存在"}), 404
    # 软删：只打个时间戳，磁盘上的东西一个字节不动，还能后悔。
    # 整批共用一个 batch 号 —— 恢复文件夹时靠它认出「哪些是跟着这次一起删的」。
    # 别拿 deleted_at 当批次认：它只精确到秒，同一秒里删两次就会串批，表现是
    # 「恢复一个文件夹，把早先单独删掉的东西也一并捞了回来」。
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    batch = uuid.uuid4().hex
    if r["is_dir"]:
        sub = r["name"] if not r["folder"] else (r["folder"] + "/" + r["name"])
        db.execute("UPDATE drive_files SET deleted_at=?, del_batch=? WHERE owner_id=? AND "
                   "(folder=? OR folder LIKE ? ESCAPE '\\') AND deleted_at IS NULL",
                   (ts, batch, uid()) + _subtree(sub))
    db.execute("UPDATE drive_files SET deleted_at=?, del_batch=? WHERE id=?", (ts, batch, fid))
    db.commit()
    return jsonify({"ok": True, "trashed": True})


# ---- 回收站 ----
TRASH_DAYS = int(CFG.get("drive_trash_days", 30))


def _kids_of(db, owner, r):
    """一个文件夹在这次删除批次里带走的所有子孙（靠 del_batch 认，不靠时间戳）。"""
    sub = r["name"] if not r["folder"] else (r["folder"] + "/" + r["name"])
    return db.execute("SELECT id, stored_name FROM drive_files WHERE owner_id=? AND "
                      "(folder=? OR folder LIKE ? ESCAPE '\\') AND del_batch=? "
                      "AND del_batch IS NOT NULL",
                      (owner,) + _subtree(sub) + (r["del_batch"],)).fetchall()


def _purge(db, owner, rows):
    """从库里和磁盘上真正抹掉。磁盘那步走 _drop_blob，共用同一份内容的别误伤。"""
    ids = [r["id"] for r in rows]
    if not ids:
        return
    blobs = {r["stored_name"] for r in rows if r["stored_name"]}
    # 分批删：一次一个占位符，清空一个几百上千项的回收站会撞上 SQLite 的
    # 宿主参数上限（老版本 999），抛异常时前面的 blob 已经删了，留下半清空的烂摊子
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        db.execute("DELETE FROM drive_files WHERE id IN (%s)" % ",".join("?" * len(part)), part)
    for b in blobs:
        _drop_blob(db, owner, b)


def _purge_expired(db, owner):
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S",
                           time.localtime(time.time() - TRASH_DAYS * 86400))
    rows = db.execute("SELECT id, stored_name FROM drive_files WHERE owner_id=? AND "
                      "deleted_at IS NOT NULL AND deleted_at < ?", (owner, cutoff)).fetchall()
    if rows:
        _purge(db, owner, rows)
        db.commit()


@bp.get("/api/drive/trash")
def drive_trash():
    db = get_db()
    _purge_expired(db, uid())          # 顺手把过期的清了，不额外挂定时器
    rows = db.execute(
        "SELECT id, folder, name, ext, mime, size, is_dir, source, created_at, deleted_at "
        "FROM drive_files WHERE owner_id=? AND deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC, id DESC LIMIT 500", (uid(),)).fetchall()
    held = db.execute(
        "SELECT COALESCE(SUM(size),0) FROM ("
        "  SELECT DISTINCT stored_name, size FROM drive_files"
        "  WHERE owner_id=? AND is_dir=0 AND deleted_at IS NOT NULL"
        "    AND stored_name IS NOT NULL AND stored_name<>'')", (uid(),)).fetchone()[0]
    return jsonify({"items": [_drive_row(r) for r in rows], "days": TRASH_DAYS, "held": held})


@bp.post("/api/drive/trash/<int:fid>/restore")
def trash_restore(fid):
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NOT NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "回收站里没有它"}), 404
    # 原来所在的目录可能也被删了 —— 补回来，否则恢复出来的东西列表里根本看不见
    _ensure_folder_path(db, uid(), r["folder"])
    if r["is_dir"]:
        for k in _kids_of(db, uid(), r):
            db.execute("UPDATE drive_files SET deleted_at=NULL, del_batch=NULL WHERE id=?", (k["id"],))
    db.execute("UPDATE drive_files SET deleted_at=NULL, del_batch=NULL WHERE id=?", (fid,))
    db.commit()
    return jsonify({"ok": True, "folder": r["folder"]})


@bp.delete("/api/drive/trash/<int:fid>")
def trash_purge_one(fid):
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND deleted_at IS NOT NULL",
                   (fid, uid())).fetchone()
    if not r:
        return jsonify({"error": "回收站里没有它"}), 404
    rows = list(_kids_of(db, uid(), r)) if r["is_dir"] else []
    rows.append(r)
    _purge(db, uid(), rows)
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/drive/trash/empty")
def trash_empty():
    db = get_db()
    rows = db.execute("SELECT id, stored_name FROM drive_files WHERE owner_id=? AND "
                      "deleted_at IS NOT NULL", (uid(),)).fetchall()
    _purge(db, uid(), rows)
    db.commit()
    return jsonify({"ok": True, "n": len(rows)})


@bp.post("/api/drive/<int:fid>/send")
def drive_send(fid):
    """把云盘里的一个文件发给某个好友（走聊天）。"""
    to = int((request.get_json(silent=True) or {}).get("to") or 0)
    db = get_db()
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0 "
                   "AND deleted_at IS NULL", (fid, uid())).fetchone()
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
def _dedup_stored(db, owner, digest):
    """这个人云盘里已经有这份内容了吗（sha256 命中、且磁盘上确实还在）。命中就别再占一份盘。"""
    if not digest:
        return None
    r = db.execute("SELECT stored_name FROM drive_files WHERE owner_id=? AND sha256=? "
                   "AND stored_name IS NOT NULL AND stored_name<>'' LIMIT 1",
                   (owner, digest)).fetchone()
    if r and os.path.exists(os.path.join(_drive_dir(owner), r["stored_name"])):
        return r["stored_name"]
    return None


def _chat_copy_to_drive(db, to, name, src_dir, stored_name, ext, mime, size, digest=None):
    """收到的文件也放进收件人云盘的「聊天文件」文件夹里，方便他保存/转存。

    先按 sha256 看收件人自己云盘里有没有同一份内容：命中就直接引用那个 stored_name。
    原先是无条件 copyfile —— 发一个 50MB 的资料，两人各占 50MB 配额，而云盘上传那条路
    早就有 sha256 秒传，聊天这条路一直没走。共用 stored_name 是安全的：_drop_blob
    删物理文件前会先数还有几行在引用它。
    """
    dst = _dedup_stored(db, to, digest)
    if not dst:
        dst = uuid.uuid4().hex + (ext or "")
        try:
            shutil.copyfile(os.path.join(src_dir, stored_name), os.path.join(_drive_dir(to), dst))
        except Exception:
            return None
    cur = db.execute(
        "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source,sha256) "
        "VALUES(?,?,?,?,?,?,?,0,'chat',?)",
        (to, "聊天文件", name, dst, ext, mime or "", size, digest))
    return cur.lastrowid


VOICE_MAX_SECONDS = 300   # 一条语音最长多久（前端到点自动停，这里是最后一道闸）
VOICE_EXT = {".webm": "audio/webm", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
             ".mp4": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def _voice_body(dur, text=""):
    """语音消息的 body。

    chat_msgs 没有「时长」「转写文本」这两列，也不值得为它们加列：语音消息本身
    就是一条文件消息，多出来的两样都是显示用的小数据，塞进本就空着的 body 里
    （跟内容卡片一个路数），老数据和老客户端都不受影响。
    """
    return json.dumps({"dur": round(float(dur or 0), 1), "text": text or ""}, ensure_ascii=False)


def _voice_of(r):
    try:
        d = json.loads(r["body"] or "{}")
        return {"dur": float(d.get("dur") or 0), "text": str(d.get("text") or "")}
    except Exception:
        return {"dur": 0.0, "text": ""}       # 脏数据也要能画出气泡，音频本身还在


def _voice_meta(f, path):
    """收一段上传的录音：确认它像音频，量出真实时长。

    时长以服务端 ffprobe 为准 —— 前端报的那个来自 MediaRecorder，Chrome 在
    「录完立刻停」的片子上经常给出 Infinity 或 0，直接信它气泡上就是「0″」。
    """
    from mods.asr import audio_duration
    ext = os.path.splitext(f.filename or "")[1].lower()
    mime = (f.mimetype or "").lower()
    if not mime.startswith("audio/") and ext not in VOICE_EXT:
        return None, "这不像一段录音"
    dur = audio_duration(path)
    if dur > VOICE_MAX_SECONDS:
        return None, "语音最长 %d 秒" % VOICE_MAX_SECONDS
    return dur, ""


def _chat_send_file(db, frm, to, name, stored_name, size, mime, src_dir, digest=None, reply_to=None,
                    voice=None):
    ext = os.path.splitext(name)[1].lower()
    fid_to = _chat_copy_to_drive(db, to, name, src_dir, stored_name, ext, mime, size, digest)
    kind = ("voice" if voice is not None else
            "image" if (mime or "").startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")
            else "file")
    cur = db.execute(
        "INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,file_id,file_name,file_size,file_mime,reply_to) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (frm, to, _direct_conv(db, frm, to), kind, _voice_body(voice), fid_to, name, size,
         mime or "", reply_to or None))
    # 通知放到调用方 commit 之后（见 chat_send/drive_send），否则对方可能在提交前就来拉、扑空
    return cur.lastrowid


# ================================================================ 会话（一对一 + 小组共用）
def _direct_conv(db, a, b, create=True):
    """(a,b) 这一对的一对一会话 id。a==b 就是文件传输助手。没有就建一条。"""
    lo, hi = min(a, b), max(a, b)
    r = db.execute(
        "SELECT c.id FROM conversations c WHERE c.kind='direct' AND EXISTS("
        "  SELECT 1 FROM chat_msgs m WHERE m.conv_id=c.id AND MIN(m.from_uid,m.to_uid)=? "
        "  AND MAX(m.from_uid,m.to_uid)=?) LIMIT 1", (lo, hi)).fetchone()
    if r:
        return r["id"]
    # 还没发过消息的一对：靠成员表找（两人且都在里面）
    r = db.execute(
        "SELECT m1.conv_id FROM conv_members m1 JOIN conv_members m2 ON m2.conv_id=m1.conv_id "
        "JOIN conversations c ON c.id=m1.conv_id "
        "WHERE c.kind='direct' AND m1.user_id=? AND m2.user_id=? "
        "AND (SELECT COUNT(*) FROM conv_members x WHERE x.conv_id=m1.conv_id)=? LIMIT 1",
        (lo, hi, 1 if lo == hi else 2)).fetchone()
    if r:
        return r["conv_id"]
    if not create:
        return 0
    cid = db.execute("INSERT INTO conversations(kind,title) VALUES('direct','')").lastrowid
    for u in {lo, hi}:
        db.execute("INSERT OR IGNORE INTO conv_members(conv_id,user_id) VALUES(?,?)", (cid, u))
    return cid


def _is_member(db, cid, u):
    return bool(db.execute("SELECT 1 FROM conv_members WHERE conv_id=? AND user_id=?",
                           (cid, u)).fetchone())


def _conv_peers(db, cid, exclude=None):
    """会话里除了 exclude 之外的人（推送/通知要挨个发）。"""
    return [r["user_id"] for r in db.execute(
        "SELECT user_id FROM conv_members WHERE conv_id=?", (cid,)).fetchall()
        if r["user_id"] != exclude]


def _mark_read(db, cid, u, upto=None):
    """把某人在这个会话里的已读水位推到 upto（默认推到最新）。

    未读一律按水位算，不再逐条数 read_at —— 群聊里一条消息有多个读者，
    单条上的 read_at 表达不了「谁读到哪」。read_at 仍然写，一对一的已读回执还靠它。
    """
    if upto is None:
        upto = db.execute("SELECT COALESCE(MAX(id),0) FROM chat_msgs WHERE conv_id=?",
                          (cid,)).fetchone()[0] or 0
    db.execute("UPDATE conv_members SET last_read_id=MAX(last_read_id,?) "
               "WHERE conv_id=? AND user_id=?", (upto, cid, u))
    return upto


def _reply_to(db, me, fid):
    """请求里带的「引用哪条」。必须校验它确实属于这个会话——否则拿别人的消息 id
    也能引用成功，等于给了一个探内容的口子（引用条里会回显原文摘要）。"""
    raw = (request.form.get("reply_to") if request.files
           else (request.get_json(silent=True) or {}).get("reply_to"))
    try:
        rid = int(raw or 0)
    except (TypeError, ValueError):
        return None
    if not rid:
        return None
    ok = db.execute("SELECT 1 FROM chat_msgs WHERE id=? AND ((from_uid=? AND to_uid=?) "
                    "OR (from_uid=? AND to_uid=?))", (rid, me, fid, fid, me)).fetchone()
    return rid if ok else None


# 能发进聊天的应用内容（丙）。key → (显示名, 前端打开它的函数)
# 这是这个聊天区别于微信的地方：发过去的不是一段文字，是应用里那一条，点开直达。
CARD_KINDS = {
    "wrongq": ("错题", "openWrongq"),
    "classic": ("古诗文", "openClassics"),
    "sucai": ("素材", "openSucai"),
    "note": ("小记", "openNotes"),
    "entry": ("收录的词", "openIdiom"),
}


def _card_of(r):
    """把 kind='card' 那行的 body 解回卡片对象；解不出来就当普通文本。"""
    if r["kind"] != "card":
        return None
    try:
        c = json.loads(r["body"] or "{}")
    except Exception:
        return None
    return c if isinstance(c, dict) and c.get("kind") in CARD_KINDS else None


def _preview(r):
    """会话列表里那一行摘要。"""
    if not r:
        return ""
    if r["recalled_at"]:
        return "[已撤回]"
    if r["kind"] == "card":
        c = _card_of(r) or {}
        return ("[%s] %s" % (CARD_KINDS.get(c.get("kind"), ("内容",))[0], c.get("title") or ""))[:30]
    if r["kind"] in ("text", "ai"):
        return (("AI 助手：" if r["kind"] == "ai" else "") + (r["body"] or ""))[:30]
    if r["kind"] == "voice":
        v = _voice_of(r)
        # 转过文字的就把文字摆出来：列表上「[语音]」一行连着好几条，谁说了什么全看不出来
        return ("[语音] " + (v["text"] or "%d″" % round(v["dur"])))[:30]
    return ("[图片]" if r["kind"] == "image" else "[文件] " + (r["file_name"] or ""))[:30]


def _msg_out(r, me, quoted=None):
    """一条消息发给前端的样子。撤回的只留个壳（正文和文件都不给）。"""
    if r["recalled_at"]:
        return {"id": r["id"], "mine": r["from_uid"] == me, "kind": "recalled",
                "body": "", "time": r["created_at"], "recalled": True}
    m = {"id": r["id"], "mine": r["from_uid"] == me, "kind": r["kind"],
         "body": r["body"] or "", "file_id": r["file_id"], "file_name": r["file_name"],
         "file_size": r["file_size"], "time": r["created_at"], "read": bool(r["read_at"])}
    if r["kind"] == "voice":
        v = _voice_of(r)
        m["dur"], m["text"], m["body"] = v["dur"], v["text"], ""
    if r["kind"] == "card":
        m["card"] = _card_of(r)
        if not m["card"]:                 # 解不出来的老数据/脏数据，退化成文本，别让气泡空着
            m["kind"] = "text"
    if quoted:
        m["quote"] = quoted
    return m


def _quote_of(db, r, me):
    """这条消息引用了谁的哪句话（给前端画引用条）。原消息被撤回/删了就说明一下。"""
    if not r["reply_to"]:
        return None
    q = db.execute("SELECT * FROM chat_msgs WHERE id=?", (r["reply_to"],)).fetchone()
    if not q:
        return {"id": r["reply_to"], "who": "", "text": "原消息已删除"}
    who = "我" if q["from_uid"] == me else uname(db, q["from_uid"])
    if q["recalled_at"]:
        return {"id": q["id"], "who": who, "text": "原消息已撤回"}
    # 走 _preview：文本 / 图片 / 文件 / 内容卡片的摘要口径只该有一份。
    # 原先这里自己写了一遍 if-else，加了卡片类型之后它就落进「[文件] 」那个分支了。
    return {"id": q["id"], "who": who, "text": _preview(q)}


@bp.get("/api/chat/g/<int:cid>/checkin")
def group_checkin_get(cid):
    return jsonify(_checkin_state(cid))


@bp.post("/api/chat/g/<int:cid>/checkin")
def group_checkin_do(cid):
    """今天打个卡。一人一天一条（主键去重），重复点不会多算。"""
    db, me = get_db(), uid()
    if not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    db.execute("INSERT OR IGNORE INTO chat_checkins(conv_id,user_id,day) "
               "VALUES(?,?,date('now','localtime'))", (cid, me))
    db.commit()
    return jsonify(_checkin_state(cid))


def _checkin_state(cid):
    """今天这个组谁打过卡。给会话顶部那张条用（CM2）。"""
    db, me = get_db(), uid()
    if not _is_member(db, cid, me):
        return {"total": 0, "done": [], "me": False}
    rows = db.execute(
        "SELECT u.id, u.username, u.avatar,"
        " EXISTS(SELECT 1 FROM chat_checkins k WHERE k.conv_id=? AND k.user_id=u.id"
        "        AND k.day=date('now','localtime')) done"
        " FROM conv_members m JOIN users u ON u.id=m.user_id WHERE m.conv_id=? ORDER BY m.joined_at",
        (cid, cid)).fetchall()
    return {"total": len(rows),
            "done": [{"id": r["id"], "username": r["username"],
                      "avatar": ("/skin/%d/%s" % (r["id"], r["avatar"])) if r["avatar"] else "",
                      "done": bool(r["done"])} for r in rows],
            "me": any(r["done"] and r["id"] == me for r in rows)}


@bp.get("/api/chat/info")
def chat_info():
    """一对一会话的信息页：传过的文件、发过的图、我的置顶/免打扰。

    小组那份在 /api/chat/groups/<id> 里（那边还要带成员和公告）。分成两条是因为
    小组多了成员/群主/公告这一整块，硬塞进同一个响应里两边都得写一堆 if。"""
    try:
        fid = int(request.args.get("id") or 0)
    except ValueError:
        fid = 0
    if not fid:
        return jsonify({"error": "缺少会话"}), 400
    db, me = get_db(), uid()
    cid = _direct_conv(db, me, fid, create=False)
    return jsonify({"files": _conv_files(db, cid) if cid else [],
                    "images": _conv_images(db, cid) if cid else [],
                    "prefs": _conv_prefs(db, me, "u", fid)})


@bp.patch("/api/chat/prefs")
def chat_prefs_set():
    """置顶 / 免打扰。body: {kind:'u'|'g', id, pinned?, muted?}。

    只写传进来的那个字段 —— 前端两个开关是分开点的，整行覆盖会把另一个悄悄清掉。"""
    d = request.get_json(silent=True) or {}
    kind = "g" if d.get("kind") == "g" else "u"
    try:
        peer = int(d.get("id") or 0)
    except (TypeError, ValueError):
        peer = 0
    if not peer:
        return jsonify({"error": "缺少会话"}), 400
    db, me = get_db(), uid()
    db.execute("INSERT OR IGNORE INTO chat_prefs(user_id,kind,peer) VALUES(?,?,?)", (me, kind, peer))
    for col in ("pinned", "muted"):
        if col in d:
            db.execute("UPDATE chat_prefs SET %s=? WHERE user_id=? AND kind=? AND peer=?" % col,
                       (1 if d.get(col) else 0, me, kind, peer))
    db.commit()
    r = db.execute("SELECT pinned,muted FROM chat_prefs WHERE user_id=? AND kind=? AND peer=?",
                   (me, kind, peer)).fetchone()
    return jsonify({"pinned": bool(r["pinned"]), "muted": bool(r["muted"])})


@bp.get("/api/chat/conversations")
def chat_convos():
    """会话列表。

    原先是「按好友数放大」的循环：每个好友 4 次查询（最后一条 / 未读数 / 用户名 / 头像），
    20 个好友就是 80 次往返，而这个列表在进聊天页、每次收到推送、每次切页签时都会重拉。
    改成两条：一条把每人的 last_id + 未读数 + 用户名头像一次带回（相关子查询在 SQLite
    内部跑，不再有 Python 侧的来回），再一条按 id 批量取那几条消息的正文做摘要。
    """
    db = get_db()
    me = uid()
    rows = db.execute(
        "SELECT f.friend_id fid, u.username, u.avatar,"
        " (SELECT MAX(m.id) FROM chat_msgs m WHERE (m.from_uid=? AND m.to_uid=f.friend_id)"
        "   OR (m.from_uid=f.friend_id AND m.to_uid=?)) last_id,"
        " (SELECT COUNT(*) FROM chat_msgs m WHERE m.from_uid=f.friend_id AND m.to_uid=?"
        "   AND m.read_at IS NULL) unread"
        " FROM friends f JOIN users u ON u.id=f.friend_id WHERE f.user_id=?",
        (me, me, me, me)).fetchall()
    # 文件传输助手（和自己的会话，跨设备传文件/暂存）
    self_last = db.execute("SELECT MAX(id) FROM chat_msgs WHERE from_uid=? AND to_uid=?",
                           (me, me)).fetchone()[0] or 0
    ids = [r["last_id"] for r in rows if r["last_id"]] + ([self_last] if self_last else [])
    last = {}
    if ids:
        q = "SELECT * FROM chat_msgs WHERE id IN (%s)" % ",".join("?" * len(ids))
        last = {m["id"]: m for m in db.execute(q, ids).fetchall()}
    convos, total_unread = [], 0
    for r in rows:
        m = last.get(r["last_id"])
        total_unread += r["unread"]
        convos.append({"id": r["fid"], "username": r["username"],
                       "avatar": ("/skin/%d/%s" % (r["fid"], r["avatar"])) if r["avatar"] else "",
                       "preview": _preview(m), "time": (m["created_at"] if m else ""),
                       "unread": r["unread"], "last_id": r["last_id"] or 0,
                       # 最后一条是自己发的时候，列表里也显示送达/已读（✓ / ✓✓）
                       "last_mine": bool(m and m["from_uid"] == me),
                       "last_read": bool(m and m["from_uid"] == me and m["read_at"])})
    # 小组：未读按水位算（群里一条消息有多个读者，单条上的 read_at 表达不了「谁读到哪」）
    groups = db.execute(
        "SELECT c.id, c.title, mm.last_read_id,"
        " (SELECT MAX(id) FROM chat_msgs x WHERE x.conv_id=c.id) last_id,"
        " (SELECT COUNT(*) FROM chat_msgs x WHERE x.conv_id=c.id AND x.id>mm.last_read_id"
        "   AND x.from_uid<>?) unread,"
        " (SELECT COUNT(*) FROM conv_members y WHERE y.conv_id=c.id) n_mem"
        " FROM conversations c JOIN conv_members mm ON mm.conv_id=c.id AND mm.user_id=?"
        " WHERE c.kind='group'", (me, me)).fetchall()
    gids = [g["last_id"] for g in groups if g["last_id"]]
    glast = {}
    if gids:
        q = "SELECT * FROM chat_msgs WHERE id IN (%s)" % ",".join("?" * len(gids))
        glast = {m["id"]: m for m in db.execute(q, gids).fetchall()}
    for g in groups:
        m = glast.get(g["last_id"])
        who = (uname(db, m["from_uid"]) + "：") if m and m["from_uid"] != me else ("我：" if m else "")
        total_unread += g["unread"]
        # 被 @ 的会话在列表里前置一个标记 —— 小组消息一多，光靠数字角标会淹掉
        at = bool(db.execute("SELECT 1 FROM notifications WHERE user_id=? AND dkey LIKE ? AND kind='chat'",
                             (me, "chatg:%d:%%:at" % g["id"])).fetchone())
        convos.append({"id": g["id"], "group": True, "username": g["title"],
                       "avatar": "", "preview": (who + _preview(m)) if m else "还没有人说话",
                       "time": (m["created_at"] if m else ""), "unread": g["unread"],
                       "last_id": g["last_id"] or 0, "last_mine": False, "last_read": False,
                       "n_mem": g["n_mem"], "at": at})
    # 置顶 / 免打扰：一次把这个人的偏好全取回来，按 (kind,peer) 贴到每一行上
    prefs = {(r["kind"], r["peer"]): r for r in
             db.execute("SELECT kind,peer,pinned,muted FROM chat_prefs WHERE user_id=?", (me,)).fetchall()}
    for c in convos:
        p = prefs.get(("g" if c.get("group") else "u", c["id"]))
        c["pinned"] = bool(p and p["pinned"])
        c["muted"] = bool(p and p["muted"])
    # 置顶的排最前，其余按最后一条消息的时间倒序
    convos.sort(key=lambda c: (0 if c["pinned"] else 1, -(c["last_id"])))
    sm = last.get(self_last)
    convos.insert(0, {"id": me, "username": "文件传输助手", "avatar": "", "self": True,
                      "preview": _preview(sm), "time": (sm["created_at"] if sm else ""),
                      "unread": 0, "last_id": self_last, "last_mine": False, "last_read": False})
    return jsonify({"conversations": convos, "unread": total_unread})


CHAT_PAGE = 50          # 首屏 / 每次向上翻页的条数
CHAT_MAX = 4000         # 单条文本上限（前端同步显示字数，见 chat.js CHAT_MAX）


@bp.get("/api/chat/<int:fid>")
def chat_history(fid):
    """取消息。三种用法，靠参数区分：

        （不带参数）  首屏：最近 CHAT_PAGE 条
        ?before=<id>  向上翻页：比这条更早的 CHAT_PAGE 条
        ?after=<id>   增量拉新：SSE 推送和兜底轮询走这条

    首屏原先是 `id>0 ORDER BY id LIMIT 200` —— 那是从**最老**的一条开始截 200 条，
    聊过几百条的会话进去看到的是几个月前的对话，最近说了什么反而要等兜底轮询一批批补。
    """
    db = get_db()
    me = uid()
    if fid != me and not _are_friends(db, me, fid):   # fid==me = 文件传输助手
        return jsonify({"error": "不是好友"}), 403
    where = "((from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?))"
    pair = (me, fid, fid, me)
    after = int(request.args.get("after") or 0)
    before = int(request.args.get("before") or 0)
    has_more = False
    if after:
        rows = db.execute("SELECT * FROM chat_msgs WHERE %s AND id>? ORDER BY id LIMIT 200" % where,
                          pair + (after,)).fetchall()
    else:
        # 倒着取 PAGE+1 条：多要的那一条只用来判断「上面还有没有」，不返给前端
        rows = db.execute(
            "SELECT * FROM chat_msgs WHERE %s%s ORDER BY id DESC LIMIT ?"
            % (where, " AND id<?" if before else ""),
            pair + ((before,) if before else ()) + (CHAT_PAGE + 1,)).fetchall()
        has_more = len(rows) > CHAT_PAGE
        rows = list(reversed(rows[:CHAT_PAGE]))
    out = [_msg_out(r, me, _quote_of(db, r, me)) for r in rows]
    # 撤回是**就地改状态**，增量拉取（after=最大 id）看不到它 —— 单给一份「这一屏之内
    # 刚刚被撤回的」，前端据此把已经画出来的气泡换成「已撤回」。
    recalled = [x[0] for x in db.execute(
        "SELECT id FROM chat_msgs WHERE %s AND recalled_at IS NOT NULL "
        "AND recalled_at > datetime('now','localtime','-1 day')" % where, pair).fetchall()]
    # 对方读到哪了：前端据此把已经画出来的自己那些气泡从「✓ 已送达」翻成「✓✓ 已读」。
    # 增量拉取只会带回**新**消息，老气泡的已读状态不会再随消息回来，所以单给一个水位。
    read_upto = db.execute("SELECT MAX(id) FROM chat_msgs WHERE from_uid=? AND to_uid=? "
                           "AND read_at IS NOT NULL", (me, fid)).fetchone()[0] or 0
    if not before:      # 翻看更早的历史不该顺手把新消息标成已读
        db.execute("UPDATE chat_msgs SET read_at=datetime('now','localtime') "
                   "WHERE from_uid=? AND to_uid=? AND read_at IS NULL", (fid, me))
        # 水位跟着一起推：一对一的未读现在也由它兜底（群聊只有它）
        conv = _direct_conv(db, me, fid, create=False)
        if conv:
            _mark_read(db, conv, me)
        # 读了这个会话 → 清掉它在消息中心/通知栏里堆积的那几条 chat 通知
        db.execute("DELETE FROM notifications WHERE user_id=? AND kind='chat' AND link=?",
                   (me, "chatroom:%d" % fid))
        db.commit()
    fname = "文件传输助手" if fid == me else uname(db, fid)
    return jsonify({"messages": out, "me": me, "friend": fname, "has_more": has_more,
                    "read_upto": read_upto, "recalled": recalled,
                    "friend_avatar": _uavatar(db, fid), "me_avatar": _uavatar(db, me)})


# ---- 小组（群聊）----
@bp.post("/api/chat/groups")
def group_new():
    """建一个学习小组。只能拉自己的好友进来。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:40]
    if not name:
        return jsonify({"error": "请给小组起个名字"}), 400
    db, me = get_db(), uid()
    ids = [int(x) for x in (data.get("members") or []) if str(x).isdigit()][:50]
    ids = [x for x in ids if x != me and _are_friends(db, me, x)]
    cid = db.execute("INSERT INTO conversations(kind,title,owner_id) VALUES('group',?,?)",
                     (name, me)).lastrowid
    for u in [me] + ids:
        db.execute("INSERT OR IGNORE INTO conv_members(conv_id,user_id) VALUES(?,?)", (cid, u))
    db.commit()
    for u in ids:
        _notify_chat(u, {"type": "friend"})        # 让对方的列表刷出这个新小组
    return jsonify({"id": cid, "name": name, "members": len(ids) + 1}), 201


def _conv_prefs(db, me, kind, peer):
    r = db.execute("SELECT pinned,muted FROM chat_prefs WHERE user_id=? AND kind=? AND peer=?",
                   (me, kind, peer)).fetchone()
    return {"pinned": bool(r and r["pinned"]), "muted": bool(r and r["muted"])}


def _conv_files(db, cid, limit=20):
    """这个会话里传过的文件（图片单独走 _conv_images，不混在一张列表里）。"""
    rows = db.execute(
        "SELECT m.id, m.file_name, m.file_size, m.created_at, u.username FROM chat_msgs m "
        "LEFT JOIN users u ON u.id=m.from_uid "
        "WHERE m.conv_id=? AND m.kind='file' AND m.recalled_at IS NULL "
        "ORDER BY m.id DESC LIMIT ?", (cid, limit)).fetchall()
    return [{"id": r["id"], "name": r["file_name"] or "", "size": r["file_size"] or 0,
             "who": r["username"] or "", "time": r["created_at"]} for r in rows]


def _conv_images(db, cid, limit=24):
    rows = db.execute(
        "SELECT id FROM chat_msgs WHERE conv_id=? AND kind='image' AND recalled_at IS NULL "
        "ORDER BY id DESC LIMIT ?", (cid, limit)).fetchall()
    return [{"id": r["id"], "url": "/api/chat/file/%d" % r["id"]} for r in rows]


@bp.get("/api/chat/groups/<int:cid>")
def group_info(cid):
    db, me = get_db(), uid()
    c = db.execute("SELECT * FROM conversations WHERE id=? AND kind='group'", (cid,)).fetchone()
    if not c or not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    rows = db.execute("SELECT m.user_id, u.username, u.avatar FROM conv_members m "
                      "JOIN users u ON u.id=m.user_id WHERE m.conv_id=? ORDER BY m.joined_at",
                      (cid,)).fetchall()
    return jsonify({
        "id": c["id"], "name": c["title"], "announce": c["announce"] or "",
        "owner_id": c["owner_id"], "is_owner": c["owner_id"] == me,
        "members": [{"id": r["user_id"], "username": r["username"],
                     "avatar": ("/skin/%d/%s" % (r["user_id"], r["avatar"])) if r["avatar"] else "",
                     "owner": r["user_id"] == c["owner_id"]} for r in rows],
        # 信息栏要的三样：传过的文件、发过的图、我自己的置顶/免打扰。
        # 一次给全，省得点开信息栏还要再打三个接口。
        "files": _conv_files(db, cid), "images": _conv_images(db, cid),
        "prefs": _conv_prefs(db, me, "g", cid)})


@bp.patch("/api/chat/groups/<int:cid>")
def group_patch(cid):
    """改群名 / 群公告（群主）。"""
    data = request.get_json(silent=True) or {}
    db, me = get_db(), uid()
    c = db.execute("SELECT * FROM conversations WHERE id=? AND kind='group'", (cid,)).fetchone()
    if not c:
        return jsonify({"error": "小组不存在"}), 404
    if c["owner_id"] != me:
        return jsonify({"error": "只有群主能改"}), 403
    if "name" in data:
        n = (data.get("name") or "").strip()[:40]
        if n:
            db.execute("UPDATE conversations SET title=? WHERE id=?", (n, cid))
    if "announce" in data:
        db.execute("UPDATE conversations SET announce=? WHERE id=?",
                   ((data.get("announce") or "").strip()[:500], cid))
    db.commit()
    for u in _conv_peers(db, cid, me):
        _notify_chat(u, {"type": "friend"})
    return jsonify({"ok": True})


@bp.post("/api/chat/groups/<int:cid>/members")
def group_invite(cid):
    db, me = get_db(), uid()
    if not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    ids = [int(x) for x in ((request.get_json(silent=True) or {}).get("members") or [])
           if str(x).isdigit()][:50]
    added = []
    for u in ids:
        if u != me and _are_friends(db, me, u) and not _is_member(db, cid, u):
            db.execute("INSERT OR IGNORE INTO conv_members(conv_id,user_id) VALUES(?,?)", (cid, u))
            added.append(u)
    db.commit()
    for u in added:
        _notify_chat(u, {"type": "friend"})
    return jsonify({"ok": True, "added": len(added)})


@bp.delete("/api/chat/groups/<int:cid>/members/<int:target>")
def group_kick(cid, target):
    """退出小组（target=自己），或群主移除某人。群主退出＝解散。"""
    db, me = get_db(), uid()
    c = db.execute("SELECT * FROM conversations WHERE id=? AND kind='group'", (cid,)).fetchone()
    if not c or not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    if target != me and c["owner_id"] != me:
        return jsonify({"error": "只有群主能移除成员"}), 403
    if target == me and c["owner_id"] == me:
        # 群主走人就解散：留一个没人管的组，别人也退不出、改不了
        db.execute("DELETE FROM conv_members WHERE conv_id=?", (cid,))
        db.execute("DELETE FROM chat_msgs WHERE conv_id=?", (cid,))
        db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        db.commit()
        return jsonify({"ok": True, "dissolved": True})
    db.execute("DELETE FROM conv_members WHERE conv_id=? AND user_id=?", (cid, target))
    db.commit()
    _notify_chat(target, {"type": "friend"})
    return jsonify({"ok": True})


RECALL_WINDOW = 2 * 60      # 撤回时限（秒），跟微信一个量级


@bp.delete("/api/chat/msg/<int:mid>")
def chat_msg_del(mid):
    """撤回或删除一条消息。

        mode=recall  两分钟内撤回自己发的，两边都看不见（对方那侧靠 recalled 列表同步）
        mode=delete  只在自己这侧删掉（对方留着）——目前先当撤回的兜底，前端只用 recall
    """
    db = get_db()
    me = uid()
    r = db.execute("SELECT * FROM chat_msgs WHERE id=?", (mid,)).fetchone()
    # 群消息的 to_uid 是 0，得按「我在不在这个会话里」判
    inside = r and (me in (r["from_uid"], r["to_uid"])
                    or (r["conv_id"] and _is_member(db, r["conv_id"], me)))
    if not inside:
        return jsonify({"error": "消息不存在"}), 404
    if r["recalled_at"]:
        return jsonify({"ok": True})            # 已经撤过了，当成功（重复点不该报错）
    if r["from_uid"] != me:
        return jsonify({"error": "只能撤回自己发的消息"}), 403
    age = db.execute("SELECT (julianday('now','localtime')-julianday(?))*86400",
                     (r["created_at"],)).fetchone()[0] or 0
    if age > RECALL_WINDOW:
        return jsonify({"error": "超过 2 分钟就不能撤回了"}), 400
    db.execute("UPDATE chat_msgs SET recalled_at=datetime('now','localtime') WHERE id=?", (mid,))
    # 顺带撤掉它在别人消息中心里的那条通知，别点进去发现是空的
    if r["to_uid"]:
        db.execute("DELETE FROM notifications WHERE user_id=? AND dkey=?",
                   (r["to_uid"], "chat:%d:%d" % (me, mid)))
        targets = [r["to_uid"]]
    else:
        db.execute("DELETE FROM notifications WHERE dkey LIKE ?", ("chatg:%d:%d%%" % (r["conv_id"], mid),))
        targets = _conv_peers(db, r["conv_id"], me)
    db.commit()
    for t in targets:
        _notify_chat(t, {"type": "msg", "from": me, "group": r["conv_id"] if not r["to_uid"] else 0,
                         "name": uname(db, me), "preview": "[已撤回]", "silent": True})
    # 撤回的是文本 → 把原文给回前端，好让「重新编辑」把它塞回输入框
    return jsonify({"ok": True, "body": r["body"] if r["kind"] == "text" else ""})


@bp.post("/api/chat/msg/<int:mid>/voicetext")
def chat_voice_text(mid):
    """把一条语音转成文字。

    转写结果写回这条消息（body 里那个 text），所以**一条语音全会话只转一次**：
    别人再点、自己换台设备再点，拿到的都是同一份，不会又去调一次识别接口。
    识别引擎默认是关的，这条就只回 503——语音条本身照常能听。
    """
    from mods.asr import asr_configured, transcribe

    db, me = get_db(), uid()
    r = db.execute("SELECT * FROM chat_msgs WHERE id=?", (mid,)).fetchone()
    inside = r and (me in (r["from_uid"], r["to_uid"])
                    or (r["conv_id"] and _is_member(db, r["conv_id"], me)))
    if not inside or r["recalled_at"]:
        return jsonify({"error": "消息不存在"}), 404
    if r["kind"] != "voice":
        return jsonify({"error": "这条不是语音"}), 400
    v = _voice_of(r)
    if v["text"]:
        return jsonify({"text": v["text"], "cached": True})
    if not asr_configured():
        return jsonify({"error": "语音转文字还没开启（管理员可在后台 → 语音识别 里配置）"}), 503
    fr = db.execute("SELECT owner_id, stored_name FROM drive_files WHERE id=?",
                    (r["file_id"],)).fetchone()
    path = os.path.join(_drive_dir(fr["owner_id"]), fr["stored_name"]) if fr else ""
    if not path or not os.path.exists(path):
        return jsonify({"error": "这段录音的文件已经不在了"}), 404
    try:
        txt = transcribe(path)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception:
        log.exception("聊天语音转文字失败 mid=%s", mid)
        return jsonify({"error": "识别失败了，稍后再试"}), 502
    db.execute("UPDATE chat_msgs SET body=? WHERE id=?", (_voice_body(v["dur"], txt), mid))
    db.commit()
    return jsonify({"text": txt})


@bp.get("/api/chat/g/<int:cid>")
def group_history(cid):
    """群消息。分页口径和一对一那条完全一样，只是按 conv_id 取。"""
    db, me = get_db(), uid()
    if not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    after = int(request.args.get("after") or 0)
    before = int(request.args.get("before") or 0)
    has_more = False
    if after:
        rows = db.execute("SELECT * FROM chat_msgs WHERE conv_id=? AND id>? ORDER BY id LIMIT 200",
                          (cid, after)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM chat_msgs WHERE conv_id=?%s ORDER BY id DESC LIMIT ?"
            % (" AND id<?" if before else ""),
            ((cid, before, CHAT_PAGE + 1) if before else (cid, CHAT_PAGE + 1))).fetchall()
        has_more = len(rows) > CHAT_PAGE
        rows = list(reversed(rows[:CHAT_PAGE]))
    names = {r["user_id"]: r["username"] for r in db.execute(
        "SELECT m.user_id, u.username FROM conv_members m JOIN users u ON u.id=m.user_id "
        "WHERE m.conv_id=?", (cid,)).fetchall()}
    out = []
    for r in rows:
        m = _msg_out(r, me, _quote_of(db, r, me))
        m["who"] = names.get(r["from_uid"], "")     # 群里要显示是谁说的
        m["from"] = r["from_uid"]
        out.append(m)
    recalled = [x[0] for x in db.execute(
        "SELECT id FROM chat_msgs WHERE conv_id=? AND recalled_at IS NOT NULL "
        "AND recalled_at > datetime('now','localtime','-1 day')", (cid,)).fetchall()]
    if not before:
        _mark_read(db, cid, me)
        db.execute("DELETE FROM notifications WHERE user_id=? AND kind='chat' AND link=?",
                   (me, "chatgroup:%d" % cid))
        db.commit()
    c = db.execute("SELECT title, announce FROM conversations WHERE id=?", (cid,)).fetchone()
    return jsonify({"messages": out, "me": me, "has_more": has_more, "recalled": recalled,
                    "name": c["title"] if c else "", "announce": (c["announce"] if c else "") or "",
                    "members": [{"id": k, "username": v} for k, v in names.items()]})


@bp.post("/api/chat/g/<int:cid>")
def group_send(cid):
    """往小组发消息。文本 / 文件 / 内容卡片，跟一对一同一套。"""
    db, me = get_db(), uid()
    if not _is_member(db, cid, me):
        return jsonify({"error": "不在这个小组里"}), 403
    myname = uname(db, me)
    gname = (db.execute("SELECT title FROM conversations WHERE id=?", (cid,)).fetchone() or
             {"title": "小组"})["title"]
    peers = _conv_peers(db, cid, me)

    def _after(mid, prev):
        """落库之后统一做的三件事：推给别人、写消息中心、把自己的水位推上去。"""
        for u in peers:
            _chat_center_notify_group(db, u, cid, gname, "%s：%s" % (myname, prev), mid)
        _mark_read(db, cid, me, mid)
        db.commit()
        for u in peers:
            _notify_chat(u, {"type": "msg", "group": cid, "name": gname,
                             "preview": "%s：%s" % (myname, prev[:50])})
        row = db.execute("SELECT created_at FROM chat_msgs WHERE id=?", (mid,)).fetchone()
        return jsonify({"ok": True, "id": mid, "time": row["created_at"] if row else ""})

    if request.files.get("file"):
        f = request.files["file"]
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > DRIVE_MAX:
            return jsonify({"error": "文件超过 %d MB" % (DRIVE_MAX // (1024 * 1024))}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        tmp = os.path.join(_drive_dir(me), "tmp-" + uuid.uuid4().hex + ext)
        f.save(tmp)
        digest = _sha256_file(tmp)
        dup = _dedup_stored(db, me, digest)
        if dup:
            os.remove(tmp)
            stored = dup
        else:
            stored = uuid.uuid4().hex + ext
            os.replace(tmp, os.path.join(_drive_dir(me), stored))
        db.execute("INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source,sha256) "
                   "VALUES(?,?,?,?,?,?,?,0,'chat',?)",
                   (me, "聊天文件", f.filename, stored, ext, f.mimetype or "", size, digest))
        dur = None
        if request.form.get("voice") == "1":
            dur, verr = _voice_meta(f, os.path.join(_drive_dir(me), stored))
            if verr:
                return jsonify({"error": verr}), 400
        kind = ("voice" if dur is not None else
                "image" if (f.mimetype or "").startswith("image/") else "file")
        # 群文件不给每个人各复制一份（人一多就是几十份盘）：消息引用发送方那一份，
        # chat_file 的鉴权已经是「你是这条消息所在会话的成员就放行」
        fid_row = db.execute("SELECT id FROM drive_files WHERE owner_id=? AND stored_name=? "
                             "ORDER BY id DESC LIMIT 1", (me, stored)).fetchone()
        mid = db.execute(
            "INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,file_id,file_name,file_size,"
            "file_mime,reply_to) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (me, 0, cid, kind, _voice_body(dur) if dur is not None else None,
             fid_row["id"], f.filename, size, f.mimetype or "",
             _reply_to_conv(db, cid))).lastrowid
        return _after(mid, "[语音]" if kind == "voice" else
                      "[图片]" if kind == "image" else "[文件] " + (f.filename or ""))

    data = request.get_json(silent=True) or {}
    card = data.get("card")
    if isinstance(card, dict) and card.get("kind") in CARD_KINDS:
        payload = {"kind": card["kind"], "id": int(card.get("id") or 0),
                   "title": str(card.get("title") or "")[:120], "sub": str(card.get("sub") or "")[:60]}
        mid = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,reply_to) "
                         "VALUES(?,?,?,'card',?,?)",
                         (me, 0, cid, json.dumps(payload, ensure_ascii=False),
                          _reply_to_conv(db, cid))).lastrowid
        return _after(mid, "[%s] %s" % (CARD_KINDS[card["kind"]][0], payload["title"]))

    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "空消息"}), 400
    if len(body) > CHAT_MAX:
        return jsonify({"error": "消息太长了（%d / %d 字），分两条发吧" % (len(body), CHAT_MAX)}), 400
    mid = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,reply_to) "
                     "VALUES(?,?,?,'text',?,?)",
                     (me, 0, cid, body, _reply_to_conv(db, cid))).lastrowid
    # @提及：被点名的人单独给一条通知，别让他在几十条里自己找
    for u in _mentioned(db, cid, body, me):
        _chat_center_notify_group(db, u, cid, gname, "%s 在小组里 @ 了你" % myname, mid, at=True)
    resp = _after(mid, body[:60])
    # @助手：AI 在群里当场回一条，全组都看得见（不是把人支到助手面板去私聊）
    if _asks_bot(body):
        _bot_reply_async(cid, me, myname, gname, body, peers)
    return resp


BOT_AT_RE = re.compile(r"@\s*(助手|小助手|AI\s*助手|AI|ai)(?![\w\u4e00-\u9fa5])")
BOT_SYS = (
    "你是这个备考学习小组里的 AI 助手，被 @ 到才说话。规矩："
    "①直接给答案和理由，别客套、别复述问题；"
    "②控制在 200 字以内，能一句说清就一句；"
    "③公考相关（行测、申论、常识、时政）答到点子上，拿不准就直说拿不准，不要编；"
    "④这是群聊，你看不到任何人的私人数据（错题本、收录、进度），别假装看得到。"
)
BOT_CTX_N = 8            # 带上最近几条当上下文：群里问「这个怎么算」全靠上文
_BOT_BUSY = set()        # 正在回答的会话，一个群同时只跑一条，别被连问几句刷爆
_BOT_LOCK = threading.Lock()


def _asks_bot(body):
    """这条消息是不是在叫 AI 助手。

    后面必须跟非字母非汉字（或结尾），否则「@AIleen」「@助手长」这种也会被当成叫它。"""
    return bool(BOT_AT_RE.search(body or ""))


def _bot_reply_async(cid, asker_id, asker_name, gname, question, peers):
    """AI 在群里答一条。

    为什么开线程：模型要几秒到十几秒，而发消息这个请求必须立刻返回 ——
    不然提问的人要等 AI 想完，自己那句话才出现在屏幕上。
    线程里不能用 g 上那条连接（请求结束就关了），自己开一条、用完自己关。

    答案落库成 kind='ai'、from_uid=0：不借用任何人的身份，所以谁看都不是「自己发的」，
    也就不会在提问人那侧渲染成右边的绿气泡。"""
    with _BOT_LOCK:
        if cid in _BOT_BUSY:
            return                      # 上一条还在答，这条就不排队了（答案马上到）
        _BOT_BUSY.add(cid)

    def run():
        con = None
        try:
            con = open_db()
            rows = con.execute(
                "SELECT m.from_uid, m.kind, m.body, u.username FROM chat_msgs m "
                "LEFT JOIN users u ON u.id=m.from_uid "
                "WHERE m.conv_id=? AND m.kind IN ('text','ai') AND m.recalled_at IS NULL "
                "ORDER BY m.id DESC LIMIT ?", (cid, BOT_CTX_N)).fetchall()
            ctx = "\n".join(
                ("AI 助手：" if r["kind"] == "ai" else ((r["username"] or "某人") + "："))
                + (r["body"] or "")[:200]
                for r in reversed(rows))
            q = BOT_AT_RE.sub("", question).strip() or "（他只 @ 了你，没说别的）"
            msgs = [{"role": "system", "content": BOT_SYS},
                    {"role": "user", "content":
                     "小组「%s」最近的对话：\n%s\n\n%s 刚才 @ 你问：%s" % (gname, ctx, asker_name, q)}]
            try:
                rep = (ai_chat(msgs, tier="fast", temperature=0.4, max_tokens=700) or "").strip()
            except Exception as e:
                # 答不出来也要落一条：群里 @ 了它却什么都不出现，看着像应用坏了
                rep = "（没答上来：%s）" % aiclient.error_message(e)
            if not rep:
                rep = "（这次没生成出内容，再 @ 我一次试试）"
            mid = con.execute(
                "INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body) VALUES(0,0,?,'ai',?)",
                (cid, rep)).lastrowid
            for u in set(list(peers) + [asker_id]):
                con.execute("INSERT OR IGNORE INTO notifications(user_id,kind,dkey,title,body,link) "
                            "VALUES(?,?,?,?,?,?)",
                            (u, "chat", "chatg:%d:%d" % (cid, mid),
                             "小组「%s」AI 助手回了一条" % gname, rep[:80], "chatgroup:%d" % cid))
            con.commit()
            for u in set(list(peers) + [asker_id]):
                _notify_chat(u, {"type": "msg", "group": cid, "name": gname,
                                 "preview": "AI 助手：" + rep[:50]})
        except Exception:
            log.exception("群里 @助手 回复失败（会话 %s）", cid)
        finally:
            if con:
                con.close()
            with _BOT_LOCK:
                _BOT_BUSY.discard(cid)

    threading.Thread(target=run, daemon=True).start()


def _mentioned(db, cid, body, me):
    """这条消息 @ 了组里的谁。按用户名匹配，@所有人 就是全组。"""
    if "@" not in body:
        return []
    rows = db.execute("SELECT m.user_id, u.username FROM conv_members m JOIN users u ON u.id=m.user_id "
                      "WHERE m.conv_id=? AND m.user_id<>?", (cid, me)).fetchall()
    if re.search(r"@(所有人|全体成员|all)", body, re.I):
        return [r["user_id"] for r in rows]
    return [r["user_id"] for r in rows if ("@" + (r["username"] or "")) in body]


def _reply_to_conv(db, cid):
    """群里引用的那条必须属于同一个会话。"""
    raw = (request.form.get("reply_to") if request.files
           else (request.get_json(silent=True) or {}).get("reply_to"))
    try:
        rid = int(raw or 0)
    except (TypeError, ValueError):
        return None
    if not rid:
        return None
    ok = db.execute("SELECT 1 FROM chat_msgs WHERE id=? AND conv_id=?", (rid, cid)).fetchone()
    return rid if ok else None


def _chat_center_notify_group(db, to_uid, cid, gname, preview, mid, at=False):
    db.execute("INSERT OR IGNORE INTO notifications(user_id,kind,dkey,title,body,link) VALUES(?,?,?,?,?,?)",
               (to_uid, "chat", "chatg:%d:%d%s" % (cid, mid, ":at" if at else ""),
                ("有人在「%s」@ 你" % gname) if at else ("小组「%s」有新消息" % gname),
                (preview or "")[:80], "chatgroup:%d" % cid))


@bp.get("/api/chat/search")
def chat_search():
    """搜聊天记录：会话内（带 with）或全局。消息 + 文件名一起搜。

    走 LIKE 不走 FTS5：见 schema.py 里那段注释（中文分词）。
    """
    db = get_db()
    me = uid()
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"results": []})
    kw = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
    # 「我能看见的消息」= 一对一里我是收发方的 + 我所在小组里的
    mine = ("(from_uid=? OR to_uid=? OR conv_id IN "
            "(SELECT conv_id FROM conv_members WHERE user_id=?))")
    args = [me, me, me]
    scope = ""
    with_id = int(request.args.get("with") or 0)
    gid = int(request.args.get("group") or 0)
    if gid:
        scope = " AND conv_id=?"
        args.append(gid)
    elif with_id:
        scope = " AND ((from_uid=? AND to_uid=?) OR (from_uid=? AND to_uid=?))"
        args += [me, with_id, with_id, me]
    rows = db.execute(
        "SELECT * FROM chat_msgs WHERE %s%s AND recalled_at IS NULL "
        "AND (body LIKE ? ESCAPE '\\' OR file_name LIKE ? ESCAPE '\\') "
        "ORDER BY id DESC LIMIT 60" % (mine, scope), args + [kw, kw]).fetchall()
    gnames = {r["id"]: r["title"] for r in db.execute(
        "SELECT c.id, c.title FROM conversations c JOIN conv_members m ON m.conv_id=c.id "
        "WHERE m.user_id=? AND c.kind='group'", (me,)).fetchall()}
    out = []
    for r in rows:
        if not r["to_uid"] and r["conv_id"] in gnames:      # 群消息
            item = {"id": r["id"], "peer": r["conv_id"], "group": True,
                    "peer_name": gnames[r["conv_id"]]}
        else:
            peer = r["to_uid"] if r["from_uid"] == me else r["from_uid"]
            item = {"id": r["id"], "peer": peer, "group": False,
                    "peer_name": "文件传输助手" if peer == me else uname(db, peer)}
        item.update({"kind": r["kind"], "time": r["created_at"],
                     # 语音的 body 是 JSON，直接摆出来是一串 {"dur":…}；转过文字就搜得到、
                     # 也显示那段文字，没转过的只给个占位
                     "text": (r["body"] or "") if r["kind"] == "text" else
                             (_voice_of(r)["text"] or "[语音]") if r["kind"] == "voice" else
                             (r["file_name"] or ""),
                     "file": r["kind"] not in ("text", "card")})
        out.append(item)
    return jsonify({"results": out, "q": q})


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
        # 先落成临时名：要先算出 sha256 才知道自己云盘里是不是已经有这份内容了
        tmp = os.path.join(_drive_dir(me), "tmp-" + uuid.uuid4().hex + ext)
        f.save(tmp)
        digest = _sha256_file(tmp)
        dup = _dedup_stored(db, me, digest)
        if dup:
            os.remove(tmp)
            stored = dup
        else:
            stored = uuid.uuid4().hex + ext
            os.replace(tmp, os.path.join(_drive_dir(me), stored))
        # 发送方也留一份在自己云盘「聊天文件」，并作为源
        db.execute("INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source,sha256) "
                   "VALUES(?,?,?,?,?,?,?,0,'chat',?)",
                   (me, "聊天文件", f.filename, stored, ext, f.mimetype or "", size, digest))
        # 语音条也是一条文件消息（音频照样进云盘「聊天文件」，想存想转发都还在），
        # 只是多带一个时长、在气泡里画成可播放的一条
        dur = None
        if request.form.get("voice") == "1":
            dur, verr = _voice_meta(f, os.path.join(_drive_dir(me), stored))
            if verr:
                return jsonify({"error": verr}), 400
        mid = _chat_send_file(db, me, fid, f.filename, stored, size, f.mimetype or "", _drive_dir(me),
                              digest, _reply_to(db, me, fid), voice=dur)
        prev = "[语音]" if dur is not None else "[文件] " + (f.filename or "")
        myname = uname(db, me)
        if fid != me:                                 # 文件传输助手(自己)不给自己发通知
            _chat_center_notify(db, fid, me, myname, prev, mid or 0)
        db.commit()
        _notify_chat(fid, {"type": "msg", "from": me, "name": myname,
                           "preview": prev})          # 提交后再秒推（跨设备同步）
        return jsonify({"ok": True, "id": mid, "dur": dur})
    data = request.get_json(silent=True) or {}
    # 内容卡片：把应用里的一条（错题 / 古诗文 / 素材 / 小记 / 收录词）发过去，对方点开直达
    card = data.get("card")
    if isinstance(card, dict) and card.get("kind") in CARD_KINDS:
        payload = {"kind": card["kind"], "id": int(card.get("id") or 0),
                   "title": str(card.get("title") or "")[:120],
                   "sub": str(card.get("sub") or "")[:60]}
        cur = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,reply_to) "
                         "VALUES(?,?,?,'card',?,?)",
                         (me, fid, _direct_conv(db, me, fid),
                          json.dumps(payload, ensure_ascii=False), _reply_to(db, me, fid)))
        myname = uname(db, me)
        prev = "[%s] %s" % (CARD_KINDS[card["kind"]][0], payload["title"])
        if fid != me:
            _chat_center_notify(db, fid, me, myname, prev[:80], cur.lastrowid)
        db.commit()
        _notify_chat(fid, {"type": "msg", "from": me, "name": myname, "preview": prev[:60]})
        row = db.execute("SELECT created_at FROM chat_msgs WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify({"ok": True, "id": cur.lastrowid, "time": row["created_at"] if row else ""})
    # 文本消息
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "空消息"}), 400
    # 原先是 body[:4000] 悄悄切一半：粘一篇范文过去，对方收到半篇，两边都不知道。
    # 前端已有字数提示，这里当最后一道闸，超了就明说。
    if len(body) > CHAT_MAX:
        return jsonify({"error": "消息太长了（%d / %d 字），分两条发吧" % (len(body), CHAT_MAX)}), 400
    cur = db.execute("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,body,reply_to) "
                     "VALUES(?,?,?,'text',?,?)",
                     (me, fid, _direct_conv(db, me, fid), body, _reply_to(db, me, fid)))
    myname = uname(db, me)
    if fid != me:
        _chat_center_notify(db, fid, me, myname, body[:80], cur.lastrowid)
    db.commit()
    _notify_chat(fid, {"type": "msg", "from": me, "name": myname,
                       "preview": body[:60]})           # 秒推给对方（自己的其它设备也会同步）
    # 带回 id 和时间：前端的乐观气泡靠它从「发送中」转成真消息，不用等下一次拉取
    row = db.execute("SELECT created_at FROM chat_msgs WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "id": cur.lastrowid, "time": row["created_at"] if row else ""})


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
        # 群文件只存发送方那一份，所以还要认「这条消息在我所在的会话里」
        party = db.execute(
            "SELECT 1 FROM chat_msgs WHERE file_id=? AND (from_uid=? OR to_uid=? "
            "OR conv_id IN (SELECT conv_id FROM conv_members WHERE user_id=?))",
            (fid, me, me, me)).fetchone()
        if not party:
            return "无权访问", 403
    # 缩略图：会话里图一多，直接铺原图就是几 MB 白等。复用云盘那套缩略图生成，
    # 出不来（不是图片 / 没装依赖）就退回原图，不让气泡开天窗。
    if request.args.get("thumb") == "1":
        try:
            tp = _thumb_path(owner, r["stored_name"])
            if not os.path.exists(tp):
                _make_thumb(os.path.join(_drive_dir(owner), r["stored_name"]), tp)
            if os.path.exists(tp):
                return _no_script(send_file(tp, mimetype="image/jpeg"))
        except Exception:
            log.info("聊天图缩略失败，退回原图", exc_info=True)
    inline = request.args.get("inline") == "1"
    resp = send_file(os.path.join(_drive_dir(owner), r["stored_name"]),
                     as_attachment=not inline, download_name=r["name"],
                     mimetype=r["mime"] or "application/octet-stream")
    # 聊天文件是**别人**发过来的，内联打开时更要挡住里面夹带的脚本
    return _no_script(resp) if inline else resp


@bp.get("/api/chat/unread")
def chat_unread():
    db, me = get_db(), uid()
    n = db.execute("SELECT COUNT(*) FROM chat_msgs WHERE to_uid=? AND read_at IS NULL",
                   (me,)).fetchone()[0]
    # 小组那部分按水位数（见 _mark_read 里的说明）
    n += db.execute(
        "SELECT COALESCE(SUM((SELECT COUNT(*) FROM chat_msgs x WHERE x.conv_id=c.id "
        "  AND x.id>mm.last_read_id AND x.from_uid<>?)),0) "
        "FROM conversations c JOIN conv_members mm ON mm.conv_id=c.id AND mm.user_id=? "
        "WHERE c.kind='group'", (me, me)).fetchone()[0] or 0
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


def listener_count():
    """当前挂着的聊天 SSE 连接数。给后台「服务并发」那块读。

    这个数就是**此刻被 SSE 占住的 waitress 线程数**（一条连接 = 一个阻塞线程，
    最长活 300 秒）。线程池一共就那么大，池子见底的症状是整站变慢而不是报错，
    日志里什么都不会有 —— 所以它必须有个能看见的刻度。
    """
    with _listeners_lock:
        return sum(len(s) for s in _chat_listeners.values())


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
