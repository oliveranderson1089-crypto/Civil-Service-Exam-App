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
import sqlite3

from flask import Blueprint, abort, jsonify, request, send_file

from core import UPLOADS, get_db, uid
from mods.review import REVIEW_INTERVALS

bp = Blueprint("realq", __name__)

# 「这道题能不能发给人做」——整个模块只认这一个口径，别处不许再写一份
SERVABLE = ("q.needs_asset=0 AND (q.has_answer=1 OR e.agree=1)")
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
    """哪些题带图（图形推理的图从 docx 里提出来的，见 ingest_figs.py）。
       一次查完，别在渲染每道题时各查一次。"""
    if not qids:
        return {}
    out = {}
    try:
        for f in db.execute(
                "SELECT qid, sha, ext FROM real_figs WHERE qid IN (%s) ORDER BY qid, ord"
                % ",".join("?" * len(qids)), list(qids)):
            out.setdefault(f["qid"], []).append(f["sha"] + f["ext"])
    except sqlite3.OperationalError as e:
        # 只放过「表还没建」这一种（没跑过提图脚本的库）。裸 except 会把 JSON 损坏、
        # 磁盘错误、SQL 写错一起吞掉，表现是「图突然全没了」而日志里一个字都没有。
        if "no such table" not in str(e):
            raise
    return out


def _pub(r, exam=False, figs=None):
    # qtype 优先用规则判出来的；规则判不出的那 44%，用 AI 顺手判的那个补上
    d = {"id": r["id"], "module": r["module"] or "",
         "qtype": (r["qtype"] or "").strip() or (r["ai_qtype"] or "").strip(),
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
    n = max(1, min(140, int(d.get("n") or 10)))
    exam_mode = bool(d.get("exam"))
    items = _pick(get_db(), uid(), mode, n,
                  module=(d.get("module") or "").strip(), qtype=(d.get("qtype") or "").strip(),
                  pkey=(d.get("pkey") or "").strip())
    if not items:
        return jsonify({"error": "这个范围里没有可做的真题（答案存疑的题不会发出来）"}), 404
    # 测试模式下答案和解析都不下发（_pub 会剥掉），交卷时由服务端按库里的答案判分 ——
    # 所以不需要另外把答案暂存一份给自己看。
    figs = _figs_of(get_db(), [r["id"] for r in items])
    return jsonify({"mode": mode, "exam": exam_mode, "n": len(items),
                    "items": [_pub(r, exam_mode, figs) for r in items]})


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
                    "explain": _explain_of(r)})

    added = _to_wrongq(db, [rows[i] for i in wrong_ids if i in rows])
    db.commit()
    return jsonify({"ok": ok_n, "total": len(res), "results": res, "wrong_added": added,
                    "acc": round(ok_n / max(1, len(res)), 2)})


def _to_wrongq(db, rows):
    """做错的真题进错题本。和专项练走同一张表，错题本不分来源。"""
    n = 0
    for r in rows:
        opts = "\n".join(json.loads(r["options"]))
        text = ("【真题】" + r["stem"] + "\n" + opts)[:2000]
        if db.execute("SELECT 1 FROM wrong_questions WHERE user_id=? AND question=?",
                      (uid(), text)).fetchone():
            continue
        ex = _explain_of(r)
        note = ex.get("keypoint") or (ex.get("official") or "")[:200]
        qt = (r["qtype"] or "").strip() or (r["ai_qtype"] or "").strip()
        db.execute("INSERT INTO wrong_questions(user_id,board,question,answer,qtype,points,note) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (uid(), r["module"] or "行测", text,
                    "正确答案 %s。%s" % (r["answer"] or r["ai_answer"] or "", note),
                    qt, qt, "来自真题练习"))
        n += 1
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
