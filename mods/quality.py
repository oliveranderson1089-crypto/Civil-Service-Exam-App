"""内容质检：题库到底能不能用。

P0 的产出健康管「今天有没有新东西」，这块管「已有的东西对不对」——两件事。
真题库是全站的标尺（出题、每日测试、找点都拿它对标），标尺歪了，
下游全跟着歪，而且是**悄悄**歪：缺答案的题照样能翻出来看，存疑的解析长得和正常的一模一样。

命门是**答案对齐**。这里的每一项都来自踩过的坑：
  · 答案是从 PDF/OCR 抠出来的，抠丢了没人知道 —— 所以要盯覆盖率而不是绝对数
  · 解析由 AI 出、另一家 AI 核验，不一致的标 agree=0 **不发给人做** —— 存疑量要看得见
  · 选词填空的横线曾被 norm 压掉（\\xa0），题干里一条线都没有 —— 修完要留个哨兵防回归
  · 图形题少了图就是道废题，但它在列表里和正常题没区别

**只读、只报告**。`--reset` / `--reparse` / 重跑 OCR 这类动辄改几千行的动作**不进后台**：
它们要在终端里看着全量新旧对比来做（改共用正则先全量比对，是这个项目的老规矩）。
所以每一项带的是「该敲哪条命令」，不是一个按钮。
"""
from flask import Blueprint, jsonify

from core import get_db, log
from mods import realref

bp = Blueprint("quality", __name__)

# 「这道真题能不能发给人做」的口径**不在这儿定义**，从 realref 借。
# 那份注释里写着：realq / drill / audit_qtype 三处原先各写各的，漏一处的表现是
# 「审计数字和线上实际取到的题对不上」——而审计存在的全部意义就是当那个唯一可信的数字。
# 这块是第四个用它的地方，更不能再抄一份。
# ⚠️ 反向统计**不能写成 `WHERE NOT (servable)`**：LEFT JOIN 没匹配上解析时
# e.agree 是 NULL，`has_answer=1 OR NULL` 求值为 NULL，NOT NULL 还是 NULL——
# 那 40 道「没答案也没解析」的题会两边都不计入（实测 7231 可用 + 335 不可用 ≠ 7606）。
# 线上取题用的是正向条件、NULL 自然被排除，所以取题是对的，只有反向统计会漏。
# 用「总数 − 可用数」绕开三值逻辑：CASE WHEN NULL THEN 1 ELSE 0 走的是 ELSE。
_UNSERVABLE = ("SELECT COUNT(*) - SUM(CASE WHEN %s THEN 1 ELSE 0 END) "
               "FROM real_questions q LEFT JOIN real_explains e ON e.qid=q.id"
               % realref.servable("q", "e"))

# key, 名称, 「有问题的数量」SQL, 「总量」SQL, warn 比例, bad 比例, 说明, 该敲的命令
# 比例口径统一是「有问题的 ÷ 总量」，所以每项都是越小越好。
CHECKS = [
    # 最贴近「标尺好不好用」的一项，所以排第一：其余各项都是它的成因分解。
    ("servable", "真题不可用（发不出去的）",
     _UNSERVABLE, "SELECT COUNT(*) FROM real_questions", 0.12, 0.25,
     "口径同 realq / drill / audit_qtype（借 mods/realref.servable）："
     "原卷带答案、或 AI 解析过了双模型核验，且不缺资产。"
     "存疑的题留库里可回查，但绝不发给人做——拿去背错的答案比不做还糟。",
     "python3 audit_qtype.py   # 全库体检，看是哪一环卡住"),

    ("answer", "真题缺答案",
     "SELECT COUNT(*) FROM real_questions WHERE has_answer=0 OR has_answer IS NULL",
     "SELECT COUNT(*) FROM real_questions", 0.05, 0.15,
     "没答案的题进不了练习，也当不了出题的标尺。多半是答案卷没 OCR 或没对齐上。",
     "python3 ocr_answers.py --plan   # 先看差多少，再跑"),

    ("explain", "真题缺解析",
     "SELECT COUNT(*) FROM real_questions q "
     "LEFT JOIN real_explains e ON e.qid=q.id WHERE e.qid IS NULL",
     "SELECT COUNT(*) FROM real_questions", 0.10, 0.25,
     "题能做但没讲解。补跑是按题计费的，先用 --plan 估成本。",
     "python3 gen_real_explain.py --plan"),

    ("agree", "解析存疑（两个模型答案不一致）",
     "SELECT COUNT(*) FROM real_explains WHERE agree=0",
     "SELECT COUNT(*) FROM real_explains", 0.03, 0.08,
     "agree=0 的**不会发给人做**，只是留着回查。占比高说明这批题本身偏难或解析器有问题。",
     "sqlite3 app.db \"SELECT qid,answer,audit_ans FROM real_explains WHERE agree=0 LIMIT 20\""),

    ("asset", "缺资产被锁住的题",
     "SELECT COUNT(*) FROM real_questions WHERE needs_asset=1",
     "SELECT COUNT(*) FROM real_questions", 0.04, 0.10,
     "needs_asset=1 是「缺图或缺材料，发不出去」的锁（见 mods/realref.servable）。"
     "两类成因要分开看：资料分析多半是材料没归位，判断推理是图没抽出来。",
     "sqlite3 app.db \"SELECT module,COUNT(*) FROM real_questions "
     "WHERE needs_asset=1 GROUP BY module\"   # 先看是哪一类"),

    # ⚠️ 判空一律用 instr() 不用 LIKE：`_` 是 LIKE 的单字符通配符，
    # `NOT LIKE '%__%'` 等于「题干不足两字」，恒为假 —— 这条哨兵曾因此完全失效
    # （上线时实测：错写法报 0 道，正确写法报 25 道）。instr 不解释通配符，写不错。
    ("blank", "填空题没有空",
     "SELECT COUNT(*) FROM real_questions WHERE qtype LIKE '%填空%' "
     "AND instr(stem,'＿')=0 AND instr(stem,'__')=0 "
     "AND instr(stem,'——')=0 AND instr(stem,'─')=0",
     "SELECT COUNT(*) FROM real_questions WHERE qtype LIKE '%填空%'", 0.05, 0.20,
     "两种成因，都要盯：①横线曾被文本归一化（\\xa0）整段压掉，题干里一条线不剩，"
     "人看到的是一句没有空的话；②**题型标错**——下文推断题（「这段文字接下来最可能讲的是」）"
     "被 AI 判成了填空题，它本来就不该有空。目前命中的多半是第二种。",
     "python3 audit_qtype.py   # 题型体检；确认是横线丢了再跑 fix_blanks.py"),

    ("drill_agree", "小题库存疑",
     "SELECT COUNT(*) FROM drill_bank WHERE agree=0",
     "SELECT COUNT(*) FROM drill_bank", 0.15, 0.30,
     "单模型出题一致率约 89%，所以每道题都由另一家模型独立作答核验过。"
     "存疑的同样不发给人做，只占库存。",
     "python3 warm_drill_bank.py --plan"),

    ("orphan_explain", "解析挂在不存在的题上",
     "SELECT COUNT(*) FROM real_explains e "
     "LEFT JOIN real_questions q ON q.id=e.qid WHERE q.id IS NULL",
     "SELECT COUNT(*) FROM real_explains", 0.001, 0.01,
     "real_questions 每次去重都整张重建、id 重发，解析靠 (anchor_paper, anchor_seq) "
     "重新挂回去。这里不为 0 说明重挂漏了——解析会显示在错误的题下面。",
     "python3 -c \"import ingest_real; ingest_real.relink_explains()\""),
]


def _num(db, sql):
    try:
        r = db.execute(sql).fetchone()
        return int(r[0] or 0)
    except Exception:
        # 表还没建（新库）或列改名了。返回 None 让上层标成「查不了」，
        # 不能当成 0 —— 那会显示成一切正常。
        log.debug("质检查询失败：%s", sql, exc_info=True)
        return None


def _one(db, key, name, bad_sql, total_sql, warn, bad, note, fix):
    n, total = _num(db, bad_sql), _num(db, total_sql)
    row = {"key": key, "name": name, "n": n, "total": total,
           "ratio": None, "state": "unknown", "note": note, "fix": fix}
    if n is None or total is None:
        row["note"] = "查不了（表或列不在）：" + note
        return row
    if not total:
        # 分母为 0：这类内容压根还没有，不是质量问题
        row["state"] = "ok"
        row["ratio"] = 0.0
        return row
    ratio = n / total
    row["ratio"] = round(ratio * 100, 1)
    row["state"] = "bad" if ratio > bad else ("warn" if ratio > warn else "ok")
    return row


def _drill_runway(db):
    """小题库还能撑几天——存量再多，架不住每天消耗。

    这项没有「有问题的 ÷ 总量」那个形状，所以单独算：可用库存 ÷ 日均消耗。
    """
    usable = _num(db, "SELECT COUNT(*) FROM drill_bank WHERE agree=1")
    used7 = _num(db, "SELECT COUNT(*) FROM drill_log "
                     "WHERE created_at >= datetime('now','localtime','-7 day')")
    row = {"key": "drill_runway", "name": "小题库续航", "n": usable, "total": None,
           "ratio": None, "state": "unknown",
           "note": "可用库存 ÷ 近 7 天日均消耗。定时器每天 03:20 补到 30 道可用，"
                   "所以正常情况下这个数不该掉下来。",
           "fix": "python3 warm_drill_bank.py --target 50"}
    if usable is None or used7 is None:
        row["note"] = "查不了（表或列不在）"
        return row
    per_day = used7 / 7.0
    if per_day <= 0:
        row["state"] = "ok"
        row["days"] = None      # 没人做题，续航无意义
        return row
    days = usable / per_day
    row["days"] = round(days, 1)
    row["state"] = "bad" if days < 3 else ("warn" if days < 7 else "ok")
    return row


def snapshot():
    db = get_db()
    rows = [_one(db, *c) for c in CHECKS]
    rows.append(_drill_runway(db))
    order = {"bad": 0, "unknown": 1, "warn": 2, "ok": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r["ratio"] or 0)))
    return rows


@bp.get("/api/admin/quality")
def quality():
    rows = snapshot()
    counts = {"ok": 0, "warn": 0, "bad": 0, "unknown": 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return jsonify({"counts": counts, "checks": rows})
