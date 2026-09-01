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

from core import BASE, get_db, log, uid
from mods import sqgrade, sqscore, timing
from mods.ai import _ai_call_or_error
from mods.review import REVIEW_INTERVALS
from mods.wrongq import wq_upsert

bp = Blueprint("shequ", __name__)

SERVABLE = sqscore.SERVABLE_SQL

# 「真题」页只列真卷子。**用白名单不用黑名单**：这一版只排除了「专项」，
# 后来加「题库」时忘了同步，结果 75 份练习册全跑进真题列表里显示成 77 份卷子。
# 白名单的话，将来再加什么 kind 都不会漏进来。
REAL_KINDS = ("招聘", "公开选聘")
# 模拟卷/押题卷：**是整卷，但不是真题**。和真题分成两组摆，卷子上标明白 ——
# 混在一起会让人以为资中考过七八套，而这门考试的真题一共就两套。
MOCK_KINDS = ("模拟", "押题")
_REAL = "p.kind IN %s" % sqscore.sql_in(REAL_KINDS)
_MOCK = "p.kind IN %s" % sqscore.sql_in(MOCK_KINDS)

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
    # 专项（程序化生成）和题库（练习册）都不是整卷，混进来会让人以为
    # 资中考过七十几套。它们各有自己的入口（资中专项 / 专项练）。
    # 模拟卷是整卷、但**不是真题**，所以单独查一次、单独一组发给前端。
    cols = ("SELECT p.id, p.name, p.year, p.kind, p.region, p.n_obj, p.n_sub, p.n_bad, "
            "  (SELECT COUNT(*) FROM sq_questions q WHERE q.paper_id=p.id "
            "     AND q.part IN %s AND %s) servable, "
            "  (SELECT COUNT(*) FROM sq_questions q WHERE q.paper_id=p.id "
            "     AND q.part IN %s AND q.verify<>'ok') n_doubt, "
            "  (SELECT COUNT(*) FROM sq_records r WHERE r.paper_id=p.id AND r.user_id=?) mine "
            "FROM sq_papers p WHERE %%s ORDER BY p.year DESC, p.name"
            % (sqscore.sql_in(sqscore.OBJ_PARTS), SERVABLE,
               sqscore.sql_in(sqscore.OBJ_PARTS)))
    rows = db.execute(cols % _REAL, (u,)).fetchall()
    # n_bad 是**解析时就没收下的题**（扫描件 OCR 把选项吃了）。发给前端是为了
    # 卷面上能写「93 题里收下 66 道」—— 只报收下的那 66，人会以为自己做完了整卷。
    mocks = [dict(r) for r in db.execute(cols % _MOCK, (u,)).fetchall()]
    # 考点分布：只统计发得出去的题，**不要拿库存充数**（库存满 ≠ 有题做）
    # 考点分布只统计真题：专项那 18 道是我们自己按公告造的，
    # 算进去会让「资中县情」这一格虚高，看不出真题的真实分布。
    real = ("FROM sq_questions q JOIN sq_papers p ON p.id=q.paper_id "
            "WHERE %s AND q.part IN ('single','multi','judge')" % _REAL)
    types = [dict(r) for r in db.execute(
        "SELECT q.qtype, COUNT(*) c %s AND %s GROUP BY q.qtype ORDER BY c DESC"
        % (real, SERVABLE))]
    doubt = db.execute("SELECT COUNT(*) c %s AND q.verify<>'ok'" % real).fetchone()["c"]
    return jsonify({"papers": [dict(r) for r in rows], "mocks": mocks, "types": types,
                    "doubt": doubt, "paper_min": timing.SQ_PAPER_MIN,
                    # 这句话跟着数据一起下发，别在 JS 里另写一份：模拟卷是外省机构编的，
                    # 卷面结构和资中真题不一样（没有案例分析和公文写作那 40 分）。
                    "mock_note": "外省机构编的模拟卷，不是资中真题：卷面只有客观题，"
                                 "没有资中那 40 分的案例分析和公文写作。原件是扫描件，"
                                 "OCR 认不出的题已剔除，缺口如实标在卷名后面。",
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
        "(q.part IN %s OR %s) ORDER BY q.seq"
        % (sqscore.sql_in(sqscore.SUB_PARTS), SERVABLE), (pid,)).fetchall()
    items = [_pub(r, reveal) for r in rows]
    held = db.execute(
        "SELECT COUNT(*) c FROM sq_questions WHERE paper_id=? AND part IN "
        "('single','multi','judge') AND verify<>'ok'", (pid,)).fetchone()["c"]
    parts = []
    for key in sqscore.PAPER_PARTS:
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

    wrong_rows = [r for r in rows if r["part"] in sqscore.OBJ_PARTS and sqscore.servable(r)
                  and str(r["id"]) in answers
                  and not sqscore.is_correct(r["part"], answers[str(r["id"])], r["answer"])]
    n_new = _to_wrongq(db, wrong_rows) if wrong_rows else 0
    cur = db.execute(
        "INSERT INTO sq_records(user_id,paper_id,mode,obj_score,obj_full,n_done,n_total,"
        "secs,detail) VALUES(?,?,?,?,?,?,?,?,?)",
        (u, pid, mode, round(got, 1), round(full, 1), ndone, len(rows), secs,
         json.dumps(detail, ensure_ascii=False)))
    db.commit()
    return jsonify({"id": cur.lastrowid, "obj_score": round(got, 1),
                    "obj_full": round(full, 1), "n_done": ndone,
                    "n_sub": sum(1 for x in detail if x["correct"] == -1),
                    "detail": detail, "to_wrongq": len(wrong_rows), "new_wrongq": n_new})


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


# ---------------------------------------------------------------- 专项练
# 只从**题库**里出题，不动真题卷：真题是标尺，刷散题时把它掺进来，
# 到考前想拿真题估分就估不准了（做过的题再做一遍，分数是虚高的）。
# 「专项练」的题源：题册 + 模拟卷。模拟卷进这儿是因为**题就是题** ——
# 它换了个 kind 是为了能整卷做，不该顺带从专项练里消失（实测会少掉 300 多道）。
BANK_KINDS = ("题库",) + MOCK_KINDS
_BANK = "p.kind IN %s" % sqscore.sql_in(BANK_KINDS)

# 哪些考点是**公告点名或真题考过**的。公告原文：「社会工作者职业资格考试初级知识，
# 党的建设、社区建设、基层治理、法律常识、时事政治等」。
# 「公基常识」（科技与生活 / 计算机 / 人文历史 / 经济）公告没点名、两套真题里也没考过 ——
# 它是题库里最大的一桶（2147 道），**不标出来的话很容易把时间花在不确定考不考的题上**。
# 不删掉是因为「等」字留了口子、社区考试也常带公基；但要让人自己决定练不练。
SURE_QTYPE = {"社区知识": "公告点名", "社会工作": "公告点名（社工初级）",
              "党建党务": "公告点名", "法律法规": "公告点名（法律常识）",
              "时政理论": "公告点名（时事政治）", "公文写作": "真题 15 分",
              "资中县情": "真题考过 8 道", "应急安全": "真题考过"}


@bp.get("/api/shequ/drill/meta")
def drill_meta():
    """能练什么：按题型 × 考点大类给出可练题量，以及我练过多少。"""
    db, u = get_db(), uid()
    rows = db.execute(
        "SELECT q.part, q.qtype, COUNT(*) c, "
        "  COUNT(DISTINCT CASE WHEN a.qid IS NOT NULL THEN q.id END) done "
        "FROM sq_questions q JOIN sq_papers p ON p.id=q.paper_id "
        "LEFT JOIN sq_attempts a ON a.qid=q.id AND a.user_id=? "
        "WHERE %s AND %s GROUP BY q.part, q.qtype ORDER BY c DESC" % (_BANK, SERVABLE),
        (u,)).fetchall()
    parts, types = {}, {}
    for r in rows:
        parts[r["part"]] = parts.get(r["part"], 0) + r["c"]
        t = types.setdefault(r["qtype"], {"qtype": r["qtype"], "c": 0, "done": 0})
        t["c"] += r["c"]
        t["done"] += r["done"]
    return jsonify({
        "parts": [{"part": k, "name": sqscore.PART_NAME.get(k, k), "c": v,
                   "rule": sqscore.RULE_TEXT.get(k, ""),
                   "done": sum(r["done"] for r in rows if r["part"] == k)}
                  for k, v in sorted(parts.items(), key=lambda x: -x[1])],
        "types": [dict(t, sure=SURE_QTYPE.get(t["qtype"], ""))
                  for t in sorted(types.values(),
                                  key=lambda x: (0 if x["qtype"] in SURE_QTYPE else 1, -x["c"]))],
        "total": sum(parts.values())})


@bp.get("/api/shequ/drill")
def drill():
    """抽一组题。**做过的排在后面**——库存满不等于有题做，先把没做过的发完。"""
    db, u = get_db(), uid()
    n = max(1, min(int(request.args.get("n") or 10), 30))
    part = (request.args.get("part") or "").strip()
    qtype = (request.args.get("qtype") or "").strip()
    where, args = [_BANK, SERVABLE], []
    if part in sqscore.OBJ_PARTS:
        where.append("q.part=?")
        args.append(part)
    if qtype:
        where.append("q.qtype=?")
        args.append(qtype)
    rows = db.execute(
        "SELECT q.*, (SELECT COUNT(*) FROM sq_attempts a WHERE a.qid=q.id AND a.user_id=?) tried, "
        "  (SELECT MIN(a.correct) FROM sq_attempts a WHERE a.qid=q.id AND a.user_id=?) everwrong "
        "FROM sq_questions q JOIN sq_papers p ON p.id=q.paper_id WHERE %s "
        # 顺序就是这个接口的价值：**错过的 > 没做过的 > 做对过的**。
        # 全随机的话，刷三遍等于把第一遍重刷三次，最该练的题反而遇不上。
        "ORDER BY CASE WHEN everwrong=0 THEN 0 WHEN tried=0 THEN 1 ELSE 2 END, RANDOM() "
        "LIMIT ?" % " AND ".join(where), [u, u] + args + [n]).fetchall()
    return jsonify({"items": [_pub(r, True) for r in rows],
                    "rules": sqscore.RULE_TEXT})


def _to_wrongq(db, rows):
    """做错的社区题进错题本 + 排进今日复习。

    和真题库那边走**同一张表、同一个 upsert、同一副遗忘曲线** —— 社区这条线不另起
    一套本子，它只是 board 不同（错题本按备考方向过滤，见 mods/line.py）。
    身份用 sq_questions.id：同一道题在整卷里做错、在专项练里也做错，收的是同一条。
    """
    n = 0
    for r in rows:
        opts = json.loads(r["options"] or "[]")
        body = r["stem"] + ("\n" + "\n".join("%s. %s" % (c, o) for c, o in zip("ABCD", opts))
                            if opts else "")
        ans = r["answer"]
        if r["part"] == "judge":
            ans = "√ 正确" if ans == "T" else "× 错误"
        wid, created = wq_upsert(db, uid(), "sq", str(r["id"]), {
            "board": r["qtype"] or "社区知识",
            "question": ("【%s】%s" % (sqscore.PART_NAME.get(r["part"], ""), body))[:2000],
            "answer": "正确答案 %s。%s" % (ans, (r["explain"] or "")[:300]),
            "qtype": sqscore.PART_NAME.get(r["part"], ""), "points": r["qtype"] or "",
            "note": "来自社区练习"})
        n += created
        # 排进遗忘曲线：**做错的题第二天就该再见到**，不等下次碰运气抽到
        db.execute("INSERT OR IGNORE INTO review_state(user_id,kind,item_id,stage,next_due) "
                   "VALUES(?,'wrongq',?,0,date('now','localtime',?))",
                   (uid(), wid, "+%d day" % (REVIEW_INTERVALS[0] if REVIEW_INTERVALS else 1)))
    return n


@bp.post("/api/shequ/drill/done")
def drill_done():
    """交一组专项练。判分口径和整卷一模一样，走同一个 sqscore。"""
    db, u = get_db(), uid()
    d = request.get_json(silent=True) or {}
    answers = d.get("answers") or {}
    ids = [int(k) for k in answers]
    if not ids:
        return jsonify({"error": "还没作答"}), 400
    rows = db.execute("SELECT * FROM sq_questions WHERE id IN (%s)"
                      % ",".join("?" * len(ids)), ids).fetchall()
    detail, got = [], 0
    for r in rows:
        chosen = answers.get(str(r["id"]), "")
        ok = sqscore.is_correct(r["part"], chosen, r["answer"])
        got += 1 if ok else 0
        miss, extra = sqscore.miss_and_extra(r["part"], chosen, r["answer"])
        detail.append({"qid": r["id"], "part": r["part"], "chosen": chosen,
                       "correct": 1 if ok else 0, "answer": r["answer"],
                       "stem": r["stem"], "miss": miss, "extra": extra})
        db.execute("INSERT INTO sq_attempts(user_id,qid,chosen,correct,secs,mode) "
                   "VALUES(?,?,?,?,?,'drill')",
                   (u, r["id"], str(chosen)[:16], 1 if ok else 0, 0))
    wrong = [r for r in rows if not sqscore.is_correct(
        r["part"], answers.get(str(r["id"]), ""), r["answer"])]
    n_new = _to_wrongq(db, wrong) if wrong else 0
    db.commit()
    return jsonify({"n": len(rows), "ok": got, "detail": detail,
                    "to_wrongq": len(wrong), "new_wrongq": n_new})


# ---------------------------------------------------------------- 每日测试
# 卷面配额按真题的题型比例折算：真题 40/10/10 → 20 题就是 12/4/4。
# **不让 AI 出题**：社区这条线已经有 6531 道册子原题，而这门考试考的是记没记住
# 具体条文与做法，AI 现编的题在这上面不如原册可靠 —— 项目的老规矩「有真题就
# 不许自己编题」在这儿同样适用，顺带一分钱 AI 都不花。
SQ_DTEST_QUOTA = {"single": 12, "multi": 4, "judge": 4}


@bp.get("/api/shequ/dtest")
def sq_dtest():
    """今天的小测。同一天重复打开给同一份卷子（做到一半退出去还能接着做）。"""
    db, u = get_db(), uid()
    today = date.today().isoformat()
    row = db.execute(
        "SELECT * FROM sq_records WHERE user_id=? AND mode='dtest' "
        "AND substr(created_at,1,10)=? ORDER BY id DESC LIMIT 1", (u, today)).fetchone()
    if row and row["detail"]:
        ids = [x["qid"] for x in json.loads(row["detail"])]
        if ids:
            qs = {q["id"]: q for q in db.execute(
                "SELECT * FROM sq_questions WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
            items = [_pub(qs[i], True) for i in ids if i in qs]
            return jsonify({"date": today, "items": items, "done": row["n_done"] > 0,
                            "record_id": row["id"], "rules": sqscore.RULE_TEXT})

    picked = []
    for part, k in SQ_DTEST_QUOTA.items():
        rows = db.execute(
            "SELECT q.*, "
            "  (SELECT COUNT(*) FROM sq_attempts a WHERE a.qid=q.id AND a.user_id=?) tried, "
            "  (SELECT MIN(a.correct) FROM sq_attempts a WHERE a.qid=q.id AND a.user_id=?) everwrong "
            "FROM sq_questions q JOIN sq_papers p ON p.id=q.paper_id "
            "WHERE %s AND %s AND q.part=? "
            # 「巩固」两个字要对得起：**先出你错过的**，再出没做过的，最后才是做对过的
            "ORDER BY CASE WHEN everwrong=0 THEN 0 WHEN tried=0 THEN 1 ELSE 2 END, RANDOM() "
            "LIMIT ?" % (_BANK, SERVABLE), (u, u, part, k)).fetchall()
        picked += list(rows)
    if not picked:
        return jsonify({"date": today, "items": [], "note": "题库还没灌进来"})
    cur = db.execute(
        "INSERT INTO sq_records(user_id,paper_id,mode,obj_score,obj_full,n_done,n_total,"
        "secs,detail) VALUES(?,NULL,'dtest',0,?,0,?,0,?)",
        (u, float(len(picked)), len(picked),
         json.dumps([{"qid": r["id"]} for r in picked], ensure_ascii=False)))
    db.commit()
    return jsonify({"date": today, "items": [_pub(r, True) for r in picked],
                    "done": False, "record_id": cur.lastrowid, "rules": sqscore.RULE_TEXT})


@bp.post("/api/shequ/dtest")
def sq_dtest_done():
    """交今天的小测。判分口径、错题收集、遗忘曲线全走和别处同一套。"""
    db, u = get_db(), uid()
    d = request.get_json(silent=True) or {}
    rid = int(d.get("record_id") or 0)
    answers = d.get("answers") or {}
    row = db.execute("SELECT * FROM sq_records WHERE id=? AND user_id=?", (rid, u)).fetchone()
    if not row:
        return jsonify({"error": "没有这份小测"}), 404
    ids = [x["qid"] for x in json.loads(row["detail"] or "[]")]
    rows = db.execute("SELECT * FROM sq_questions WHERE id IN (%s)"
                      % ",".join("?" * len(ids)), ids).fetchall() if ids else []
    detail, got = [], 0
    for r in rows:
        chosen = answers.get(str(r["id"]), "")
        ok = sqscore.is_correct(r["part"], chosen, r["answer"])
        got += 1 if ok else 0
        miss, extra = sqscore.miss_and_extra(r["part"], chosen, r["answer"])
        detail.append({"qid": r["id"], "part": r["part"], "chosen": chosen,
                       "correct": 1 if ok else 0, "miss": miss, "extra": extra})
        db.execute("INSERT INTO sq_attempts(user_id,qid,chosen,correct,secs,mode) "
                   "VALUES(?,?,?,?,0,'dtest')", (u, r["id"], str(chosen)[:16], 1 if ok else 0))
    wrong = [r for r in rows if not sqscore.is_correct(
        r["part"], answers.get(str(r["id"]), ""), r["answer"])]
    n_new = _to_wrongq(db, wrong) if wrong else 0
    db.execute("UPDATE sq_records SET obj_score=?, n_done=?, detail=? WHERE id=?",
               (float(got), len(detail), json.dumps(detail, ensure_ascii=False), rid))
    db.commit()
    return jsonify({"n": len(rows), "ok": got, "detail": detail,
                    "to_wrongq": len(wrong), "new_wrongq": n_new})


# ---------------------------------------------------------------- 主观题（40 分）
# 主观题的三档，**摆在一起但不混为一谈**：
#   real     资中两套原卷上的四道题 —— 这是标尺，永远排最前
#   offsite  外省真题里和资中同型的（案例分析 / 公文写作）
#   short    简答论述。资中卷面上**没有这个题型**，只当知识点自测用
# 分档写在这儿而不是前端：JS 里再判一遍迟早和后端说的不是一回事。
SUB_GROUPS = [
    ("real", "资中真题", "两套原卷上的原题。这是标尺 —— 别的题都照着它的形状练。"),
    ("offsite", "外省真题 · 同型", "别的省份考过的案例分析和公文写作，形状和资中一样。"
                                   "满分是照资中口径给的（案例 12 分、公文 15 分），"
                                   "外省原卷没标分值。"),
    ("short", "简答论述 · 资中未考", "外省题库带来的题型，资中两套原卷上没有。"
                                     "不算在 40 分里，当知识点自测用。满分按 10 分记。"),
]


def _sub_group(part, kind):
    if part == "short":
        return "short"
    return "real" if kind in REAL_KINDS else "offsite"


@bp.get("/api/shequ/subjective")
def subjective():
    """主观题清单。**采分点是规则从参考答案拆的**，所以这儿顺带把
       「这道题能不能逐点批改」也算出来告诉前端。"""
    db = get_db()
    rows = db.execute(
        "SELECT q.*, p.year, p.kind, p.name paper_name FROM sq_questions q "
        "JOIN sq_papers p ON p.id=q.paper_id WHERE q.part IN %s "
        "ORDER BY p.year DESC, q.part, q.seq" % sqscore.sql_in(sqscore.SUB_PARTS)).fetchall()
    mine = {r["qid"]: r["c"] for r in db.execute(
        "SELECT qid, COUNT(*) c FROM sq_grade WHERE user_id=? GROUP BY qid", (uid(),))}
    out = []
    for r in rows:
        # 公文的参考答案是整篇范文、拆不出点，改按结构部件给分（见 sqgrade）——
        # 所以它 n_points 是 0 但照样能批改，两件事别用同一个字段表示。
        pts = [] if r["part"] == "gongwen" else sqgrade.split_points(r["answer"], r["score"])
        sk = sqgrade.skeleton_of(r["stem"]) if r["part"] == "case" else None
        out.append({"id": r["id"], "part": r["part"],
                    "part_name": sqscore.PART_NAME.get(r["part"], r["part"]),
                    "group": _sub_group(r["part"], r["kind"]),
                    "year": r["year"], "src": r["paper_name"],
                    "stem": r["stem"], "score": r["score"],
                    "n_points": len(pts),
                    "gradable": bool(pts) or r["part"] == "gongwen",
                    "skeleton": sqgrade.SKELETONS.get(sk) if sk else None,
                    "mine": mine.get(r["id"], 0)})
    return jsonify({"items": out, "skeletons": sqgrade.SKELETONS,
                    "groups": [{"key": k, "name": n, "note": d} for k, n, d in SUB_GROUPS]})


@bp.post("/api/shequ/grade")
def grade():
    """按采分点逐点批改。分数由**我们**按判定算，不采信 AI 报的总分。"""
    db, u = get_db(), uid()
    d = request.get_json(silent=True) or {}
    qid = int(d.get("qid") or 0)
    answer = (d.get("answer") or "").strip()
    if len(answer) < 20:
        return jsonify({"error": "请先写出你的答案（至少 20 个字）"}), 400
    q = db.execute("SELECT * FROM sq_questions WHERE id=?", (qid,)).fetchone()
    if not q or q["part"] not in sqscore.SUB_PARTS:
        return jsonify({"error": "这不是一道主观题"}), 404

    # 公文的参考答案是整篇范文、拆不出点，改按**结构部件**给分；
    # 案例的参考答案本来就是分点写的，规则拆即可。
    if q["part"] == "gongwen":
        pts = sqgrade.gongwen_points(q["score"])
        issues = sqgrade.format_issues(answer, "通知")
    else:
        pts = sqgrade.split_points(q["answer"], q["score"])
        issues = []
    if not pts:
        # 拆不动就说拆不动：给参考答案对照，**不硬凑一个采分点把满分全压上去**
        return jsonify({"gradable": False, "reference": q["answer"],
                        "note": "这道题的参考答案不是分点写的，拆不出采分点，"
                                "只能和参考答案对照着看。"})
    prompt = sqgrade.build_prompt(q["stem"], answer, pts, q["score"])
    if issues:
        # 格式硬伤由**代码**判定（判据都有真题实证），直接告诉 AI 结论，
        # 别让它对同一件事再判一遍 —— 两套判定说不到一块去时，用户不知道信谁。
        prompt += "\n\n【格式检查器已判定的硬伤（请在相应采分点上扣分并指出）】\n" + \
            "\n".join("· %s：%s" % (e["check"], e["why"][:80]) for e in issues)
    msgs = [{"role": "system", "content": sqgrade.SYS},
            {"role": "user", "content": prompt}]
    # 批改用 pro：低频高价值，而且判「沾边」比判对错难
    txt, err = _ai_call_or_error(msgs, tier="pro", temperature=0.2,
                                 max_tokens=2200, json_mode=True, timeout=180)
    if err:
        return jsonify(err[0]), err[1]
    try:
        m = re.search(r"\{.*\}", txt or "", re.S)
        raw = json.loads(m.group()) if m else {}
    except Exception:
        log.warning("社区主观题批改返回不是 JSON：%s", (txt or "")[:200])
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    result = sqgrade.merge(pts, raw.get("points"))
    total = sqgrade.total_of(result)
    advice = str(raw.get("advice") or "")[:300]
    cur = db.execute(
        "INSERT INTO sq_grade(user_id,qid,part,answer,score,full,points,advice) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (u, qid, q["part"], answer, total, q["score"],
         json.dumps(result, ensure_ascii=False), advice))
    db.commit()
    # 跨次统计：这个采分点你漏过几回 —— 一次没答上是手滑，三次没答上是没记住
    miss = [p["name"] for p in result if p["verdict"] == "miss"]
    hab = {}
    for r in db.execute(
            "SELECT points FROM sq_grade WHERE user_id=? AND part='case' ORDER BY id DESC LIMIT 20",
            (u,)):
        try:
            for p in json.loads(r["points"] or "[]"):
                if p.get("verdict") == "miss":
                    hab[p["name"]] = hab.get(p["name"], 0) + 1
        except Exception:
            continue
    return jsonify({"gradable": True, "id": cur.lastrowid, "score": total,
                    "full": q["score"], "points": result, "advice": advice,
                    "reference": q["answer"], "issues": issues,
                    "repeat": [{"name": n, "n": hab[n]} for n in miss if hab.get(n, 0) >= 2]})


@bp.get("/api/shequ/grades")
def grades():
    rows = get_db().execute(
        "SELECT g.id,g.qid,g.part,g.score,g.full,g.advice,g.created_at,q.stem "
        "FROM sq_grade g LEFT JOIN sq_questions q ON q.id=g.qid "
        "WHERE g.user_id=? ORDER BY g.id DESC LIMIT 40", (uid(),)).fetchall()
    return jsonify({"items": [dict(r, part_name=sqscore.PART_NAME.get(r["part"], r["part"]))
                              for r in rows]})


# ---------------------------------------------------------------- 校对裁决台
@bp.get("/api/shequ/doubts")
def doubts():
    """待裁决的存疑题。**三方答案并排给出来**，人点一下就行。"""
    db = get_db()
    rows = db.execute(
        "SELECT q.*, p.name paper_name, p.year FROM sq_questions q "
        "LEFT JOIN sq_papers p ON p.id=q.paper_id "
        "WHERE %s AND q.part IN ('single','multi','judge') AND q.verify<>'ok' "
        "ORDER BY q.paper_id, q.seq" % _REAL).fetchall()
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
        "WHERE %s GROUP BY p.id ORDER BY p.year DESC" % _REAL)]
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
