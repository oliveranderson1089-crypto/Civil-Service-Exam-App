"""每日巩固测试：按当天学的内容出小测。

巩固测试的模块配额：行测五个板块都要有，不能只出常识
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import get_db, uid
from mods.ai import _ai_call_or_error
from mods.drill import _dtest_to_wrongq

bp = Blueprint("dailytest", __name__)


DTEST_QUOTA = {
    10: {"言语理解": 3, "判断推理": 2, "资料分析": 1, "数量关系": 1, "常识判断": 3},
    15: {"言语理解": 4, "判断推理": 3, "资料分析": 2, "数量关系": 2, "常识判断": 4},
}

# 图形推理 / 资料分析的程序化出题已抽到 figgen.py（题库·模拟卷也要用，见 gen_quiz.py）
from figgen import _gen_figure_q, _gen_ziliao  # noqa: E402

def _dtest_material(db, today):
    """凑出可考素材，按板块分开给：常识/时政（常识判断）、成语实词上位词（言语理解）、我的错题（出变式题）。"""
    m = {"常识": [], "言语": [], "错题": []}
    cs = db.execute("SELECT board, COALESCE(NULLIF(title,''),topic) t, content FROM changshi_items "
                    "WHERE date=? LIMIT 12", (today,)).fetchall()
    if len(cs) < 4:
        cs = db.execute("SELECT board, COALESCE(NULLIF(title,''),topic) t, content FROM changshi_items "
                        "WHERE date>=date('now','localtime','-3 day') ORDER BY date DESC LIMIT 12").fetchall()
    for r in cs:
        m["常识"].append("【常识·%s】%s：%s" % (r["board"] or "", r["t"] or "", (r["content"] or "")[:110]))
    nw = db.execute("SELECT title, ai_summary FROM news_items "
                    "WHERE date(created_at)>=date('now','localtime','-3 day') ORDER BY id DESC LIMIT 8").fetchall()
    for r in nw:
        m["常识"].append("【时政】%s：%s" % (r["title"] or "", (r["ai_summary"] or "")[:110]))
    for r in db.execute("SELECT title, content FROM theory_items ORDER BY RANDOM() LIMIT 4"):
        m["常识"].append("【理论】%s：%s" % (r["title"] or "", (r["content"] or "")[:90]))
    # 言语：我收录的成语词语 + 常考里的高频成语/实词/上位词
    for r in db.execute("SELECT word, explanation FROM entries WHERE user_id=? ORDER BY RANDOM() LIMIT 8", (uid(),)):
        m["言语"].append("【成语/词语】%s：%s" % (r["word"] or "", (r["explanation"] or "")[:90]))
    for r in db.execute("SELECT board, title, content FROM changkao_items "
                        "WHERE board IN ('成语','实词','上位词') ORDER BY RANDOM() LIMIT 10"):
        m["言语"].append("【常考·%s】%s：%s" % (r["board"] or "", r["title"] or "", (r["content"] or "")[:90]))
    # 错题：按板块给，出「同考点变式题」最有价值
    for r in db.execute("SELECT board, qtype, question, points FROM wrong_questions "
                        "WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid(),)):
        m["错题"].append("【错题·%s】%s｜考点：%s" % (r["board"] or r["qtype"] or "", (r["question"] or "")[:80],
                                              (r["points"] or "")[:50]))
    return m


DTEST_ORDER = ["言语理解", "判断推理", "资料分析", "数量关系", "常识判断"]


def _gen_dtest(db, today, n=10):
    n = 15 if int(n) >= 15 else 10          # 题量只支持 10 / 15
    m = _dtest_material(db, today)
    quota = dict(DTEST_QUOTA[n])
    if not m["常识"] and not m["言语"]:
        return None, "还没积累够可测的内容（常识/时政/成语等），先学一会儿再来测～"

    # 图形推理、资料分析都由代码出：答案是构造出来的，必然正确，材料也一定在
    figs = [_gen_figure_q() for _ in range(1 if quota["判断推理"] >= 2 else 0)]
    quota["判断推理"] -= len(figs)
    zl = _gen_ziliao(quota["资料分析"]) if quota["资料分析"] else []
    quota["资料分析"] = 0

    mat = ""
    for k, title in (("常识", "常识 / 时政 / 理论素材（出常识判断题用）"),
                     ("言语", "成语 / 实词 / 上位词素材（出言语理解题用）"),
                     ("错题", "他最近做错的题（优先出同考点的变式题）")):
        if m[k]:
            mat += "\n【%s】\n" % title + "\n".join("· " + x for x in m[k][:14]) + "\n"

    n_ai = n - len(figs) - len(zl)          # 图形题/资料分析已由程序出好，AI 只出剩下的
    prompt = (
        "给一名四川省考考生出一份「每日巩固小测」的一部分：正好 %d 道**单选题**，"
        "**严格按这个配额出，不要多出、不要凑数**：%s。\n\n"
        "每个板块怎么出：\n"
        "· 常识判断：只能考下面给的常识/时政/理论素材里的考点。\n"
        "· 言语理解：用下面给的成语/实词/上位词，出**逻辑填空**（题干要有完整语境，四个近义词选项）"
        "或**语句衔接/病句**，考的是辨析而不是背释义。\n"
        "· 判断推理：出**纯文字**题型——类比推理 / 定义判断 / 逻辑判断（翻译推理、削弱加强）。"
        "图形推理已经由程序另外出好了，你**不要**出图形推理。\n"
        "· 资料分析：已由程序另外出好（带真表格 / 图表），你**不要**出资料分析题。\n"
        "· 数量关系：出工程 / 行程 / 利润 / 排列组合 / 容斥这类经典计算题。\n"
        "· **计算题必须自查一遍**：把数字设计成能算出**干净答案**的（整数或标准百分数）；"
        "正确选项要明显唯一，不能出现两个选项都「约等于」结果的情况；"
        "如果结果不是整数，题干要问「约为多少」并保证正确项明显最接近；工程/人数这类必须是整数的，题目就设计成整除。\n"
        "· 如果给了「他做错的题」，优先出**同考点的变式题**（换个数据/换个情境，考同一个知识点）。\n\n"
        "每题字段：q 题干；options 四个选项（形如 \"A. …\"）；answer 正确选项字母；"
        "explain 一句话解析（讲清为什么，别只说答案）；module 板块名（必须是 言语理解/判断推理/资料分析/数量关系/常识判断 之一）；"
        "source 这题考什么（如「时政-乡村振兴」「成语-抑扬顿挫」「错题变式-资料分析比重」）。\n"
        '只输出 JSON：{"items":[{"q":"","options":["A. …","B. …","C. …","D. …"],"answer":"A",'
        '"explain":"","module":"","source":""}]}\n'
        % (n_ai, "、".join("%s %d 题" % (k, v) for k, v in quota.items() if v)) + mat)

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是四川省考命题老师。按要求的板块配额出单选题，"
                                       "答案唯一且经得起推敲，计算题的数字必须算得出来。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=6000, timeout=240, json_mode=True)
    if err:
        return None, "AI 出题失败，请稍后再试"
    try:
        items = [x for x in (json.loads(rep).get("items") or [])
                 if x.get("q") and (x.get("options") or []) and x.get("answer")]
    except Exception:
        return None, "AI 返回格式异常，请重试"
    if not items:
        return None, "没能出出题目，请重试"

    for it in items:                                  # 材料数据不干净就退回纯文字题干，别渲染出个空图
        if not _dtest_ok_material(it.get("material")):
            it.pop("material", None)

    seen, uniq = set(), []
    for it in items:                                  # AI 偶尔会重复出同一道题，去掉
        k = (it.get("q") or "").strip()[:40]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    items = uniq[:n_ai] + figs + zl
    items.sort(key=lambda x: DTEST_ORDER.index(x.get("module")) if x.get("module") in DTEST_ORDER else 99)
    db.execute("INSERT OR REPLACE INTO daily_quiz(user_id,date,questions_json) VALUES(?,?,?)",
               (uid(), today, json.dumps(items, ensure_ascii=False)))
    db.commit()
    return items, None


def _dtest_ok_material(m):
    """资料分析的材料必须是干净的结构化数据，数字得真是数字。"""
    if not isinstance(m, dict):
        return False
    t = m.get("type")
    if t == "table":
        rows = m.get("rows") or []
        return bool(m.get("headers")) and rows and all(isinstance(r, list) and r for r in rows)
    if t in ("bar", "line", "pie"):
        labels, series = m.get("labels") or [], m.get("series") or []
        if not labels or not series:
            return False
        for s in series:
            data = s.get("data") or []
            if len(data) != len(labels) or not all(isinstance(v, (int, float)) for v in data):
                return False
        return True
    return False


def _dtest_public(items, exam):
    """服务端判分模式(exam)下，发到前端的题目去掉答案与解析，交卷才由服务端判（板块标签保留）。"""
    if not exam:
        return items
    out = []
    for it in items:
        x = {"q": it.get("q", ""), "options": it.get("options") or [], "module": it.get("module", "")}
        if it.get("material"):
            x["material"] = it["material"]        # 资料分析的表格/图表要看得见
        if it.get("figs"):
            x["figs"] = it["figs"]                # 图形推理的图要看得见
        out.append(x)
    return out


@bp.get("/api/dtest")
def dtest_get():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    exam = request.args.get("exam") in ("1", "true")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    items = json.loads(r["questions_json"]) if r else []
    return jsonify({"date": today, "items": _dtest_public(items, exam), "has": bool(items), "exam": exam})


@bp.post("/api/dtest")
def dtest_gen():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    d = request.get_json(silent=True) or {}
    force = bool(d.get("force"))
    exam = bool(d.get("exam"))
    count = 15 if int(d.get("count") or 10) >= 15 else 10
    if not force:
        r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
        if r:
            return jsonify({"date": today, "items": _dtest_public(json.loads(r["questions_json"]), exam),
                            "cached": True, "exam": exam})
    items, err = _gen_dtest(db, today, count)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"date": today, "items": _dtest_public(items, exam), "exam": exam})


@bp.post("/api/dtest/grade")
def dtest_grade():
    """判分并记录：收到 {answers:{题号:字母}}，对照缓存的正确答案判分、存一条记录并回传结果。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if not r:
        return jsonify({"error": "今天还没有测试"}), 400
    items = json.loads(r["questions_json"])
    ans = (request.get_json(silent=True) or {}).get("answers") or {}
    results, score, detail = [], 0, []
    for i, it in enumerate(items):
        your = (str(ans.get(str(i), ans.get(i, ""))) or "").strip().upper()
        correct_letter = (it.get("answer") or "").strip().upper()
        ok = bool(your) and your == correct_letter
        if ok:
            score += 1
        res = {"your": your, "answer": correct_letter, "correct": ok,
               "explain": it.get("explain", ""), "source": it.get("source", "")}
        results.append(res)
        detail.append({"q": it.get("q", ""), "options": it.get("options") or [], **res})
    db.execute("INSERT INTO dtest_records(user_id,date,score,total,detail_json) VALUES(?,?,?,?,?)",
               (uid(), today, score, len(items), json.dumps(detail, ensure_ascii=False)))
    _dtest_to_wrongq(db, items, results)      # 做错的自动收进错题本
    db.commit()
    return jsonify({"score": score, "total": len(items), "results": results})


@bp.post("/api/dtest/wrong")
def dtest_wrong():
    """背题模式（做一题看一题答案）里选错了，也要进错题本。"""
    d = request.get_json(silent=True) or {}
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.execute("SELECT questions_json FROM daily_quiz WHERE user_id=? AND date=?", (uid(), today)).fetchone()
    if not r:
        return jsonify({"ok": False})
    items = json.loads(r["questions_json"])
    try:
        i = int(d.get("idx"))
        it = items[i]
    except Exception:
        return jsonify({"ok": False})
    your = (str(d.get("choice") or "")).strip().upper()
    ans = (it.get("answer") or "").strip().upper()
    if not your or your == ans:
        return jsonify({"ok": True, "added": 0})
    n = _dtest_to_wrongq(db, [it], [{"your": your, "answer": ans, "correct": False}])
    db.commit()
    return jsonify({"ok": True, "added": n})
