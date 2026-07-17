"""错题本：收错题 + 归因 + 复盘。


"""
import json
import os
import re
import uuid

from flask import Blueprint, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods.ai import _ai_call_or_error
from mods.files import _remove_file, _user_dir

bp = Blueprint("wrongq", __name__)


WQ_BOARDS = ["常识判断", "资料分析", "判断推理", "数量关系", "政治理论", "言语理解与表达", "申论"]


def _wq_analyze(question, answer=""):
    prompt = (
        "你是公务员考试(行测/申论)辅导老师。分析下面这道题"
        + ("（附我的作答或参考解析）" if answer else "")
        + "，只输出一个 JSON 对象（不要多余文字），字段如下：\n"
        '{"board":"所属板块，取值之一：' + "/".join(WQ_BOARDS) + '",\n'
        ' "qtype":"具体题型（如：资料分析-增长率、判断推理-类比推理、逻辑填空 等）",\n'
        ' "points":"涉及的核心知识点",\n'
        ' "method":"用到的公式或方法",\n'
        ' "skill":"解题技巧与易错点",\n'
        ' "steps":"清晰的解题步骤，分条，用\\n换行"}\n\n题目：\n' + question
        + (("\n\n我的作答/参考解析：\n" + answer) if answer else ""))
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考辅导老师，只输出规范的 JSON 对象。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=1500, json_mode=True)
    if err:
        return None, err
    try:
        d = json.loads(reply)
    except Exception:
        m = re.search(r"\{.*\}", reply or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:
            d = {}
    out = {}
    for k in ("board", "qtype", "points", "method", "skill", "steps"):
        v = d.get(k)
        out[k] = v.strip() if isinstance(v, str) else ("" if v is None else str(v))
    return out, None


def _wq_dict(r):
    return {"id": r["id"], "board": r["board"] or "", "question": r["question"] or "",
            "image": ("/api/wrongq/%d/image" % r["id"]) if r["image"] else "",
            "answer": r["answer"] or "", "qtype": r["qtype"] or "", "points": r["points"] or "",
            "method": r["method"] or "", "skill": r["skill"] or "", "steps": r["steps"] or "",
            "note": r["note"] or "", "starred": bool(r["starred"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _get_wq(wid):
    return get_db().execute("SELECT * FROM wrong_questions WHERE id=? AND user_id=?",
                            (wid, uid())).fetchone()


@bp.get("/api/wrongq/boards")
def wq_boards():
    db = get_db()
    rows = db.execute("SELECT board,COUNT(*) c FROM wrong_questions WHERE user_id=? "
                      "GROUP BY board ORDER BY c DESC", (uid(),)).fetchall()
    return jsonify({"boards": [{"name": r["board"] or "未分类", "count": r["c"]} for r in rows],
                    "total": db.execute("SELECT COUNT(*) c FROM wrong_questions WHERE user_id=?", (uid(),)).fetchone()["c"],
                    "star": db.execute("SELECT COUNT(*) c FROM wrong_questions WHERE user_id=? AND starred=1", (uid(),)).fetchone()["c"]})


@bp.get("/api/wrongq")
def wq_list():
    board = (request.args.get("board") or "").strip()
    star = request.args.get("star") == "1"
    q = (request.args.get("q") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1
    size = 10
    where, args = ["user_id=?"], [uid()]
    if board:
        where.append("board=?"); args.append(board)
    if star:
        where.append("starred=1")
    if q:
        where.append("(question LIKE ? OR qtype LIKE ? OR points LIKE ?)")
        L = "%" + q + "%"; args += [L, L, L]
    wsql = " WHERE " + " AND ".join(where)
    db = get_db()
    total = db.execute("SELECT COUNT(*) n FROM wrong_questions" + wsql, args).fetchone()["n"]
    rows = db.execute("SELECT * FROM wrong_questions" + wsql + " ORDER BY id DESC LIMIT ? OFFSET ?",
                      args + [size, (page - 1) * size]).fetchall()
    return jsonify({"items": [_wq_dict(r) for r in rows], "total": total, "page": page,
                    "pages": max(1, (total + size - 1) // size)})


@bp.post("/api/wrongq")
def wq_create():
    question = (request.form.get("question") or "").strip()
    answer = (request.form.get("answer") or "").strip()
    board = (request.form.get("board") or "").strip()
    do_ai = request.form.get("analyze", "1") != "0"
    img = request.files.get("image")
    stored = ""
    if img and img.filename:
        ext = os.path.splitext(img.filename)[1].lower() or ".jpg"
        stored = "wq_" + uuid.uuid4().hex + ext
        img.save(os.path.join(_user_dir(uid()), stored))
    if not question and not stored:
        return jsonify({"error": "请填写题目或上传图片"}), 400
    f = {"board": board, "qtype": "", "points": "", "method": "", "skill": "", "steps": ""}
    if do_ai and question:
        res, err = _wq_analyze(question, answer)
        if res:
            for k, v in res.items():
                if v:
                    f[k] = v
            if not board and res.get("board"):
                f["board"] = res["board"]
    db = get_db()
    cur = db.execute(
        "INSERT INTO wrong_questions(user_id,board,question,image,answer,qtype,points,method,skill,steps) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid(), f["board"], question, stored, answer, f["qtype"], f["points"], f["method"], f["skill"], f["steps"]))
    db.commit()
    return jsonify(_wq_dict(db.execute("SELECT * FROM wrong_questions WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.post("/api/wrongq/<int:wid>/analyze")
def wq_reanalyze(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    if not (r["question"] or "").strip():
        return jsonify({"error": "没有题目文字，请先填写题干或对图片做 OCR"}), 400
    res, err = _wq_analyze(r["question"], r["answer"] or "")
    if err:
        return err
    board = r["board"] or res.get("board") or ""
    get_db().execute(
        "UPDATE wrong_questions SET board=?,qtype=?,points=?,method=?,skill=?,steps=?,"
        "updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
        (board, res["qtype"], res["points"], res["method"], res["skill"], res["steps"], wid, uid()))
    get_db().commit()
    return jsonify(_wq_dict(_get_wq(wid)))


@bp.get("/api/wrongq/<int:wid>")
def wq_get(wid):
    r = _get_wq(wid)
    return (jsonify(_wq_dict(r)) if r else (jsonify({"error": "未找到"}), 404))


@bp.put("/api/wrongq/<int:wid>")
def wq_update(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = request.get_json(silent=True) or {}
    sets, args = [], []
    for fld in ("board", "question", "answer", "qtype", "points", "method", "skill", "steps", "note"):
        if fld in d:
            sets.append(fld + "=?"); args.append((d.get(fld) or "").strip())
    if "starred" in d:
        sets.append("starred=?"); args.append(1 if d.get("starred") else 0)
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        args += [wid, uid()]
        get_db().execute("UPDATE wrong_questions SET %s WHERE id=? AND user_id=?" % ",".join(sets), args)
        get_db().commit()
    return jsonify(_wq_dict(_get_wq(wid)))


@bp.delete("/api/wrongq/<int:wid>")
def wq_delete(wid):
    r = _get_wq(wid)
    if not r:
        return jsonify({"error": "未找到"}), 404
    if r["image"]:
        _remove_file(uid(), r["image"])
    get_db().execute("DELETE FROM wrong_questions WHERE id=? AND user_id=?", (wid, uid()))
    get_db().commit()
    return jsonify({"ok": True})


@bp.get("/api/wrongq/<int:wid>/image")
def wq_image(wid):
    r = _get_wq(wid)
    if not r or not r["image"]:
        return "未找到", 404
    p = os.path.join(UPLOADS, str(uid()), r["image"])
    if not os.path.exists(p):
        return "文件丢失", 404
    return send_file(p, as_attachment=False)
