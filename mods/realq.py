"""真题练习：按题型刷 / 按卷子刷 / 智能刷（反复练）。

和「专项练」（drill.py）最大的不同是**这里的题是死的**——就那么几千道，考完就不会再有新的。
所以重点不是「出题」，而是**怎么安排你把同一道题刷第二遍第三遍**：

  · 每次作答都单独留一条 real_attempts，**不覆盖**上一次 —— 第二遍做错了要看得出来；
  · 排程复用全站那套遗忘曲线（review_state，kind='realq'），
    和成语/错题/素材走同一个「今日复习」入口，不另起炉灶；
  · 智能刷的顺序是：**错过且到期 > 没做过 > 做对了但到期该回顾**。
    随机抽的话，刷三遍等于把第一遍重刷三次，最该练的题反而遇不上。

只发「答案靠得住」的题：原卷带答案的，或者 AI 出解析且过了双模型核验的（agree=1）。
答案存疑的留在库里可以回查，但绝不发给人做。
"""
import json
import os
import re

from flask import Blueprint, abort, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods import realref, timing
from mods.review import REVIEW_INTERVALS
from mods.wrongq import wq_upsert

bp = Blueprint("realq", __name__)

# 「这道题能不能发给人做」——**全站只有 mods/realref.py 一份口径**，这儿只是取个短名字。
# 别在任何地方重新写一遍字符串：drill.py 出题、audit_qtype.py 体检都吃同一个判定，
# 各写一份的话改口径必须同步三处，漏一处的表现是审计数字和线上实际发的题对不上。
SERVABLE = realref.servable("q", "e")
_JOIN = ("FROM real_questions q LEFT JOIN real_explains e ON e.qid=q.id")


def _explain_of(r):
    """解析优先用原卷的（最权威），没有再用 AI 的结构化解析。

    两种形态都返回，前端按有哪个排哪个：
      official —— 一整段文字（原卷解析，内容权威但排版是 PDF 拉下来的）
      steps    —— 结构化四段（关键/步骤/错项/举一反三），手机上好读得多
    """
    out = {"official": (r["explain"] or "").strip()}
    if r["keypoint"] or r["steps"]:
        out.update(keypoint=r["keypoint"] or "",
                   steps=json.loads(r["steps"] or "[]"),
                   wrong=json.loads(r["wrong"] or "{}"),
                   tip=r["tip"] or "",
                   by="ai" if r["src"] == "ai" else "ai_on_official")
    return out


def _figs_of(db, qids):
    """哪些题带图。实现在 mods/realref.py —— 专项练的真题题源要用同一份，
       各写一份的话「改了这边没改那边」不会报错，只会静默发出错图。"""
    return realref.figs_of(db, qids)


def _pub(r, exam=False, figs=None):
    # qtype 优先用规则判出来的；规则判不出的那 44%，用 AI 顺手判的那个补上
    qt = (r["qtype"] or "").strip() or (r["ai_qtype"] or "").strip()
    d = {"id": r["id"], "module": r["module"] or "",
         "qtype": qt,
         # 这道题该给多少秒（按题型，见 mods/timing.py）。整卷模考的总时长
         # 也是这些数加出来的，所以口径必须是同一份。
         "sec": timing.limit_of(r["module"] or "", qt),
         # 资料分析的题干本身没信息量（「2019 年该省 GDP 同比增长约：」），
         # 真正的题在材料里 —— 材料和表格图都得给，不然这道题没法做
         "material": (r["material"] or "") if "material" in r.keys() else "",
         "stem": r["stem"], "options": json.loads(r["options"]),
         "figs": (figs or {}).get(r["id"], []),
         "sources": json.loads(r["sources"] or "[]")[:3]}
    if not exam:
        d["answer"] = r["answer"] or r["ai_answer"] or ""
        d["explain"] = _explain_of(r)
    return d


@bp.get("/api/real/overview")
def real_overview():
    """真题库有什么、我练到哪了。"""
    db = get_db()
    u = uid()
    tot = db.execute("SELECT COUNT(*) c %s WHERE %s" % (_JOIN, SERVABLE)).fetchone()["c"]
    mine = db.execute(
        "SELECT COUNT(DISTINCT qid) c, SUM(correct) ok, COUNT(*) n "
        "FROM real_attempts WHERE user_id=?", (u,)).fetchone()
    mods = [dict(r) for r in db.execute(
        "SELECT q.module, COUNT(*) c, "
        "  (SELECT COUNT(DISTINCT a.qid) FROM real_attempts a JOIN real_questions q2 ON q2.id=a.qid "
        "   WHERE a.user_id=? AND q2.module=q.module) done "
        "%s WHERE %s GROUP BY q.module ORDER BY c DESC" % (_JOIN, SERVABLE), (u,))]
    types = [dict(r) for r in db.execute(
        # GROUP BY 里不能写别名 qtype —— 和 q.qtype / e.qtype 撞名，SQLite 直接报 ambiguous
        "SELECT q.module, COALESCE(NULLIF(q.qtype,''), e.qtype, '') qtype, COUNT(*) c "
        "%s WHERE %s AND COALESCE(NULLIF(q.qtype,''), e.qtype, '')<>'' "
        "GROUP BY q.module, COALESCE(NULLIF(q.qtype,''), e.qtype, '') "
        # 按题量降序，不按模块名 —— 按模块名排的话空模块（''）会顶到最前面，
        # 一屏全是只有一两道题的零碎题型，真正能刷的大类反而看不见
        "ORDER BY c DESC" % (_JOIN, SERVABLE))]
    due = db.execute("SELECT COUNT(*) c FROM review_state WHERE user_id=? AND kind='realq' "
                     "AND next_due<=date('now','localtime')", (u,)).fetchone()["c"]
    return jsonify({"total": tot, "done": mine["c"] or 0, "attempts": mine["n"] or 0,
                    "correct": mine["ok"] or 0, "due": due,
                    "modules": mods, "types": types})


@bp.get("/api/real/papers")
def real_papers():
    """按卷子刷：哪些年、哪些卷种，各有多少道能做的，我做过多少。"""
    db = get_db()
    # 按 pkey（规范化文件名 + 卷别令牌）分组，**不能按 (exam,year,paper,season) 分**：
    # 2020 四川的 0725 和 1206 是两场不同的考试，这四项却完全一样，
    # 按它们分会把两场考试合并成一份 197 道的「卷子」。
    rows = db.execute(
        "SELECT p.pkey, MIN(p.exam) exam, MIN(p.year) year, MIN(p.paper) paper, "
        "  MIN(p.season) season, MIN(p.name) name, COUNT(DISTINCT q.id) c, "
        "  COUNT(DISTINCT CASE WHEN a.qid IS NOT NULL THEN q.id END) done "
        "FROM real_papers p JOIN real_raw rr ON rr.paper_id=p.id "
        "JOIN real_questions q ON q.id=rr.qid "
        "LEFT JOIN real_explains e ON e.qid=q.id "
        "LEFT JOIN real_attempts a ON a.qid=q.id AND a.user_id=? "
        "WHERE p.role='q' AND p.pkey IS NOT NULL AND %s "
        "GROUP BY p.pkey HAVING c>=10 ORDER BY year DESC, exam, paper" % SERVABLE,
        (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


def _pick(db, u, mode, n, module="", qtype="", pkey=""):
    """挑题。**顺序就是这个模块的价值所在**，不是随便抽。"""
    where, wargs = [SERVABLE], []
    if module:
        where.append("q.module=?")
        wargs.append(module)
    if qtype:
        where.append("COALESCE(NULLIF(q.qtype,''), e.qtype, '')=?")
        wargs.append(qtype)

    if mode == "paper":
        # 整卷模考要**按卷面题号出**。原先没有任何 ORDER BY，返回的是 real_questions.id
        # 顺序 —— 那是去重时的插入次序，副省级/地市级共题的那些会拿到先处理那份卷子的 id，
        # 题序和原卷对不上（实测第 1 题直接不在开头）。所以这里连上 real_raw 取 seq 排序。
        # 卷子用 pkey 认，不用 (exam,year,paper,season)：2020 四川 0725 和 1206 是两场
        # 不同的考试，那四项却完全一样，会把两场合并成一份 195 道的「卷子」。
        sql = ("SELECT q.*, e.answer AS ai_answer, e.qtype AS ai_qtype, e.keypoint, e.steps, "
               "  e.wrong, e.tip, e.src, MIN(rr.seq) seq "
               "FROM real_questions q LEFT JOIN real_explains e ON e.qid=q.id "
               "JOIN real_raw rr ON rr.qid=q.id "
               "JOIN real_papers p ON p.id=rr.paper_id AND p.role='q' AND p.pkey=? "
               "WHERE " + " AND ".join(where) + " GROUP BY q.id ORDER BY seq")
        rows = [dict(r) for r in db.execute(sql, [pkey] + wargs)]
        return rows[:n] if n else rows

    # 每道题带上「我做过几次、最近一次对不对、复习什么时候到期」。
    # 三个 u 是给上面三个子查询的，必须排在 where 的参数**之前** —— 顺序错了 SQLite
    # 不报错，只会静默把参数绑到别的列上。
    sql = (
        "SELECT q.*, e.answer AS ai_answer, e.qtype AS ai_qtype, e.keypoint, e.steps, "
        "  e.wrong, e.tip, e.src, "
        "  (SELECT COUNT(*) FROM real_attempts a WHERE a.qid=q.id AND a.user_id=?) tries, "
        "  (SELECT a.correct FROM real_attempts a WHERE a.qid=q.id AND a.user_id=? "
        "   ORDER BY a.id DESC LIMIT 1) last_ok, "
        "  (SELECT s.next_due FROM review_state s WHERE s.kind='realq' AND s.item_id=q.id "
        "   AND s.user_id=?) due "
        "%s WHERE %s" % (_JOIN, " AND ".join(where)))
    rows = [dict(r) for r in db.execute(sql, [u, u, u] + wargs)]

    today = db.execute("SELECT date('now','localtime')").fetchone()[0]

    def rank(r):
        # 0 错过且到期 → 1 没做过 → 2 做对但到期 → 3 其余（做对且没到期，最不该占名额）
        if r["tries"] and not r["last_ok"] and (not r["due"] or r["due"] <= today):
            return (0, -r["tries"])
        if not r["tries"]:
            return (1, r["id"])
        if r["due"] and r["due"] <= today:
            return (2, r["due"])
        return (3, r["id"])

    rows.sort(key=rank)
    return rows[:n]


@bp.post("/api/real/quiz")
def real_quiz():
    d = request.get_json(silent=True) or {}
    mode = d.get("mode") if d.get("mode") in ("smart", "type", "paper") else "smart"
    # 题量由前端选（5/10/20/30/50，和专项练一个交互）。整卷模考传 140 = 整份卷子。
    # 上限仍卡在 140：再多也不是一次能做完的量，而且 _pick 要全表排序。
    try:
        n = max(1, min(140, int(d.get("n") or 10)))
    except (TypeError, ValueError):
        n = 10
    exam_mode = bool(d.get("exam"))
    items = _pick(get_db(), uid(), mode, n,
                  module=(d.get("module") or "").strip(), qtype=(d.get("qtype") or "").strip(),
                  pkey=(d.get("pkey") or "").strip())
    if not items:
        return jsonify({"error": "这个范围里没有可做的真题（答案存疑的题不会发出来）"}), 404
    # 测试模式下答案和解析都不下发（_pub 会剥掉），交卷时由服务端按库里的答案判分 ——
    # 所以不需要另外把答案暂存一份给自己看。
    figs = _figs_of(get_db(), [r["id"] for r in items])
    pub = [_pub(r, exam_mode, figs) for r in items]
    return jsonify({"mode": mode, "exam": exam_mode, "n": len(pub), "items": pub,
                    # 整卷模考的总时长 = 各题建议用时之和（130 道的行测卷算出来
                    # 一小时五十几分，和真实的 120 分钟对得上）。不写死 120 分钟：
                    # 只挑了一个模块的 40 题卷会白给一小时，倒计时就成了摆设。
                    "total_sec": sum(x["sec"] for x in pub)})


@bp.post("/api/real/done")
def real_done():
    """交卷：判分 + **每次作答独立留痕** + 排进遗忘曲线 + 错题进错题本。"""
    d = request.get_json(silent=True) or {}
    answers = d.get("answers") or {}
    secs = d.get("seconds") or {}
    # 题号是客户端传的，必须先过一遍：直接 int() 的话，一个非数字键就是 500
    qids = [int(k) for k in answers if str(k).lstrip("-").isdigit()]
    if not answers or not qids:
        return jsonify({"error": "没有作答"}), 400
    db, u = get_db(), uid()
    today = db.execute("SELECT date('now','localtime')").fetchone()[0]
    # **这里也要过 SERVABLE**：出题时挡掉的存疑题/需图题，不能从交卷这个口子溜进来
    # 记账、排进遗忘曲线、还把一个系统自己判定不可信的「正确答案」写进错题本。
    rows = {r["id"]: r for r in db.execute(
        "SELECT q.*, e.answer AS ai_answer, e.qtype AS ai_qtype, e.keypoint, e.steps, "
        "  e.wrong, e.tip, e.src "
        "%s WHERE %s AND q.id IN (%s)" % (_JOIN, SERVABLE, ",".join("?" * len(qids))),
        qids)}

    figs = _figs_of(db, list(rows))
    res, ok_n, wrong_ids = [], 0, []
    for qid_s, choice in answers.items():
        if not str(qid_s).lstrip("-").isdigit():
            continue
        r = rows.get(int(qid_s))
        if not r:
            continue
        right = (r["answer"] or r["ai_answer"] or "").strip().upper()[:1]
        your = (choice or "").strip().upper()[:1]
        ok = bool(your) and your == right
        ok_n += ok
        db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct,seconds) "
                   "VALUES(?,?,?,?,?)", (u, r["id"], your, 1 if ok else 0,
                                         float(secs.get(qid_s) or 0)))
        # 排进遗忘曲线：做对了往后推一档，做错了打回第 0 档、明天就得再见
        st = db.execute("SELECT stage FROM review_state WHERE user_id=? AND kind='realq' "
                        "AND item_id=?", (u, r["id"])).fetchone()
        stage = (st["stage"] if st else 0)
        stage = min(stage + 1, len(REVIEW_INTERVALS) - 1) if ok else 0
        db.execute(
            "INSERT INTO review_state(user_id,kind,item_id,stage,next_due,last_done) "
            "VALUES(?,'realq',?,?,date('now','localtime','+%d day'),?) "
            "ON CONFLICT(user_id,kind,item_id) DO UPDATE SET stage=excluded.stage, "
            "next_due=excluded.next_due, last_done=excluded.last_done"
            % REVIEW_INTERVALS[stage], (u, r["id"], stage, today))
        if not ok:
            wrong_ids.append(r["id"])
        res.append({"id": r["id"], "your": your, "answer": right, "correct": ok,
                    # 图要带上：模考交卷后的逐题回顾里，图形推理题没有图就只剩一句
                    # 「选择最合适的一个填入问号处」，正是这类题最需要对着图看解析
                    "figs": figs.get(r["id"], []),
                    # 材料也要带：资料分析做错的题，回顾时没有材料就只剩
                    # 「2019 年该省 GDP 同比增长约：」和四个数字，解析根本看不懂
                    "material": (r["material"] or "") if "material" in r.keys() else "",
                    "explain": _explain_of(r)})

    added = _to_wrongq(db, [rows[i] for i in wrong_ids if i in rows])
    rid = _save_record(db, u, d, rows, res, secs)
    db.commit()
    return jsonify({"ok": ok_n, "total": len(res), "results": res, "wrong_added": added,
                    "rid": rid, "acc": round(ok_n / max(1, len(res)), 2)})


REC_KEEP = 60          # 每人保留多少条回看记录（列表也只显示这么多）


def _save_record(db, u, d, rows, res, secs):
    """整组留一条记录，和专项练的 drill_records 一个形状。

    real_attempts 是逐题流水，回看不了「那一组」：智能刷抽的是哪十道、模考里
    哪几道超时，只有整组存下来才看得见。

    **只存瘦身后的作答，不存材料和解析**：那两样才是大头 —— 130 道的整卷里，
    资料分析的材料按题存会把同一篇材料抄 5 遍，加上原卷解析，一条记录就能到
    几百 KB 甚至 1MB，一天一套、永不清理，库很快就被这个功能撑起来。
    材料/图/解析都能按 qid 从真题库现查（见 real_record），回看照样是全的。
    """
    items = []
    for r in res:
        q = rows.get(r["id"])
        if not q:
            continue
        qt = (q["qtype"] or "").strip() or (q["ai_qtype"] or "").strip()
        items.append({"id": r["id"], "module": q["module"] or "", "qtype": qt,
                      "answer": r["answer"], "your": r["your"], "correct": r["correct"],
                      "seconds": float(secs.get(str(r["id"])) or secs.get(r["id"]) or 0),
                      "sec": timing.limit_of(q["module"] or "", qt)})
    mode = d.get("mode") if d.get("mode") in ("smart", "type", "paper") else "smart"
    scope = (d.get("scope") or d.get("qtype") or "").strip() or {
        "smart": "智能刷", "type": "按题型", "paper": "整卷模考"}[mode]
    cur = db.execute(
        "INSERT INTO real_records(user_id,mode,scope,exam,total,correct,seconds,items,answers) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (u, mode, scope[:60], 1 if d.get("exam") else 0, len(items),
         sum(1 for x in items if x["correct"]), sum(x["seconds"] for x in items),
         json.dumps(items, ensure_ascii=False), ""))
    # 只留最近 REC_KEEP 条：列表本来也只显示这么多，再往前翻不如看「薄弱题型」统计。
    # 不清的话这张表只增不减 —— 一天一组，一年就是三百多条谁也不会回看的记录。
    db.execute("DELETE FROM real_records WHERE user_id=? AND id NOT IN "
               "(SELECT id FROM real_records WHERE user_id=? ORDER BY id DESC LIMIT ?)",
               (u, u, REC_KEEP))
    return cur.lastrowid


@bp.get("/api/real/records")
def real_records():
    """做题记录列表。60 条封顶 —— 再往前翻不如去看「薄弱题型」统计。"""
    rows = get_db().execute(
        "SELECT id,mode,scope,exam,total,correct,seconds,created_at FROM real_records "
        "WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid(),)).fetchall()
    name = {"smart": "智能刷", "type": "按题型", "paper": "整卷模考"}
    return jsonify({"items": [dict(r, mode_name=name.get(r["mode"], r["mode"] or ""))
                              for r in rows]})


@bp.get("/api/real/record/<int:rid>")
def real_record(rid):
    """回看某一组：作答从记录里取，题面/材料/图/解析**现查真题库**。

    存的时候只留了作答（见 _save_record 为什么不存题面）。回看时按 qid 一次性
    把题捞回来补上 —— 一条 IN 查询的事，换来的是记录表不再按 MB 涨。
    """
    db = get_db()
    r = db.execute("SELECT * FROM real_records WHERE id=? AND user_id=?",
                   (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    d = dict(r)
    items = json.loads(d["items"] or "[]")
    qids = [x["id"] for x in items if x.get("id")]
    qs, figs = {}, {}
    if qids:
        qs = {q["id"]: q for q in db.execute(
            "SELECT q.*, e.answer AS ai_answer, e.qtype AS ai_qtype, e.keypoint, e.steps, "
            "  e.wrong, e.tip, e.src FROM real_questions q "
            "LEFT JOIN real_explains e ON e.qid=q.id WHERE q.id IN (%s)"
            % ",".join("?" * len(qids)), qids)}
        figs = _figs_of(db, qids)
    for x in items:
        q = qs.get(x.get("id"))
        if not q:
            # 题被重导时换了 id：作答还在，题面没了。说清楚，别显示成一道空题。
            x["stem"] = x.get("stem") or "（这道题已不在题库里，只剩作答记录）"
            x.setdefault("options", [])
            continue
        x["stem"] = q["stem"]
        x["options"] = json.loads(q["options"] or "[]")
        x["material"] = (q["material"] or "") if "material" in q.keys() else ""
        x["figs"] = figs.get(q["id"], [])
        x["explain"] = _explain_of(q)
        if not x.get("qtype"):
            x["qtype"] = (q["qtype"] or "").strip() or (q["ai_qtype"] or "").strip()
    d["items"] = items
    d.pop("answers", None)      # 逐题结果已经并进 items 了，别再发一份重的
    return jsonify(d)


@bp.delete("/api/real/record/<int:rid>")
def real_record_del(rid):
    db = get_db()
    if not db.execute("SELECT 1 FROM real_records WHERE id=? AND user_id=?",
                      (rid, uid())).fetchone():
        return jsonify({"error": "记录不存在"}), 404
    # 只删这条回看记录。real_attempts 的流水**不动** —— 那是进度和遗忘曲线的依据，
    # 跟着删的话「这题做过没」会倒退，智能刷又把做过的题当新题推给你。
    db.execute("DELETE FROM real_records WHERE id=? AND user_id=?", (rid, uid()))
    db.commit()
    return jsonify({"ok": True})


def _to_wrongq(db, rows):
    """做错的真题进错题本。和专项练走同一张表、同一个 upsert。

    身份用 **真题 id**（src_kind='realq'）：同一道题在这儿做错、在专项练的真题模式
    也做错，收的是同一条；做题界面据此认出「这题已经在本子里」，就地能改能删。
    """
    n = 0
    for r in rows:
        opts = "\n".join(json.loads(r["options"]))
        text = ("【真题】" + r["stem"] + "\n" + opts)[:2000]
        ex = _explain_of(r)
        note = ex.get("keypoint") or (ex.get("official") or "")[:200]
        qt = (r["qtype"] or "").strip() or (r["ai_qtype"] or "").strip()
        _, created = wq_upsert(db, uid(), "realq", str(r["id"]), {
            "board": r["module"] or "行测", "question": text,
            "answer": "正确答案 %s。%s" % (r["answer"] or r["ai_answer"] or "", note),
            "qtype": qt, "points": qt, "note": "来自真题练习"})
        n += created
    return n


@bp.get("/api/real/fig/<name>")
def real_fig(name):
    """题目里的图。文件名是内容 sha256（提图时按内容存的），所以不用带鉴权参数；
       但仍要**挡住路径穿越** —— 名字里只允许十六进制和一个扩展名。
       白名单里没有 emf/wmf：浏览器渲染不了这两种 Windows 图元格式，
       放行只会显示成裂图；提图阶段已经把它们转成 png 了。"""
    if not re.fullmatch(r"[0-9a-f]{8,64}\.(png|jpe?g|gif|bmp)", name or ""):
        abort(404)
    p = os.path.join(UPLOADS, "realfig", name)
    if not os.path.exists(p):
        abort(404)
    return send_file(p, max_age=86400)


@bp.get("/api/real/stats")
def real_stats():
    """我的真题进度：整体、按模块、按题型的正确率，弱的排前面。"""
    db, u = get_db(), uid()
    by = [dict(r) for r in db.execute(
        # 题型要和出题、概览一样回退到 e.qtype —— 规则法只判出 56%，
        # 不回退的话做过的题里有一多半会挤进 qtype='' 这一个桶，「薄弱题型」就没意义了
        "SELECT q.module, COALESCE(NULLIF(q.qtype,''), e.qtype, '') qtype, "
        "  COUNT(*) n, SUM(a.correct) ok, AVG(a.seconds) sec "
        "FROM real_attempts a JOIN real_questions q ON q.id=a.qid "
        "LEFT JOIN real_explains e ON e.qid=q.id "
        "WHERE a.user_id=? "
        "GROUP BY q.module, COALESCE(NULLIF(q.qtype,''), e.qtype, '') HAVING n>=3", (u,))]
    for x in by:
        x["acc"] = round(100.0 * (x["ok"] or 0) / x["n"])
        x["sec"] = round(x["sec"] or 0)
    by.sort(key=lambda x: x["acc"])
    return jsonify({"weak": by[:12], "all": by})
