"""小记（仿语雀）：随手记 + 附件。


"""
import json
import os
import uuid

from flask import Blueprint, Response, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods.files import (INLINE_EXT, OFFICE_EXT, TEXT_EXT, _extract_text,
                        _no_script, _office_to_pdf, _remove_file, _user_dir)

bp = Blueprint("notes", __name__)


NOTE_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _jl(row, key):
    try:
        return json.loads(row[key] or "[]")
    except Exception:
        return []


def _note_dict(row):
    imgs = _jl(row, "images")
    atts = _jl(row, "attachments")
    return {
        "id": row["id"], "board": row["board"] or "", "content": row["content"] or "",
        "images": ["/api/notes/%d/img/%d" % (row["id"], i) for i in range(len(imgs))],
        "img_files": imgs,
        "attachments": [{"name": a.get("name"), "ext": a.get("ext", ""),
                         "viewable": (a.get("ext") in INLINE_EXT) or (a.get("ext") in OFFICE_EXT),
                         "url": "/api/notes/%d/file/%d" % (row["id"], i)}
                        for i, a in enumerate(atts)],
        "att_files": atts,
        "todos": _jl(row, "todos"),
        "tags": _jl(row, "tags"),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _save_note_images(files):
    names = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in NOTE_IMG_EXT:
            # 相册/content URI 选图常无扩展名：按 mimetype 兜底
            mt = (f.mimetype or "").lower()
            if mt.startswith("image/"):
                ext = "." + mt.split("/", 1)[1].split("+")[0]
                if ext not in NOTE_IMG_EXT:
                    ext = ".jpg"
            else:
                continue
        stored = "note_" + uuid.uuid4().hex + ext
        f.save(os.path.join(_user_dir(uid()), stored))
        names.append(stored)
    return names


def _save_note_atts(files):
    out = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        stored = "natt_" + uuid.uuid4().hex + ext
        f.save(os.path.join(_user_dir(uid()), stored))
        out.append({"file": stored, "name": f.filename, "ext": ext,
                    "size": os.path.getsize(os.path.join(_user_dir(uid()), stored))})
    return out


def _parse_json(s, default):
    try:
        v = json.loads(s)
        return v if v is not None else default
    except Exception:
        return default


def _get_note(nid):
    return get_db().execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()


@bp.post("/api/notes")
def note_create():
    board = (request.form.get("board") or "").strip()
    content = (request.form.get("content") or "").strip()
    todos = _parse_json(request.form.get("todos"), [])
    tags = _parse_json(request.form.get("tags"), [])
    imgs = _save_note_images(request.files.getlist("images"))
    atts = _save_note_atts(request.files.getlist("attachments"))
    if not (content or imgs or atts or todos):
        return jsonify({"error": "内容不能为空"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO notes(user_id,board,content,images,attachments,todos,tags) VALUES(?,?,?,?,?,?,?)",
        (uid(), board, content, json.dumps(imgs), json.dumps(atts),
         json.dumps(todos), json.dumps(tags)))
    db.commit()
    return jsonify(_note_dict(db.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.get("/api/notes")
def note_list():
    board = (request.args.get("board") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    db = get_db()
    sql = "SELECT * FROM notes WHERE user_id=?"
    args = [uid()]
    if board:
        sql += " AND board=?"
        args.append(board)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, args).fetchall()
    items = [_note_dict(r) for r in rows]
    if tag:
        items = [n for n in items if tag in n["tags"]]
    return jsonify({"items": items})


@bp.get("/api/notes/counts")
def note_counts():
    rows = get_db().execute(
        "SELECT board, COUNT(*) c FROM notes WHERE user_id=? GROUP BY board", (uid(),)).fetchall()
    return jsonify({"counts": {(r["board"] or ""): r["c"] for r in rows},
                    "total": sum(r["c"] for r in rows)})


@bp.get("/api/notes/tags")
def note_tags():
    board = (request.args.get("board") or "").strip()
    sql = "SELECT id, tags FROM notes WHERE user_id=?"
    args = [uid()]
    if board:
        sql += " AND board=?"
        args.append(board)
    seen, out, cnt, last = set(), [], {}, {}
    for r in get_db().execute(sql, args).fetchall():
        for t in _jl(r, "tags"):
            cnt[t] = cnt.get(t, 0) + 1
            last[t] = max(last.get(t, 0), r["id"])
            if t not in seen:
                seen.add(t)
                out.append(t)
    """items 比 tags 多两样东西：**用了多少条**，以及**按「常用 + 最近」排好的顺序**。

    标签攒到三四十个之后，一行行平铺在顶上就没法用了（占掉半屏，还得拿眼睛找）。
    前端据此只把前几个摆在外面、其余收进「更多」。

    排序为什么要带上「最近」：实测这个库里 39 个标签有 34 个只用过一次 —— 只按条数排，
    那 34 个就退化成**建库顺序**（也就是最老的排最前），正好是最没用的一头。
    所以条数相同就看最近一次用在哪条小记上，手头正在写的那批自然浮上来。
    排序放服务端做：同一份口径前后端各排一次，迟早会不一致。"""
    items = sorted(({"tag": t, "n": cnt[t], "last": last[t]} for t in out),
                   key=lambda x: (-x["n"], -x["last"]))
    return jsonify({"tags": out, "items": items})


@bp.get("/api/notes/<int:nid>/img/<int:idx>")
def note_img(nid, idx):
    n = _get_note(nid)
    if not n:
        return "未找到", 404
    imgs = _jl(n, "images")
    if idx < 0 or idx >= len(imgs):
        return "未找到", 404
    path = os.path.join(UPLOADS, str(uid()), imgs[idx])
    if not os.path.exists(path):
        return "文件丢失", 404
    return _no_script(send_file(path, as_attachment=False))


@bp.get("/api/notes/<int:nid>/file/<int:idx>")
def note_file(nid, idx):
    n = _get_note(nid)
    if not n:
        return "未找到", 404
    atts = _jl(n, "attachments")
    if idx < 0 or idx >= len(atts):
        return "未找到", 404
    a = atts[idx]
    path = os.path.join(UPLOADS, str(uid()), a["file"])
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = a.get("ext", "")
    dl = request.args.get("dl") == "1"
    if not dl and ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if pdf:
            return _no_script(send_file(pdf, mimetype="application/pdf", as_attachment=False))
    if not dl and ext in (".html", ".htm"):
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/html; charset=utf-8")
    if not dl and ext in TEXT_EXT:
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/plain; charset=utf-8")
    if not dl and ext in INLINE_EXT:
        return _no_script(send_file(path, as_attachment=False, download_name=a.get("name")))
    return send_file(path, as_attachment=True, download_name=a.get("name") or a["file"])


@bp.get("/api/notes/<int:nid>/file/<int:idx>/text")
def note_file_text(nid, idx):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    atts = _jl(n, "attachments")
    if idx < 0 or idx >= len(atts):
        return jsonify({"error": "未找到"}), 404
    a = atts[idx]
    t = _extract_text(os.path.join(UPLOADS, str(uid()), a["file"]), a.get("ext", ""))
    if t is None:
        return jsonify({"error": "文件丢失"}), 404
    return jsonify({"text": t})


@bp.put("/api/notes/<int:nid>")
def note_update(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    content = (request.form.get("content") or "").strip()
    todos = _parse_json(request.form.get("todos"), [])
    tags = _parse_json(request.form.get("tags"), [])
    # 图片：保留 keep_imgs 中的，删其余，加新上传
    old_i = _jl(n, "images")
    keep_i = _parse_json(request.form.get("keep_imgs"), old_i)
    keep_i = [x for x in old_i if x in keep_i]
    for fn in old_i:
        if fn not in keep_i:
            _remove_file(uid(), fn)
    final_i = keep_i + _save_note_images(request.files.getlist("images"))
    # 附件：同理
    old_a = _jl(n, "attachments")
    keep_af = _parse_json(request.form.get("keep_atts"), [a["file"] for a in old_a])
    keep_a = [a for a in old_a if a["file"] in keep_af]
    for a in old_a:
        if a["file"] not in keep_af:
            _remove_file(uid(), a["file"])
    final_a = keep_a + _save_note_atts(request.files.getlist("attachments"))
    if not (content or final_i or final_a or todos):
        return jsonify({"error": "内容不能为空"}), 400
    db = get_db()
    db.execute("UPDATE notes SET content=?,images=?,attachments=?,todos=?,tags=?,"
               "updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
               (content, json.dumps(final_i), json.dumps(final_a),
                json.dumps(todos), json.dumps(tags), nid, uid()))
    db.commit()
    return jsonify(_note_dict(db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()))


@bp.post("/api/notes/<int:nid>/todo")
def note_toggle_todo(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    idx = data.get("idx")
    todos = _jl(n, "todos")
    if isinstance(idx, int) and 0 <= idx < len(todos):
        todos[idx]["done"] = bool(data.get("done"))
        get_db().execute("UPDATE notes SET todos=? WHERE id=? AND user_id=?",
                         (json.dumps(todos), nid, uid()))
        get_db().commit()
    return jsonify({"ok": True})


@bp.delete("/api/notes/<int:nid>")
def note_delete(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    for fn in _jl(n, "images"):
        _remove_file(uid(), fn)
    for a in _jl(n, "attachments"):
        _remove_file(uid(), a.get("file", ""))
    db = get_db()
    db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


# 从「全文搜索」区段挪回来的：搜索结果点开看详情，可它用的 _get_note/_note_dict
# 都在本模块，落在 search 里是历史遗留。
@bp.get("/api/notes/<int:nid>")
def note_get(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    return jsonify(_note_dict(n))
