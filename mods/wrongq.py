"""错题本：收错题 + 归因 + 复盘。

**全站所有刷题模块的错题都落在这一张表**（专项练 / 历年真题 / 巩固测试 / 题库模拟卷），
靠 (src_kind, src_key) 认「是不是同一道题」：

    realq → real_questions.id      drill / dtest / quiz → 题干规范化后的 sha1 前 16 位
    manual → 空（手动录入的没有来源）

有了这个身份，两个方向才通得起来：
  · 刷题端能问「这道题在错题本里吗」（lookup），当场加入 / 改笔记 / 移出；
  · 错题本这边改了、删了，回到刷题界面看到的也是改后的状态。
原先只有「question 全文相等」这一个判据 —— 题干里改一个标点就变成两条，
反过来也没法从错题定位回原题，所以「同步」根本无从谈起。
"""
import hashlib
import json
import os
import re
import sqlite3
import uuid

from flask import Blueprint, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods.ai import _ai_call_or_error
from mods.files import _no_script, _remove_file, _user_dir

bp = Blueprint("wrongq", __name__)


WQ_BOARDS = ["常识判断", "资料分析", "判断推理", "数量关系", "政治理论", "言语理解与表达", "申论"]
# 来源标签：错题详情里显示「来自哪」，也用来决定能不能「回去重做这道题」
WQ_SRC_NAME = {"realq": "历年真题", "drill": "专项练", "dtest": "巩固测试",
               "quiz": "题库模拟卷", "manual": "手动录入"}


WQ_MAX = 2000          # 题干存进错题本的上限；**算指纹前先截到这儿**，见下


def wq_key(text):
    """题干指纹：空白和全半角标点差异不算「另一道题」。

    刷题端每次渲染都要拿它去 lookup，所以规范化必须**稳定** ——
    同一道题今天算出 abc、明天算出 def 的话，错题本会越攒越多重复条目。

    **先截断再算**：入库的题干是截到 WQ_MAX 的，drill.wrong_text 也是先截断再算指纹。
    这儿拿全文算的话，一道两千字以上的材料题（资料分析整篇材料 + 题干）会出现
    两个不同的 key —— 服务端自动收一条、前端手动收一条，同一道题存成两份。
    """
    s = re.sub(r"\s+", "", (text or "")[:WQ_MAX])
    s = re.sub(r"[，。；：、（）()【】\[\]“”\"'？?！!,.;:]", "", s)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def wq_upsert(db, user_id, kind, key, fields):
    """收一道错题，**同一道题只留一条**。返回 (id, 新收=True/已有=False)。

    已经在本子里的题：只补**空着的**字段，不覆盖已有内容 —— 第二遍又做错时，
    人工写的笔记、改过的答案不能被自动生成的内容洗掉（这正是「刷题端能改」的前提）。
    """
    key = str(key or "")
    row = db.execute("SELECT * FROM wrong_questions WHERE user_id=? AND src_kind=? AND src_key=?",
                     (user_id, kind, key)).fetchone() if key else None
    if not row and fields.get("question"):
        # 老数据认领：这条题在加 src 列之前就收过（当时靠全文相等去重）。
        # 不认领的话，同一道题会以「无来源」和「有来源」各存一条。
        row = db.execute("SELECT * FROM wrong_questions WHERE user_id=? AND question=? "
                         "AND (src_kind IS NULL OR src_kind='')",
                         (user_id, fields["question"])).fetchone()
        if row:
            db.execute("UPDATE wrong_questions SET src_kind=?, src_key=? WHERE id=?",
                       (kind, key, row["id"]))
    if row:
        sets, args = [], []
        for f, v in fields.items():
            if v and not (row[f] if f in row.keys() else ""):
                sets.append(f + "=?"); args.append(v)
        if sets:
            db.execute("UPDATE wrong_questions SET %s WHERE id=?" % ",".join(sets),
                       args + [row["id"]])
        return row["id"], False
    cols = ["user_id", "src_kind", "src_key"] + list(fields)
    try:
        cur = db.execute("INSERT INTO wrong_questions(%s) VALUES(%s)"
                         % (",".join(cols), ",".join("?" * len(cols))),
                         [user_id, kind, key] + list(fields.values()))
    except sqlite3.IntegrityError:
        # 「先查再插」中间有窗口：双击「收错题」会发两个并发请求，两边都查不到、
        # 都走到这句 INSERT，第二个撞 idx_wq_src 唯一索引。这不是错误情形 ——
        # 本来就只该有一条，把先插进去的那条捞出来返回即可（不抛 500 给用户）。
        row = db.execute("SELECT id FROM wrong_questions WHERE user_id=? AND src_kind=? "
                         "AND src_key=?", (user_id, kind, key)).fetchone()
        if not row:
            raise
        return row["id"], False
    return cur.lastrowid, True


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
    k = r.keys()
    src = (r["src_kind"] if "src_kind" in k else "") or ""
    return {"id": r["id"], "board": r["board"] or "", "question": r["question"] or "",
            "image": ("/api/wrongq/%d/image" % r["id"]) if r["image"] else "",
            "answer": r["answer"] or "", "qtype": r["qtype"] or "", "points": r["points"] or "",
            "method": r["method"] or "", "skill": r["skill"] or "", "steps": r["steps"] or "",
            "note": r["note"] or "", "starred": bool(r["starred"]),
            "src_kind": src, "src_key": (r["src_key"] if "src_key" in k else "") or "",
            "src_name": WQ_SRC_NAME.get(src, ""),
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


@bp.post("/api/wrongq/sync")
def wq_sync():
    """刷题界面上的「收进错题本」。同一道题重复点不会收出两条。

    和 POST /api/wrongq 的分工：那个是**人工录入**（带图片、要 AI 分析，十几秒），
    这个是**做题时就地收**（题干答案解析现成的，必须是毫秒级、不调 AI）。
    """
    d = request.get_json(silent=True) or {}
    kind = (d.get("kind") or "").strip() or "manual"
    question = (d.get("question") or "").strip()
    key = str(d.get("key") or "").strip() or (wq_key(question) if question else "")
    if not question:
        return jsonify({"error": "没有题目内容"}), 400
    if kind not in WQ_SRC_NAME:
        return jsonify({"error": "来源不对"}), 400
    db = get_db()
    wid, created = wq_upsert(db, uid(), kind, key, {
        "board": (d.get("board") or "").strip(),
        "question": question[:WQ_MAX],
        "answer": (d.get("answer") or "").strip(),
        "qtype": (d.get("qtype") or "").strip(),
        "points": (d.get("points") or "").strip(),
        "note": (d.get("note") or "").strip(),
    })
    db.commit()
    return jsonify({"id": wid, "created": created,
                    "item": _wq_dict(db.execute("SELECT * FROM wrong_questions WHERE id=?",
                                                (wid,)).fetchone())})


@bp.post("/api/wrongq/lookup")
def wq_lookup():
    """这一批题里，哪些已经在错题本里了（刷题界面渲染按钮要用）。

    一次问一批，别每道题各发一个请求 —— 整卷模考一屏 130 道题。
    真题传 keys（就是真题 id）；专项练/巩固测试的题没有库内 id，传 questions
    让服务端算指纹 —— **指纹算法只此一份**，前端自己算的话两边对不上，
    表现是明明收过的题在做题界面显示成没收过。
    """
    d = request.get_json(silent=True) or {}
    kind = (d.get("kind") or "").strip()
    keys = [str(k) for k in (d.get("keys") or [])][:200]
    qs = [str(q or "") for q in (d.get("questions") or [])][:200]
    if qs:
        keys = [wq_key(q) for q in qs]
    if not kind or not keys:
        return jsonify({"items": {}, "keys": []})
    uniq = list(dict.fromkeys(keys))          # 去重但保序；占位符和参数**同一份**，别各建各的集合
    rows = get_db().execute(
        "SELECT id, src_key, starred, note FROM wrong_questions WHERE user_id=? AND src_kind=? "
        "AND src_key IN (%s)" % ",".join("?" * len(uniq)),
        [uid(), kind] + uniq).fetchall()
    return jsonify({"items": {r["src_key"]: {"id": r["id"], "starred": bool(r["starred"]),
                                             "note": r["note"] or ""} for r in rows},
                    # 算出来的 key 一并回给前端：之后加入/移出直接用它，不用再算一次
                    "keys": keys})


@bp.delete("/api/wrongq/src/<kind>/<key>")
def wq_del_by_src(kind, key):
    """在刷题界面把这道题移出错题本（不用先知道错题 id）。"""
    r = get_db().execute("SELECT * FROM wrong_questions WHERE user_id=? AND src_kind=? AND src_key=?",
                         (uid(), kind, key)).fetchone()
    if not r:
        return jsonify({"ok": True, "removed": 0})
    if r["image"]:
        _remove_file(uid(), r["image"])
    get_db().execute("DELETE FROM wrong_questions WHERE id=?", (r["id"],))
    get_db().commit()
    return jsonify({"ok": True, "removed": 1})


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
    return _no_script(send_file(p, as_attachment=False))
