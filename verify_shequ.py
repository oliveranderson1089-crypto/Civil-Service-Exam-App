#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社区真题的**校对闸门**：源卷的答案不可信，入库后必须过这一关才准发给人做。

为什么非有它不可：本地那两套卷是网传回忆版，抽查就撞见好几处答案与选项对不上
（「小组工作社会目标模式主要应用于」标注 D 职业规划，选项 A 才是对的；
「违反治安管理造成他人损害，民事赔偿责任人」标注 B 社区，正解是 A 行为人或其监护人）。
直接采信 = 拿错答案背，比少收几道题严重得多 —— 真题库当年就栽在这儿。

怎么判：

  第一轮  两家**不同厂商**的模型各自独立作答（绝不把源答案给它们看，否则会被锚定）。
          三方（源卷、甲、乙）全一致 → ok，过闸。
  第二轮  只要有一方不一致，才升一档请第三方仲裁。**算力花在有争议的题上**，
          而不是均摊给全部 120 道。
          仲裁后按多数决：多数与源一致 → ok（但不一致方仍记进 verify_note）；
          多数与源不一致且彼此一致 → doubt，并记下「建议答案」。
          谁也不占多数 → doubt。

判不出来一律 doubt，**不许默认采信源答案** —— 这是这个脚本存在的全部意义。
doubt 的题带标记留在库里（看得见），但不计入可练题量（做不到），由人在
「本地真题 · 入库校对」界面上逐条裁决。

用法：
    python3 verify_shequ.py --dry            # 只看要校对哪些题、预估几次调用
    python3 verify_shequ.py                  # 校对所有还没校对过的（可中断续跑）
    python3 verify_shequ.py --limit 10       # 先跑 10 道看看
    python3 verify_shequ.py --redo           # 全部重来（含已 ok 的）
    python3 verify_shequ.py --paper 2        # 只校对某一份卷子
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import aiclient                                            # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
OBJ_PARTS = ("single", "multi", "judge")

# 判断题在提示词里用「对/错」问，回来再折成 T/F。直接问 T/F 的话模型
# 十次有三次答成 True/False/正确，白白多一层容错。
_TF_IN = {"对": "T", "错": "F", "正确": "T", "错误": "F", "T": "T", "F": "F",
          "TRUE": "T", "FALSE": "F", "√": "T", "×": "F"}


def _q_prompt(row):
    """把一道题写成提示词。**不含源答案**。"""
    opts = json.loads(row["options"] or "[]")
    if row["part"] == "judge":
        return ("下面是一道社区工作者招聘考试的**判断题**。请你独立判断这句话对不对。\n\n"
                "【题目】%s\n\n"
                "只输出 JSON：{\"answer\":\"对\" 或 \"错\",\"note\":\"一句话理由\"}" % row["stem"])
    kind = "**多项选择题**（正确答案有两个或以上）" if row["part"] == "multi" else "**单项选择题**"
    letters = "、".join("ABCD"[:len(opts)])
    body = "\n".join("%s. %s" % ("ABCD"[i], o) for i, o in enumerate(opts))
    return ("下面是一道社区工作者招聘考试的%s。请你独立作答。\n\n"
            "【题目】%s\n【选项】\n%s\n\n"
            "只输出 JSON：{\"answer\":\"从 %s 中选，多选题按字母顺序连写如 ABD\","
            "\"note\":\"一句话理由\"}" % (kind, row["stem"], body, letters))


def _norm_answer(part, raw):
    """把模型给的答案折成库里的口径。折不出来返回空串 —— 空串一律当「这一方弃权」。"""
    s = (raw or "").strip().upper().replace(" ", "")
    if part == "judge":
        for k, v in _TF_IN.items():
            if s.startswith(k.upper()):
                return v
        return ""
    letters = "".join(sorted(set(c for c in s if c in "ABCD")))
    if not letters:
        return ""
    if part == "single" and len(letters) != 1:
        return ""              # 单选题给了多个字母 = 没答对题型，不算数
    return letters


def _ask_deepseek(row, tier):
    """甲方 / 仲裁方：走 aiclient，模型名由档位解析，这儿不许出现真实模型名。"""
    try:
        txt = aiclient.chat([{"role": "user", "content": _q_prompt(row)}],
                            tier=tier, temperature=0.1, max_tokens=500,
                            json_mode=True, timeout=90)
    except Exception as e:
        return "", "调用失败：%s" % str(e)[:80]
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return "", "返回不是 JSON"
    try:
        j = json.loads(m.group())
    except Exception:
        return "", "JSON 解析失败"
    return _norm_answer(row["part"], j.get("answer")), (j.get("note") or "").strip()[:160]


def _ask_zhipu(row, cfg):
    """乙方：**另一家厂商**。跨厂商才叫独立——同一家的两个档位错得往往一模一样。

    模型名从配置里读（vision_model），不写死在代码里。
    """
    base = (cfg.get("vision_base") or "").rstrip("/")
    key = cfg.get("vision_key") or ""
    model = cfg.get("vision_model") or ""
    if not (base and key and model):
        return "", "乙方未配置"
    url = base + ("" if base.endswith("/chat/completions") else "/chat/completions")
    # max_tokens 给到 3000 是**量出来的**：乙方是推理模型，600 的额度会被思考段吃光，
    # 返回 content='' 且 finish_reason='length' —— 抽查的三道题全是这样，
    # 而闸门那边只看到「返回不是 JSON」，根本不知道是额度问题。
    payload = {"model": model, "temperature": 0.1, "max_tokens": 3000,
               "messages": [{"role": "user", "content": _q_prompt(row)}],
               "response_format": {"type": "json_object"}}
    txt = ""
    for attempt in range(3):                      # 这家会瞬时限流（429），退避重试
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            ch = d["choices"][0]
            txt = (ch["message"].get("content") or "").strip()
            if not txt and ch.get("finish_reason") == "length":
                return "", "额度被推理段吃光（finish_reason=length）"
            break
        except Exception as e:
            if attempt == 2:
                return "", "调用失败：%s" % str(e)[:80]
            time.sleep(2 ** attempt * 2)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return "", "返回不是 JSON"
    try:
        j = json.loads(m.group())
    except Exception:
        return "", "JSON 解析失败"
    return _norm_answer(row["part"], j.get("answer")), (j.get("note") or "").strip()[:160]


# 模型**不可能知道**的题：招录人数、年龄上限、合同期限这类只写在当地招聘公告里的事实。
# 实测三方各自「援引公告」给出三个互相矛盾的数字（35 / 71 / 71），而源卷的 143
# 恰好和同一份卷子多选题里的「网格员内部选聘 143 人」对得上 —— 是模型在编，不是源卷错。
# 对这类题，模型的「建议」是**自信的幻觉**，照着改会把对的答案改坏。
# 所以：照样跑核验（能看出分歧就是信息），但**绝不提出改答案的建议**。
LOCAL_QTYPE = "本地县情"


def judge(src, parties, local=False):
    """三方（或四方）表决。返回 (verify, 建议答案, 一句话结论)。

    parties: [(名字, 答案, 理由), ...]，答案为空串表示这一方弃权（调用失败/答不成形）。
    local=True 时不许给建议答案 —— 见 LOCAL_QTYPE 上面那段。
    """
    votes = [p[1] for p in parties if p[1]]
    if not votes:
        return "doubt", "", "没有一方答得出来，无法校对"
    # **少于两方作答一律不盖章。** 少了这一条，只要有一方调用失败，闸门就会悄悄
    # 降级成「单模型说了算」，还照样报「与源卷一致」—— 那比不校对更糟，
    # 因为它给了一个并不存在的保证。判不出来就说判不出来。
    if len(votes) < 2:
        return "doubt", "", "只有 %d 方答得出来，两方以上才算数" % len(votes)
    agree = [v for v in votes if v == src]
    if len(agree) == len(votes):
        return "ok", src, "%d 方独立作答，与源卷一致" % len(votes)
    # 有分歧：看反对方是不是抱成一团
    other = [v for v in votes if v != src]
    top = max(set(other), key=other.count) if other else ""
    if other and other.count(top) > len(votes) / 2:
        return _local(local, other, "doubt", top, "%d/%d 方认为应为 %s，与源卷标注的 %s 不符" % (
            other.count(top), len(votes), top, src))
    if len(agree) > len(votes) / 2:
        return "ok", src, "%d/%d 方与源卷一致（有 %d 方异议）" % (
            len(agree), len(votes), len(votes) - len(agree))
    return _local(local, other, "doubt", "", "各方答案分散，谁也不占多数")


def _local(local, other, verdict, suggest, why):
    """本地事实题只要落到存疑，就一律**撤掉建议答案**并说清为什么。

    放在一处而不是逐个分支写：分歧可能来自「多数反对」也可能来自「答案分散」，
    两条路都得说同一句话 —— 少说一条，那道题就会带着一个幻觉出来的建议摆在裁决台上。
    """
    if not local or verdict == "ok":
        return verdict, suggest, why
    return verdict, "", ("这是本地事实题（招录人数/年龄/期限这类只在当地公告里的数字），"
                         "模型没有依据、答案还互相矛盾（%s）—— **源卷更可信**，别按模型改。"
                         % ("/".join(sorted(set(other))) or "各说各的"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只统计要校对哪些题，不调用 AI")
    ap.add_argument("--redo", action="store_true", help="连已校对过的一起重来")
    ap.add_argument("--limit", type=int, default=0, help="最多校对几道")
    ap.add_argument("--paper", type=int, default=0, help="只校对指定 sq_papers.id")
    ap.add_argument("--sleep", type=float, default=0.4, help="每题之间歇多久（避免撞限流）")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    where = ["part IN (%s)" % ",".join("'%s'" % p for p in OBJ_PARTS)]
    if not a.redo:
        where.append("(verify IS NULL OR verify='')")
    if a.paper:
        where.append("paper_id=%d" % a.paper)
    sql = "SELECT * FROM sq_questions WHERE %s ORDER BY paper_id, seq" % " AND ".join(where)
    rows = con.execute(sql).fetchall()
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        print("没有需要校对的题（--redo 可全部重来）")
        return 0

    cfg = aiclient.load_cfg()
    print("待校对 %d 道。第一轮两家各答一遍，出现分歧才升档仲裁。" % len(rows))
    if a.dry:
        print("预估调用：第一轮 %d 次，仲裁按经验约 %d~%d 次"
              % (len(rows) * 2, len(rows) // 10, len(rows) // 3))
        return 0

    stat = {"ok": 0, "doubt": 0}
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        src = row["answer"]
        a1, n1 = _ask_deepseek(row, "fast")
        a2, n2 = _ask_zhipu(row, cfg)
        local = (row["qtype"] or "") == LOCAL_QTYPE
        parties = [("甲·fast", a1, n1), ("乙·另一家", a2, n2)]
        verdict, suggest, why = judge(src, parties, local)
        if verdict != "ok":                       # 只有争议题才请仲裁，算力花在刀刃上
            a3, n3 = _ask_deepseek(row, "pro")
            parties.append(("丙·pro 仲裁", a3, n3))
            verdict, suggest, why = judge(src, parties, local)
        note = {"src": src, "suggest": suggest, "why": why, "local": local,
                "parties": [{"who": w, "answer": v, "note": n} for w, v, n in parties]}
        con.execute("UPDATE sq_questions SET verify=?, verify_note=? WHERE id=?",
                    (verdict, json.dumps(note, ensure_ascii=False), row["id"]))
        con.commit()                              # 逐题落盘：中断了也不用从头再来
        stat[verdict] = stat.get(verdict, 0) + 1
        flag = "✓" if verdict == "ok" else "⚠"
        print("  %s [%3d/%d] 卷%d 第%2d题 源=%s %s"
              % (flag, i, len(rows), row["paper_id"], row["seq"], src, why))
        if verdict == "doubt":
            print("        题干：%s" % row["stem"][:52])
        time.sleep(a.sleep)

    for pid, in con.execute("SELECT DISTINCT paper_id FROM sq_questions").fetchall():
        n = con.execute("SELECT COUNT(*) FROM sq_questions WHERE paper_id=? AND verify!='ok' "
                        "AND part IN (%s)" % ",".join("'%s'" % p for p in OBJ_PARTS),
                        (pid,)).fetchone()[0]
        con.execute("UPDATE sq_papers SET n_doubt=? WHERE id=?", (n, pid))
    con.commit()
    print("\n校对完成：过闸 %d 道，存疑 %d 道，用时 %.1f 分钟"
          % (stat["ok"], stat["doubt"], (time.time() - t0) / 60))
    print("存疑题带标记留在库里，但不计入可练题量 —— 到「本地真题 · 入库校对」逐条裁决。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
