"""知识库：笔记本 + 文档树。


"""
import json
import os
import uuid

from flask import Blueprint, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods.files import (INLINE_EXT, OFFICE_EXT, _extract_text, _no_script,
                        _office_to_pdf, _remove_file, _user_dir)
from mods.notes import _jl

bp = Blueprint("kb", __name__)


def _kb_notebook(nb_id):
    return get_db().execute(
        "SELECT * FROM notebooks WHERE id=? AND user_id=?", (nb_id, uid())).fetchone()


def _kb_get_node(node_id):
    return get_db().execute(
        "SELECT * FROM kb_nodes WHERE id=? AND user_id=?", (node_id, uid())).fetchone()


def _notebook_dict(row):
    n = get_db().execute(
        "SELECT COUNT(*) c FROM kb_nodes WHERE notebook_id=? AND type='doc'",
        (row["id"],)).fetchone()["c"]
    return {"id": row["id"], "name": row["name"], "intro": row["intro"] or "",
            "cover": row["cover"] or 0, "doc_count": n,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _node_dict(row, with_content=False):
    d = {"id": row["id"], "notebook_id": row["notebook_id"],
         "parent_id": row["parent_id"], "type": row["type"],
         "title": row["title"] or "", "updated_at": row["updated_at"]}
    if with_content:
        d["content"] = _jl(row, "content")
    return d


def _kb_tree(nb_id):
    rows = get_db().execute(
        "SELECT * FROM kb_nodes WHERE notebook_id=? AND user_id=? ORDER BY sort, id",
        (nb_id, uid())).fetchall()
    nodes = {r["id"]: {**_node_dict(r), "children": []} for r in rows}
    roots = []
    for r in rows:
        nd = nodes[r["id"]]
        p = r["parent_id"]
        if p and p in nodes:
            nodes[p]["children"].append(nd)
        else:
            roots.append(nd)
    return roots


def _kb_assets_in_content(content):
    """从文档块 JSON 里收集引用的存储文件名，便于删除时清理。"""
    out = []
    for b in (content or []):
        data = b.get("data") or {}
        s = data.get("stored")
        if s:
            out.append(s)
    return out


@bp.get("/api/kb/notebooks")
def kb_notebooks():
    rows = get_db().execute(
        "SELECT * FROM notebooks WHERE user_id=? ORDER BY sort, id DESC", (uid(),)).fetchall()
    return jsonify({"items": [_notebook_dict(r) for r in rows]})


@bp.post("/api/kb/notebooks")
def kb_notebook_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "请填写知识库名称"}), 400
    intro = (data.get("intro") or "").strip()
    cover = int(data.get("cover") or 0)
    db = get_db()
    cur = db.execute("INSERT INTO notebooks(user_id,name,intro,cover) VALUES(?,?,?,?)",
                     (uid(), name, intro, cover))
    db.commit()
    return jsonify(_notebook_dict(db.execute(
        "SELECT * FROM notebooks WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.put("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_update(nb_id):
    if not _kb_notebook(nb_id):
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    sets, args = [], []
    if "name" in data:
        nm = (data.get("name") or "").strip()
        if not nm:
            return jsonify({"error": "名称不能为空"}), 400
        sets.append("name=?"); args.append(nm)
    if "intro" in data:
        sets.append("intro=?"); args.append((data.get("intro") or "").strip())
    if "cover" in data:
        sets.append("cover=?"); args.append(int(data.get("cover") or 0))
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [nb_id, uid()]
        get_db().execute("UPDATE notebooks SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        get_db().commit()
    return jsonify(_notebook_dict(_kb_notebook(nb_id)))


@bp.delete("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_delete(nb_id):
    if not _kb_notebook(nb_id):
        return jsonify({"error": "未找到"}), 404
    db = get_db()
    for r in db.execute("SELECT content FROM kb_nodes WHERE notebook_id=? AND user_id=?",
                        (nb_id, uid())).fetchall():
        for s in _kb_assets_in_content(_jl(r, "content")):
            _remove_file(uid(), s)
    db.execute("DELETE FROM kb_nodes WHERE notebook_id=? AND user_id=?", (nb_id, uid()))
    db.execute("DELETE FROM notebooks WHERE id=? AND user_id=?", (nb_id, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/kb/notebooks/<int:nb_id>")
def kb_notebook_detail(nb_id):
    nb = _kb_notebook(nb_id)
    if not nb:
        return jsonify({"error": "未找到"}), 404
    return jsonify({"notebook": _notebook_dict(nb), "tree": _kb_tree(nb_id)})


@bp.post("/api/kb/nodes")
def kb_node_create():
    data = request.get_json(silent=True) or {}
    nb_id = data.get("notebook_id")
    if not _kb_notebook(nb_id):
        return jsonify({"error": "知识库不存在"}), 404
    ntype = data.get("type")
    if ntype not in ("group", "doc"):
        return jsonify({"error": "类型错误"}), 400
    parent_id = data.get("parent_id") or None
    if parent_id is not None:
        p = _kb_get_node(parent_id)
        if not p or p["type"] != "group" or p["notebook_id"] != nb_id:
            return jsonify({"error": "父分组无效"}), 400
    title = (data.get("title") or "").strip()
    if not title:
        title = "未命名分组" if ntype == "group" else "无标题文档"
    db = get_db()
    nxt = db.execute("SELECT COALESCE(MAX(sort),0)+1 s FROM kb_nodes "
                     "WHERE notebook_id=? AND IFNULL(parent_id,0)=IFNULL(?,0)",
                     (nb_id, parent_id)).fetchone()["s"]
    cur = db.execute(
        "INSERT INTO kb_nodes(user_id,notebook_id,parent_id,type,title,content,sort) "
        "VALUES(?,?,?,?,?,?,?)",
        (uid(), nb_id, parent_id, ntype, title, "[]" if ntype == "doc" else None, nxt))
    db.execute("UPDATE notebooks SET updated_at=datetime('now','localtime') WHERE id=?", (nb_id,))
    db.commit()
    return jsonify(_node_dict(db.execute(
        "SELECT * FROM kb_nodes WHERE id=?", (cur.lastrowid,)).fetchone(), with_content=True)), 201


@bp.get("/api/kb/nodes/<int:node_id>")
def kb_node_get(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify(_node_dict(r, with_content=True))


@bp.put("/api/kb/nodes/<int:node_id>")
def kb_node_update(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    sets, args = [], []
    if "title" in data:
        sets.append("title=?"); args.append((data.get("title") or "").strip())
    if "content" in data:
        # 清理被移除的资源文件
        old = _kb_assets_in_content(_jl(r, "content"))
        new = _kb_assets_in_content(data.get("content") or [])
        for s in old:
            if s not in new:
                _remove_file(uid(), s)
        sets.append("content=?"); args.append(json.dumps(data.get("content") or []))
    if "parent_id" in data:
        pid = data.get("parent_id") or None
        if pid is not None:
            p = _kb_get_node(pid)
            if not p or p["type"] != "group" or p["notebook_id"] != r["notebook_id"] or pid == node_id:
                return jsonify({"error": "目标分组无效"}), 400
        sets.append("parent_id=?"); args.append(pid)
    if "sort" in data:
        sets.append("sort=?"); args.append(int(data.get("sort") or 0))
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [node_id, uid()]
        db = get_db()
        db.execute("UPDATE kb_nodes SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        db.execute("UPDATE notebooks SET updated_at=datetime('now','localtime') WHERE id=?",
                   (r["notebook_id"],))
        db.commit()
    return jsonify(_node_dict(_kb_get_node(node_id), with_content=True))


@bp.delete("/api/kb/nodes/<int:node_id>")
def kb_node_delete(node_id):
    r = _kb_get_node(node_id)
    if not r:
        return jsonify({"error": "未找到"}), 404
    db = get_db()
    # 递归收集子孙
    to_del, stack = [], [node_id]
    while stack:
        cur = stack.pop()
        to_del.append(cur)
        for ch in db.execute("SELECT id FROM kb_nodes WHERE parent_id=? AND user_id=?",
                             (cur, uid())).fetchall():
            stack.append(ch["id"])
    for nid in to_del:
        row = db.execute("SELECT content FROM kb_nodes WHERE id=?", (nid,)).fetchone()
        if row:
            for s in _kb_assets_in_content(_jl(row, "content")):
                _remove_file(uid(), s)
        db.execute("DELETE FROM kb_nodes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return jsonify({"ok": True})


KB_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")


@bp.post("/api/kb/upload")
def kb_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "没有文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    stored = "kb_" + uuid.uuid4().hex + ext
    path = os.path.join(_user_dir(uid()), stored)
    f.save(path)
    is_img = ext in KB_IMG_EXT
    return jsonify({
        "stored": stored, "name": f.filename, "ext": ext,
        "size": os.path.getsize(path), "is_image": is_img,
        "viewable": is_img or (ext in INLINE_EXT) or (ext in OFFICE_EXT),
        "url": "/api/kb/asset/" + stored,
    })


@bp.get("/api/kb/asset/<path:stored>")
def kb_asset(stored):
    stored = os.path.basename(stored)
    path = os.path.join(UPLOADS, str(uid()), stored)
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = os.path.splitext(stored)[1].lower()
    if request.args.get("text") == "1":      # 阅读模式取文字
        return jsonify({"text": _extract_text(path, ext) or ""})
    dl = request.args.get("dl") == "1"
    if not dl and ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if pdf:
            return _no_script(send_file(pdf, mimetype="application/pdf", as_attachment=False))
    if not dl and (ext in KB_IMG_EXT or ext in INLINE_EXT):
        return _no_script(send_file(path, as_attachment=False))
    return send_file(path, as_attachment=True)
