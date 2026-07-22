"""每日巩固测试：按**当天学的内容**出小测。

和专项练的分工是刻意的，别混：
  · 专项练  —— 考点由题型定，题量无限，练的是「这类题怎么做」
  · 巩固测试 —— **考点必须来自今天学的东西**（今天记的常识、看的时政、积累的成语、
                做错的题），练的是「今天学的记住了没」。今天学的常识/时政真题库里
                根本不一定有，所以这里**不从真题库捞题**。

但「形式」要向真题看齐：题干多长、惯用问法怎么写、选词填空几个空 —— 这些从
mods/realprofile.py 的真题画像来。一句话：**考点给今天学的，形式给真题**。

三条硬保证（原先都没有，是这轮补的）：
  1. 板块配额**由组卷器算**，不指望 AI 听话 —— 实测历史数据里 78 道有 23 道
     连 module 都没填，配额形同虚设；
  2. 正确答案的位置**由代码放** —— 实测历史 A 37.2% / D 5.1%，蒙 A 的期望正确率
     快四成，练出来的是蒙题习惯；
  3. 每道题都过**双模型独立核验**，答案不一致的不发 —— 这是全站最后一个裸奔的
     出题入口，专项练那套核验机制就在隔壁。
"""
import json
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import get_db, log, uid
from mods import realprofile
from mods.ai import _ai_call_or_error
from mods.drill import (_assemble_items, _audit_items, _dtest_to_wrongq,
                        _real_examples, _parse_items)

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
    # ⚠️ 理论**先取今天新增的**。原先是全库 ORDER BY RANDOM()，268 条里随便抽 4 条 ——
    #    那就成了「随机常识题」，和「今天学的」没关系，「巩固」两个字白叫了。
    th = db.execute("SELECT title, content FROM theory_items "
                    "WHERE date(created_at)>=? LIMIT 4", (today,)).fetchall()
    if not th:                          # 今天没新增就退回最近的（别按 RANDOM 抽三个月前的）
        th = db.execute("SELECT title, content FROM theory_items "
                        "ORDER BY id DESC LIMIT 4").fetchall()
    for r in th:
        m["常识"].append("【理论】%s：%s" % (r["title"] or "", (r["content"] or "")[:90]))
    # 言语：我收录的成语词语 + 常考里的高频成语/实词/上位词
    # 言语素材同理：**先要今天收录的**，不够再往前找。原先两条都是全库 RANDOM，
    # 「今天巩固」考的却可能是三个月前记的词。
    en = db.execute("SELECT word, explanation FROM entries WHERE user_id=? "
                    "AND date(created_at)>=? ORDER BY id DESC LIMIT 8",
                    (uid(), today)).fetchall()
    if len(en) < 4:
        en = db.execute("SELECT word, explanation FROM entries WHERE user_id=? "
                        "ORDER BY id DESC LIMIT 8", (uid(),)).fetchall()
    for r in en:
        m["言语"].append("【成语/词语】%s：%s" % (r["word"] or "", (r["explanation"] or "")[:90]))
    ck = db.execute("SELECT board, title, content FROM changkao_items "
                    "WHERE board IN ('成语','实词','上位词') AND date(created_at)>=? LIMIT 10",
                    (today,)).fetchall()
    if len(ck) < 4:
        ck = db.execute("SELECT board, title, content FROM changkao_items "
                        "WHERE board IN ('成语','实词','上位词') ORDER BY RANDOM() LIMIT 10").fetchall()
    for r in ck:
        m["言语"].append("【常考·%s】%s：%s" % (r["board"] or "", r["title"] or "", (r["content"] or "")[:90]))
    # 错题：按板块给，出「同考点变式题」最有价值
    for r in db.execute("SELECT board, qtype, question, points FROM wrong_questions "
                        "WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid(),)):
        m["错题"].append("【错题·%s】%s｜考点：%s" % (r["board"] or r["qtype"] or "", (r["question"] or "")[:80],
                                              (r["points"] or "")[:50]))
    return m


DTEST_ORDER = ["言语理解", "判断推理", "资料分析", "数量关系", "常识判断"]


_PROF_QTYPE = {"言语理解": ("言语理解与表达", "语境分析"),
               "判断推理": ("判断推理", "定义判断"),
               "常识判断": ("常识判断", "人文常识"),
               "数量关系": ("数量关系", "工程")}

_DTEST_SPEC = {
    "常识判断": "只能考给定素材里的考点，一道题一个考点。四个选项可以是关于同一事物的四种说法。",
    "言语理解": "用给定的成语/实词出**选词填空**：题干要有完整语境（把上下文的呼应关系写足），"
                "四个选项是近义词/易混词，放在一起才需要辨析。考辨析，不是考背释义。",
    "判断推理": "出**纯文字**题型：类比推理 / 定义判断 / 翻译推理 / 削弱加强。"
                "图形推理已由程序另外出好，**不要**出图形推理。",
    "数量关系": "出工程 / 行程 / 利润 / 排列组合 / 容斥这类经典计算题。"
                "**数字必须自查**：设计成能算出干净答案的（整数或标准百分数）；"
                "正确项明显唯一，不能两个选项都「约等于」结果；"
                "结果不是整数就问「约为多少」并保证正确项明显最接近。",
}


def _dtest_quota(db, today, n):
    """今天这份小测每个板块出几道。**由代码算，不写进提示词让 AI 自觉**。

    按「C 方案」：今天新增的素材打底（DTEST_QUOTA），再给**今天已经勾完成的任务**
    对应的板块加权 —— 今天真做完了资料分析，就该多考它两道。
    最多挪 2 道、且每个板块至少留 1 道：巩固测试的意义是全面回顾，不是刷成偏科。
    """
    quota = dict(DTEST_QUOTA[n])
    try:
        done = [r["module"] for r in db.execute(
            "SELECT module FROM plan_items WHERE user_id=? AND date=? AND done=1",
            (uid(), today))]
    except sqlite3.Error:
        done = []                       # 还没有任务清单表/数据
    for mod in [x for x in done if x in quota][:2]:
        src = max((k for k in quota if k != mod and quota[k] > 1),
                  key=lambda k: quota[k], default=None)
        if src:                         # 从当前最多的那个板块挪一道过来，总数不变
            quota[src] -= 1
            quota[mod] += 1
    return quota


def _dtest_one(module, k, mat, prof, examples):
    """出**一个板块**的 k 道题。配额由调用方保证，这里只管这一个板块。

    考点来自 mat（今天学的），形式来自 prof（真题画像）+ examples（同题型真题）——
    这就是「考点给今天学的，形式给真题」那句话的落地处。

    **多要一半再截断**：双模核验会刷掉一部分（实测要 10 道只出 8 道，
    数量关系那种计算题最容易被刷），按配额精确请求的话每天都缺题。
    """
    want = k + max(1, (k + 1) // 2)
    prompt = (
        "给一名四川省考考生出 %d 道**%s**的单选题，用来巩固他**今天学的内容**。\n\n"
        "【这个板块怎么出】%s\n\n"
        "【每道题】\n"
        "· q：题干%s\n"
        "· right：**正确选项的内容**（只写内容，不要加 A/B/C/D，也不要提任何字母）\n"
        "· wrong：三个干扰项的内容，数组（同样不带字母）\n"
        "· why_right / why_wrong：为什么对 / 三个各自错在哪（数组，和 wrong 一一对应，不出现字母）\n"
        "· source：**这题对应下面素材里的哪一条**，照抄那条素材的标题\n\n"
        "【硬要求】\n"
        "1. **考点必须来自下面给的素材**。下面还会给几道真题当范例，那是让你学"
        "**题目长什么样**（篇幅、设问措辞、干扰项怎么造），"
        "**绝不能考真题里的内容** —— 考点只能从素材里挑。\n"
        "2. 答案唯一且经得起推敲，四个选项互不相同、长度相当。\n"
        "3. **通篇不要出现 A/B/C/D**：选项排第几位由我来定。\n\n"
        '只输出 JSON：{"items":[{"q":"","right":"","wrong":["","",""],'
        '"why_right":"","why_wrong":["","",""],"source":""}]}'
        % (want, module, _DTEST_SPEC.get(module, "按这个板块的常规考法出"),
           realprofile.q_hint(prof)))
    prompt += realprofile.prompt_lines(prof)
    if examples:
        prompt += ("\n\n【同题型真题，**只学形式不学内容**】\n"
                   + "\n\n".join("· %s" % e["q"][:400] for e in examples)
                   + "\n\n要学的是：题干体量、设问措辞、干扰项怎么造。"
                     "**考点必须换成上面素材里的**，绝不能出这几道真题考的东西。")
    prompt += "\n\n【今天学的素材 —— 考点只能从这里挑】\n" + mat

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是四川省考命题老师。答案唯一、干扰项讲究。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=4000, timeout=180, json_mode=True)
    if err:
        log.warning("每日测试 %s 出题失败：%s", module, err)
        return []
    # 位置分配和题数**已经解耦**（drill._slot_letters 每发完一副 ABCD 重洗一副），
    # 所以这里不用再把 want 传进去 —— 早先按题数铺固定表时，每个板块才 1~4 道，
    # want=1 会让整块的答案全是 A。
    ready, _st = _assemble_items(_parse_items(rep, "每日测试 " + module), prof)
    if not ready:
        return []
    # ★ 双模型核验：这是全站最后一个裸奔的出题入口。答案不一致的**直接丢** ——
    #   和专项练不同，每日测试没有题库可以留存回查，存疑的题留着没用，只会误人。
    board, qtype = _PROF_QTYPE.get(module, (module, ""))
    out = []
    for (it, q, ans, opts), au in zip(ready, _audit_items(ready, board, qtype), strict=True):
        if not au or au[0] != ans or au[1] != "ok":
            continue
        # ⚠️ 这里**先不定答案位置**，把模型交的原始 right/wrong/why_* 原样带回去。
        #    位置留到 _gen_dtest 里**对整份卷子统一放** —— 每个板块才 2~3 道，
        #    各放各的根本均衡不了（实测一份卷子出过 B 53% / D 0%）。
        #    核验已经在这一步做完了，重新排位置不影响它的结论（它认的是选项内容）。
        out.append(dict(it, module=module))
        if len(out) >= k:               # 够配额就停，多出来的不要
            break
    return out


def _gen_dtest(db, today, n=10):
    n = 15 if int(n) >= 15 else 10          # 题量只支持 10 / 15
    m = _dtest_material(db, today)
    quota = _dtest_quota(db, today, n)
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

    # ★ **每个板块单独一次调用**，配额由这里的循环保证，不写进提示词让 AI 自觉。
    #   并发跑：五个板块串行做要好几分钟，而前端的 fetch 没有超时。
    jobs = [(mod, cnt) for mod, cnt in quota.items() if cnt > 0]

    def one(job):
        mod, cnt = job
        board, qtype = _PROF_QTYPE.get(mod, (mod, ""))
        prof = realprofile.get(db, board, qtype) if qtype else None
        ex = _real_examples(db, board, qtype, n=2) if qtype else []
        return _dtest_one(mod, cnt, mat, prof, ex)

    ai_items = []
    if jobs:
        with ThreadPoolExecutor(max_workers=min(5, len(jobs))) as pool:
            ai_items = [x for batch in pool.map(one, jobs) for x in batch]

    seen, uniq = set(), []
    for it in ai_items:                               # AI 偶尔会重复出同一道题，去掉
        key = (it.get("q") or "").strip()[:40]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # ★ 答案位置**对整份卷子统一放**（prof 传 None：篇幅护栏各板块已经过了，别再卡一次）。
    #   分板块各放各的时每块才 2~3 道，均衡不了 —— 实测出过一份 B 53% / D 0% 的卷子。
    random.shuffle(uniq)                              # 先打散板块，免得同一块的题挤在相邻位置
    ai_final = []
    for it, q, ans, opts in _assemble_items(uniq, None)[0]:
        ai_final.append({"q": q, "options": opts, "answer": ans,
                         "explain": it.get("explain") or "", "module": it.get("module") or "",
                         "source": (it.get("source") or "").strip()[:60]})
    items = ai_final + figs + zl
    if not items:
        return None, "出题没成功（可能是 AI 接口不稳），过一会儿再试"
    for it in items:                                  # 材料数据不干净就退回纯文字题干，别渲染出个空图
        if it.get("material") is not None and not _dtest_ok_material(it.get("material")):
            it.pop("material", None)
    items.sort(key=lambda x: DTEST_ORDER.index(x.get("module"))
               if x.get("module") in DTEST_ORDER else 99)
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
