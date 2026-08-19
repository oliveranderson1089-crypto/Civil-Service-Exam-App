"""社区专职工作者（资中县）：整卷背题 / 模考，以及**入库校对的裁决台**。

和真题库（realq.py）分开写而不是塞进去，理由和建表时一样：这张卷子有多选、
判断和 40 分主观题，形状根本不同。共用的是**规矩**不是代码 ——

  · 每次作答独立留痕（sq_attempts），不覆盖上一次；
  · 模考期间只报答没答、不透出对错，交卷才判分；
  · 只发「答案靠得住」的题：过了校对闸门（verify='ok'）的才发，
    存疑题留在库里看得见、但做不到。

判分口径一律走 mods/sqscore，这儿一个字都不许重写。
"""
import json
import os
import re
from datetime import date

from flask import Blueprint, jsonify, request

from core import BASE, get_db, uid
from mods import sqscore, timing

bp = Blueprint("shequ", __name__)

SERVABLE = sqscore.SERVABLE_SQL

# 招聘公告的权威事实（build_zizhong.py 也读它）。日期从这儿取而**不是**从用户的
# 「备考计划」里取：那个字段一个用户只有一个，填的是公考的日子；社区笔试是另一场，
# 而且它的日期是公告定死的、对所有人一样，本来就不该让人自己填。
_META = os.path.join(BASE, "zizhong_meta.json")
_meta_cache = {"mtime": 0, "data": None}


def _meta():
    try:
        mt = os.path.getmtime(_META)
    except OSError:
        return None
    if _meta_cache["mtime"] != mt:
        try:
            with open(_META, encoding="utf-8") as f:
                _meta_cache["data"] = json.load(f)
            _meta_cache["mtime"] = mt
        except Exception:
            return None
    return _meta_cache["data"]


def _countdown():
    """距笔试还有多少天。取不到就返回 None —— **宁可不显示，也不要显示一个瞎算的数**。"""
    m = _meta()
    if not m:
        return None
    raw = (m.get("schedule") or {}).get("笔试") or ""
    mm = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", raw)
    if not mm:
        return None
    y, mo, d = (int(x) for x in mm.groups())
    left = (date(y, mo, d) - date.today()).days
    return {"exam_date": "%04d-%02d-%02d" % (y, mo, d), "days": left,
            "sign_up": (m.get("schedule") or {}).get("报名", ""),
            "scope": (m.get("exam") or {}).get("内容", ""),
            "year": m.get("year"), "total": m.get("total")}


def _pub(r, reveal):
    """一道题的对外形状。reveal=False 时**答案和解析一个字都不带出去** ——
       模考模式下前端拿不到就作弊不了，不指望前端自觉不显示。"""
    d = {"id": r["id"], "seq": r["seq"], "part": r["part"], "part_seq": r["part_seq"],
         "part_name": sqscore.PART_NAME.get(r["part"], r["part"]),
         "qtype": r["qtype"], "stem": r["stem"], "score": r["score"],
         "options": json.loads(r["options"] or "[]"),
         "ref_sec": timing.sq_part_sec(r["part"])}
    if reveal:
        d["answer"] = r["answer"]
        d["explain"] = r["explain"] or ""
    return d


@bp.get("/api/shequ/overview")
def overview():
    """有哪些卷、每卷能练多少、我练到哪了。"""
    db, u = get_db(), uid()
    # servable 和 n_doubt **都只数客观题**：主观题不过校对闸门（没有客观答案可校），
    # 混进来的话「可练 N」和「待裁决 M」的分母不一样，两个数摆在同一张卡片上不可比。
    # n_doubt **现算，不读 sq_papers 存的那一列**。存的那份是给脚本看的，
    # 校对跑到一半、或裁决完还没回写时它就过期了 —— 而 servable 是现算的，
    # 两个数一起摆在同一张卡片上就会自相矛盾（实测「60 道待裁决」配「可练 41」）。
    # 同一件事只认一个来源。
    rows = db.execute(
        "SELECT p.id, p.name, p.year, p.kind, p.region, p.n_obj, p.n_sub, "
        "  (SELECT COUNT(*) FROM sq_questions q WHERE q.paper_id=p.id "
        "     AND q.part IN ('single','multi','judge') AND %s) servable, "
        "  (SELECT COUNT(*) FROM sq_questions q WHERE q.paper_id=p.id "
        "     AND q.part IN ('single','multi','judge') AND q.verify<>'ok') n_doubt, "
        "  (SELECT COUNT(*) FROM sq_records r WHERE r.paper_id=p.id AND r.user_id=?) mine "
        # 专项那份是**程序化生成**的练习集，不是真题卷：混在真题列表里会让人
        # 以为资中考过三套卷。它有自己的入口（资中专项），从这儿排除掉。
        "FROM sq_papers p WHERE COALESCE(p.kind,'')<>'专项' "
        "ORDER BY p.year DESC" % SERVABLE, (u,)).fetchall()
    # 考点分布：只统计发得出去的题，**不要拿库存充数**（库存满 ≠ 有题做）
    # 考点分布只统计真题：专项那 18 道是我们自己按公告造的，
    # 算进去会让「资中县情」这一格虚高，看不出真题的真实分布。
    real = ("FROM sq_questions q JOIN sq_papers p ON p.id=q.paper_id "
            "WHERE COALESCE(p.kind,'')<>'专项' AND q.part IN ('single','multi','judge')")
    types = [dict(r) for r in db.execute(
        "SELECT q.qtype, COUNT(*) c %s AND %s GROUP BY q.qtype ORDER BY c DESC"
        % (real, SERVABLE))]
    doubt = db.execute("SELECT COUNT(*) c %s AND q.verify<>'ok'" % real).fetchone()["c"]
    return jsonify({"papers": [dict(r) for r in rows], "types": types,
                    "doubt": doubt, "paper_min": timing.SQ_PAPER_MIN,
                    "rules": sqscore.RULE_TEXT, "exam": _countdown()})


@bp.get("/api/shequ/paper/<int:pid>")
def paper(pid):
    """取整卷。mode=exam 模考（不带答案）/ study 背题（带答案解析）。

    **存疑题不发**：客观题只取过闸的。这会让卷子不满 60 道 —— 那是实话，
    比凑满 60 道里混着错答案强。前端把缺口如实显示成「N 道待裁决」。
    """
    db = get_db()
    mode = request.args.get("mode", "study")
    reveal = mode != "exam"
    p = db.execute("SELECT * FROM sq_papers WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "没有这份卷子"}), 404
    rows = db.execute(
        "SELECT q.* FROM sq_questions q WHERE q.paper_id=? AND "
        "(q.part IN ('case','gongwen') OR %s) ORDER BY q.seq" % SERVABLE, (pid,)).fetchall()
    items = [_pub(r, reveal) for r in rows]
    held = db.execute(
        "SELECT COUNT(*) c FROM sq_questions WHERE paper_id=? AND part IN "
        "('single','multi','judge') AND verify<>'ok'", (pid,)).fetchone()["c"]
    parts = []
    for key in ("single", "multi", "judge", "case", "gongwen"):
        got = [i for i in items if i["part"] == key]
        if got:
            parts.append({"part": key, "name": sqscore.PART_NAME[key], "n": len(got),
                          "score": round(sum(i["score"] for i in got), 1),
                          "rule": sqscore.RULE_TEXT.get(key, "")})
    return jsonify({"paper": dict(p), "mode": mode, "items": items, "parts": parts,
                    "held": held, "seconds": timing.sq_paper_seconds(),
                    "obj_full": round(sum(i["score"] for i in items
                                          if i["part"] in sqscore.OBJ_PARTS), 1)})


@bp.post("/api/shequ/submit")
def submit():
    """交卷。客观题当场判，主观题只登记「答了没」，分数留给采分点批改。"""
    db, u = get_db(), uid()
    d = request.get_json(silent=True) or {}
    pid = int(d.get("paper_id") or 0)
    mode = d.get("mode") or "study"
    secs = int(d.get("seconds") or 0)
    answers = d.get("answers") or {}          # {qid: "A" / "ABD" / "T" / 主观题正文}
    rows = db.execute("SELECT * FROM sq_questions WHERE paper_id=?", (pid,)).fetchall()
    by_id = {r["id"]: r for r in rows}

    detail, got, full, ndone = [], 0.0, 0.0, 0
    for qid_s, chosen in answers.items():
        r = by_id.get(int(qid_s))
        if not r:
            continue
        part = r["part"]
        if part in sqscore.OBJ_PARTS:
            if not sqscore.servable(r):       # 存疑题就算前端发上来也不判分
                continue
            ok = sqscore.is_correct(part, chosen, r["answer"])
            sc = sqscore.score_of(part, chosen, r["answer"], r["score"])
            got += sc
            if sqscore.norm_chosen(part, chosen):
                ndone += 1
            miss, extra = sqscore.miss_and_extra(part, chosen, r["answer"])
            detail.append({"qid": r["id"], "seq": r["seq"], "part": part,
                           "chosen": chosen, "correct": 1 if ok else 0,
                           "miss": miss, "extra": extra})
            db.execute("INSERT INTO sq_attempts(user_id,qid,chosen,correct,secs,mode) "
                       "VALUES(?,?,?,?,?,?)",
                       (u, r["id"], str(chosen)[:16], 1 if ok else 0, 0, mode))
        else:
            text = (chosen or "").strip()
            if text:
                ndone += 1
            detail.append({"qid": r["id"], "seq": r["seq"], "part": part,
                           "chosen": text, "correct": -1})   # -1 = 待批改，不是错
    for r in rows:
        if r["part"] in sqscore.OBJ_PARTS and sqscore.servable(r):
            full += float(r["score"] or 0)

    cur = db.execute(
        "INSERT INTO sq_records(user_id,paper_id,mode,obj_score,obj_full,n_done,n_total,"
        "secs,detail) VALUES(?,?,?,?,?,?,?,?,?)",
        (u, pid, mode, round(got, 1), round(full, 1), ndone, len(rows), secs,
         json.dumps(detail, ensure_ascii=False)))
    db.commit()
    return jsonify({"id": cur.lastrowid, "obj_score": round(got, 1),
                    "obj_full": round(full, 1), "n_done": ndone,
                    "n_sub": sum(1 for x in detail if x["correct"] == -1),
                    "detail": detail})


@bp.get("/api/shequ/records")
def records():
    rows = get_db().execute(
        "SELECT r.id,r.mode,r.obj_score,r.obj_full,r.n_done,r.n_total,r.secs,r.created_at,"
        "  p.name paper_name, p.year FROM sq_records r LEFT JOIN sq_papers p ON p.id=r.paper_id "
        "WHERE r.user_id=? ORDER BY r.id DESC LIMIT 60", (uid(),)).fetchall()
    name = {"exam": "模考", "study": "背题"}
    return jsonify({"items": [dict(r, mode_name=name.get(r["mode"], r["mode"] or ""))
                              for r in rows]})


@bp.get("/api/shequ/record/<int:rid>")
def record(rid):
    """回看某一次：作答从记录里取，题面/答案/解析**现查库**（记录表不存题面）。"""
    db = get_db()
    r = db.execute("SELECT * FROM sq_records WHERE id=? AND user_id=?",
                   (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "没有这条记录"}), 404
    detail = json.loads(r["detail"] or "[]")
    qids = [x["qid"] for x in detail] or [0]
    qs = {q["id"]: q for q in db.execute(
        "SELECT * FROM sq_questions WHERE id IN (%s)" % ",".join("?" * len(qids)), qids)}
    items = []
    for x in detail:
        q = qs.get(x["qid"])
        if not q:
            continue
        items.append(dict(_pub(q, True), chosen=x.get("chosen", ""),
                          correct=x.get("correct", 0),
                          miss=x.get("miss", ""), extra=x.get("extra", "")))
    return jsonify({"record": dict(r, detail=None), "items": items})


# ---------------------------------------------------------------- 资中专项
@bp.get("/api/shequ/facts")
def facts():
    """资中专项的速记卡。

    **每条都带来源与年份**，界面上必须显示 —— 本地数据是会过期的：县情 PDF 里
    还有 2018 年的数字，招聘公告和统计公报每年换。不标年份就是假知识。

    proven=1 的排在前面：两套原卷里 8 道本地题全部出自招聘公告参数，
    没有一道考县情地理或 GDP。所以「真题考过」这一档不能和其余的混着摆。
    """
    db = get_db()
    rows = db.execute("SELECT * FROM sq_facts ORDER BY grp, ord").fetchall()
    groups, order = {}, []
    for r in rows:
        g = r["grp"]
        if g not in groups:
            groups[g] = {"grp": g, "items": [], "proven": 0}
            order.append(g)
        groups[g]["items"].append(dict(r))
        groups[g]["proven"] += 1 if r["proven"] else 0
    # 「真题考过的条目多」的组排前面，不按字典序
    out = sorted((groups[g] for g in order), key=lambda x: -x["proven"])
    paper = db.execute("SELECT id, n_obj FROM sq_papers WHERE kind='专项'").fetchone()
    return jsonify({"groups": out, "total": len(rows),
                    "quiz_paper": paper["id"] if paper else 0,
                    "quiz_n": paper["n_obj"] if paper else 0, "exam": _countdown()})


# ---------------------------------------------------------------- 校对裁决台
@bp.get("/api/shequ/doubts")
def doubts():
    """待裁决的存疑题。**三方答案并排给出来**，人点一下就行。"""
    db = get_db()
    rows = db.execute(
        "SELECT q.*, p.name paper_name, p.year FROM sq_questions q "
        "LEFT JOIN sq_papers p ON p.id=q.paper_id "
        "WHERE q.part IN ('single','multi','judge') AND q.verify<>'ok' "
        "ORDER BY q.paper_id, q.seq").fetchall()
    out = []
    for r in rows:
        try:
            note = json.loads(r["verify_note"] or "{}")
        except Exception:
            note = {}
        out.append(dict(_pub(r, True), paper_name=r["paper_name"], year=r["year"],
                        verify=r["verify"], note=note))
    # 体检单：每份卷子过闸多少、存疑多少、不入库多少
    # **四个数都只数客观题**。主观题没有客观答案可校，压根不过这道闸；
    # 把它们算进 todo 会显示成「还有 3 道没校对」，让人以为闸门漏了活。
    health = [dict(r) for r in db.execute(
        "SELECT p.id, p.name, p.year, COUNT(q.id) obj, "
        "  SUM(CASE WHEN q.verify='ok' THEN 1 ELSE 0 END) ok, "
        "  SUM(CASE WHEN q.verify='doubt' THEN 1 ELSE 0 END) doubt, "
        "  SUM(CASE WHEN q.verify='bad' THEN 1 ELSE 0 END) bad, "
        "  SUM(CASE WHEN COALESCE(q.verify,'')='' THEN 1 ELSE 0 END) todo "
        "FROM sq_papers p LEFT JOIN sq_questions q ON q.paper_id=p.id "
        "  AND q.part IN ('single','multi','judge') "
        "GROUP BY p.id ORDER BY p.year DESC")]
    return jsonify({"items": out, "health": health})


@bp.post("/api/shequ/doubt/<int:qid>")
def doubt_rule(qid):
    """裁决一道存疑题。

    act=accept  采信建议答案（改答案 + 过闸）
    act=keep    维持源答案并过闸（你确认源卷是对的）
    act=hold    保留存疑（默认态，什么都不做，留着以后再看）
    act=drop    判定这题没法用（verify='bad'，永不发出）
    """
    db = get_db()
    d = request.get_json(silent=True) or {}
    act = d.get("act") or "hold"
    q = db.execute("SELECT * FROM sq_questions WHERE id=?", (qid,)).fetchone()
    if not q:
        return jsonify({"error": "没有这道题"}), 404
    try:
        note = json.loads(q["verify_note"] or "{}")
    except Exception:
        note = {}
    if act == "accept":
        suggest = (d.get("answer") or note.get("suggest") or "").strip().upper()
        suggest = sqscore.norm_chosen(q["part"], suggest)
        if not suggest:
            return jsonify({"error": "没有可采信的建议答案"}), 400
        note["ruled"] = {"act": "accept", "from": q["answer"], "to": suggest}
        db.execute("UPDATE sq_questions SET answer=?, verify='ok', verify_note=? WHERE id=?",
                   (suggest, json.dumps(note, ensure_ascii=False), qid))
    elif act == "keep":
        note["ruled"] = {"act": "keep", "answer": q["answer"]}
        db.execute("UPDATE sq_questions SET verify='ok', verify_note=? WHERE id=?",
                   (json.dumps(note, ensure_ascii=False), qid))
    elif act == "drop":
        note["ruled"] = {"act": "drop"}
        db.execute("UPDATE sq_questions SET verify='bad', verify_note=? WHERE id=?",
                   (json.dumps(note, ensure_ascii=False), qid))
    else:
        note["ruled"] = {"act": "hold"}
        db.execute("UPDATE sq_questions SET verify='doubt', verify_note=? WHERE id=?",
                   (json.dumps(note, ensure_ascii=False), qid))
    # 卷子上的存疑计数跟着走，别让体检单和实际不一致
    db.execute(
        "UPDATE sq_papers SET n_doubt=(SELECT COUNT(*) FROM sq_questions q "
        "  WHERE q.paper_id=sq_papers.id AND q.part IN ('single','multi','judge') "
        "  AND q.verify<>'ok') WHERE id=?", (q["paper_id"],))
    db.commit()
    return jsonify({"ok": True, "act": act})
