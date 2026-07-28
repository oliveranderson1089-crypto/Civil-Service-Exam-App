"""巩固测试的历史记录 + 学习计划分析。

**这是个杂物间，别照着它建新模块。** 它是拆分时按 app.py 的旧区段边界切出来的，
而那个边界本身就是错的：
- /api/dtest/records、/api/dtest/record/<id> —— 出题和批改在 mods/dailytest.py
- /api/plan/history、/api/plan/analyze     —— 其余 11 个 plan 路由在 mods/plan.py

真要动这两块功能时，顺手把它们并回 dailytest.py 和 plan.py，这个文件就该没了。
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from core import get_db, log, uid
from mods.ai import _ai_call_or_error

bp = Blueprint("dtest", __name__)


@bp.get("/api/dtest/records")
def dtest_records():
    db = get_db()
    rows = db.execute("SELECT id,date,score,total,created_at FROM dtest_records "
                      "WHERE user_id=? ORDER BY id DESC LIMIT 60", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/dtest/record/<int:rid>")
def dtest_record_detail(rid):
    db = get_db()
    r = db.execute("SELECT * FROM dtest_records WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    try:
        d["detail"] = json.loads(d.pop("detail_json") or "[]")
    except Exception:
        d["detail"] = []
    return jsonify(d)


@bp.get("/api/plan/history")
def plan_history():
    """每天的计划 + 完成情况；今天被重排覆盖掉的旧版本也一并带出来。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    days = {}
    for r in db.execute("SELECT date,seq,title,module,minutes,reason,link,source,done,done_at "
                        "FROM plan_items WHERE user_id=? ORDER BY date DESC, seq, id", (uid(),)):
        d = days.setdefault(r["date"], {"date": r["date"], "live": [], "archived": []})
        d["live"].append({k: r[k] for k in
                          ("seq", "title", "module", "minutes", "reason", "link", "source", "done", "done_at")})
    for r in db.execute("SELECT id,date,created_at,summary,minutes_total,done_n,total,items_json "
                        "FROM plan_log WHERE user_id=? ORDER BY date DESC, id DESC", (uid(),)):
        d = days.setdefault(r["date"], {"date": r["date"], "live": [], "archived": []})
        try:
            items = json.loads(r["items_json"] or "[]")
        except Exception:
            items = []
        d["archived"].append({"id": r["id"], "created_at": r["created_at"], "summary": r["summary"],
                              "minutes_total": r["minutes_total"], "done_n": r["done_n"],
                              "total": r["total"], "items": items})
    out = []
    for date in sorted(days, reverse=True):
        d = days[date]
        live = d["live"]
        out.append({"date": date, "is_today": date == today, "items": live,
                    "done_n": sum(1 for x in live if x["done"]), "total": len(live),
                    "minutes_total": sum(x["minutes"] or 0 for x in live),
                    "minutes_done": sum((x["minutes"] or 0) for x in live if x["done"]),
                    "archived": d["archived"]})
    return jsonify({"days": out, "today": today})


# 计划能覆盖的模块 → 用关键词从任务标题/模块名里认出来，算「最近有没有安排到」
PLAN_MODULES = [
    ("每日复习", ["复习", "遗忘曲线", "背诵", "回忆"]),
    ("错题订正", ["错题", "订正"]),
    ("成语词语", ["成语", "词语", "实词", "选词填空"]),
    ("上位词", ["上位词", "概括词"]),
    ("古诗文", ["古诗", "诗词", "名句", "文学常识"]),
    ("数量关系", ["数量关系", "数学运算", "行程", "工程问题", "浓度", "排列组合", "概率"]),
    ("资料分析", ["资料分析", "速算", "增长率", "比重"]),
    ("判断推理", ["图形推理", "类比推理", "定义判断", "逻辑判断", "判断推理"]),
    ("言语理解", ["言语理解", "逻辑填空", "片段阅读", "语句表达"]),
    ("常识判断", ["常识"]),
    ("政治理论/时政", ["时政", "政治理论", "理论基础", "马原", "毛概", "习思想", "党的创新"]),
    ("申论", ["申论", "归纳概括", "综合分析", "提出对策", "贯彻执行", "大作文", "应用文", "作文", "批改"]),
    ("素材/积累", ["素材", "积累", "概括句", "金句", "习语"]),
]


@bp.post("/api/plan/analyze")
def plan_analyze():
    db = get_db()
    today_d = datetime.now().date()
    since = (today_d - timedelta(days=13)).strftime("%Y-%m-%d")
    rows = db.execute("SELECT date,title,module,minutes,done FROM plan_items "
                      "WHERE user_id=? AND date>=? ORDER BY date", (uid(), since)).fetchall()
    # 把被覆盖的历史版本也纳入「安排过什么」的判断（避免漏掉今天早些版本里的成语等）
    for r in db.execute("SELECT date,items_json FROM plan_log WHERE user_id=? AND date>=?", (uid(), since)):
        try:
            for it in json.loads(r["items_json"] or "[]"):
                rows.append({"date": r["date"], "title": it.get("title", ""),
                             "module": it.get("module", ""), "minutes": it.get("minutes", 0),
                             "done": it.get("done", 0)})
        except Exception:
            log.warning("plan_log.items_json 解析失败，这天不计入分析", exc_info=True)
    if not rows:
        return jsonify({"error": "还没有计划记录，先让规划助手排几天计划再来分析"}), 400

    dates = sorted({r["date"] for r in rows})
    ndays = len(dates)
    cover = {}
    for name, kws in PLAN_MODULES:
        hit = sorted({r["date"] for r in rows
                      if any(k in ((r["title"] or "") + "|" + (r["module"] or "")) for k in kws)})
        cover[name] = {"days": len(hit), "last": hit[-1] if hit else None}
    total_items = len(rows)
    done_items = sum(1 for r in rows if r["done"])

    prof = db.execute("SELECT exam,exam_date,weak,note FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    cov_txt = "\n".join(
        "· %s：%d 天里安排了 %d 天%s" %
        (n, ndays, c["days"], ("，最近一次 %s" % c["last"]) if c["last"] else "，从没安排过")
        for n, c in cover.items())
    per_day = {}
    for r in rows:
        per_day.setdefault(r["date"], [0, 0])
        per_day[r["date"]][0] += 1
        per_day[r["date"]][1] += 1 if r["done"] else 0
    day_txt = "\n".join("· %s：%d 条，完成 %d 条" % (d, per_day[d][0], per_day[d][1])
                        for d in sorted(per_day))

    prompt = (
        "这是一名公考考生最近 %d 天（%s ~ %s）的每日备考计划完成情况，请你做一次进度分析。\n\n"
        "【备考信息】考试：%s；薄弱环节：%s；备注：%s\n"
        "【每天完成】\n%s\n\n"
        "【各模块被安排的频率】（days 越少说明越少练到）\n%s\n\n"
        "共 %d 条任务、完成 %d 条。请分析：\n"
        "1. overview：两三句总体评价（完成率、坚持度）。\n"
        "2. keep：坚持得好、完成率高的方面（数组，各一句）。\n"
        "3. neglected：被冷落或长期没安排的模块，尤其点名那些「从没安排过」或很久没练的（如成语、古诗文等日积累项），"
        "说明长期不练的风险（数组，各一句，带模块名）。\n"
        "4. suggestions：给明天/近几天的具体建议，包含该补上的日积累项和薄弱环节（数组，3~5 条，可执行）。\n"
        '只输出 JSON：{"overview":"","keep":[],"neglected":[],"suggestions":[]}'
        % (ndays, dates[0], dates[-1],
           prof["exam"] if prof else "未填", (prof["weak"] if prof else "") or "未填",
           (prof["note"] if prof else "") or "无", day_txt, cov_txt, total_items, done_items))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考备考教练，善于从学习记录里发现坚持得好的地方和被忽视的短板，"
          "建议具体可执行。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=1400, timeout=120, json_mode=True, tier="pro")
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    return jsonify({
        "overview": (d.get("overview") or "").strip(),
        "keep": [str(x).strip() for x in (d.get("keep") or []) if str(x).strip()],
        "neglected": [str(x).strip() for x in (d.get("neglected") or []) if str(x).strip()],
        "suggestions": [str(x).strip() for x in (d.get("suggestions") or []) if str(x).strip()],
        "days": ndays, "total": total_items, "done": done_items,
        "coverage": [{"name": n, "days": c["days"], "last": c["last"]} for n, c in cover.items()],
    })
