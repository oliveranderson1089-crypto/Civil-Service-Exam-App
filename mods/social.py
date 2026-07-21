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

from core import CFG, UPLOADS, get_db, log, uid, uname
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
def _chat_copy_to_drive(db, to, name, src_dir, stored_name, ext, mime, size):
    """收到的文件也放进收件人云盘的「聊天文件」文件夹里，方便他保存/转存。"""
    dst = uuid.uuid4().hex + (ext or "")
    try:
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
