#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「我和 AI 助手的学习对话」总结成笔记，存进资料库（分类：AI 学习问答）。

为什么要有它：跟 AI 一问一答学到的东西是散的、聊完就忘。每天收工时让 AI 把当天的问答
提炼成一份「今天问了什么、AI 讲了哪些要点、值得记住的知识点」的笔记，沉淀进资料库，
以后能翻、能复习。按用户各存各的。

标题由 AI 按当天真正学了什么来起（「资料分析的速算三招 · 08-11」），日期永远留在末尾 ——
一列全是「AI 学习问答 · 某日」的话，翻起来等于没有标题，得挨个点开才知道哪天讲了什么。

每周再把这七份日记合成一份**周总结**（--weekly）：日记是流水账，周总结负责回答
「这周到底积累了什么、哪些还没弄懂」。

用法：
    .venv/bin/python3 summarize_ai.py            # 总结「今天」的对话
    .venv/bin/python3 summarize_ai.py --date 2026-07-15
    .venv/bin/python3 summarize_ai.py --weekly   # 把最近 7 天的日记合成周总结
"""
import argparse
import datetime
import os
import re
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import DB  # noqa: E402
from mods.ai import _ai_call_or_error  # noqa: E402
from mods.files import _user_dir  # noqa: E402

CATEGORY = "AI 学习问答"          # 资料库里新分的类
MIN_CHARS = 200                   # 当天对话太少（没怎么学）就不生成，免得净是空笔记
WEEK_MIN = 2                      # 一周里少于两份日记就不出周总结（凑不成「一周」）
DEF_TITLE = "AI 学习问答"          # AI 没给出标题时的退路


def day_msgs(db, user_id, day):
    """取某用户当天有更新的会话里的问答（user/assistant 成对）。"""
    rows = db.execute(
        "SELECT m.role, m.content FROM ai_msgs m JOIN ai_chats c ON c.id=m.chat_id "
        "WHERE c.user_id=? AND date(c.updated_at)=? ORDER BY m.chat_id, m.id",
        (user_id, day)).fetchall()
    return [(r["role"], r["content"] or "") for r in rows]


def summarize(msgs, day):
    convo = []
    for role, content in msgs:
        who = "我" if role == "user" else "AI"
        convo.append("%s：%s" % (who, content[:1200]))
    text = "\n".join(convo)[:12000]
    prompt = (
        "下面是我（公考考生）今天和 AI 学习助手的问答记录。请提炼成一份**今日学习笔记**，"
        "用简体中文 Markdown，聚焦学到的知识、而不是复述闲聊。\n"
        "**第一行**先单独写一行标题，格式就是「标题：xxx」——用一句不超过 16 个字的话概括"
        "今天到底学了什么（例：「资料分析的速算三招」「定义判断怎么抓主体」）。"
        "不要写成「今日学习笔记」「AI 问答总结」这种谁都能套的空话。\n"
        "第二行起是正文，分这几块：\n"
        "## 今天问了什么（一句话概括几个主题）\n"
        "## 知识要点（分条，把 AI 讲的干货、结论、易错点记下来，能直接背/复习）\n"
        "## 值得记住的表述 / 例子（如果有金句、典型例子、辨析）\n"
        "只保留对备考有用的；没营养的闲聊略过。若当天没什么实质学习内容，只回一行「（今日无实质学习对话）」。\n\n"
        "问答记录：\n%s" % text)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是学习助理，把一天的问答提炼成有条理、能复习的学习笔记。简体中文 Markdown。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=2500)
    if err:
        return None, ""
    return _split_title(reply)


def _split_title(reply):
    """把 AI 回的第一行「标题：xxx」摘出来，剩下的当正文。

    摘不出来（模型没照格式写）就返回空标题，由调用方退回默认名 —— 宁可标题平淡，
    也不能因为格式没对上就丢掉整份笔记。
    """
    text = (reply or "").lstrip()
    m = re.match(r"^\s*(?:#+\s*)?标题[：:]\s*(.+?)\s*$", text.split("\n", 1)[0])
    if not m:
        return text, ""
    title = m.group(1).strip().strip("《》\"'“”")
    body = text.split("\n", 1)[1].lstrip() if "\n" in text else ""
    return body, title[:24]


def save_note(db, user_id, day, md, topic="", note="由 AI 每日自动汇总当天的学习问答"):
    """把总结存成资料库里的一份 .md（阅读模式能渲染），分类 = AI 学习问答。

    标题 = 「AI 起的主题 · 日期」。日期一定留着：资料库里同类是按标题排的，
    没日期就分不清哪份是哪天的；主题在前，扫一眼列表就知道哪天讲了什么。
    """
    d = _user_dir(user_id)
    stored = uuid.uuid4().hex + ".md"
    title = "%s · %s" % (topic or DEF_TITLE, day)
    header = "# %s\n\n> %s\n\n" % (title, note)
    with open(os.path.join(d, stored), "w", encoding="utf-8") as f:
        f.write(header + (md or ""))
    size = os.path.getsize(os.path.join(d, stored))
    db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (user_id, "", CATEGORY, title, title + ".md", stored, ".md", "text/markdown", size))
    db.commit()


def week_notes(db, user_id, days):
    """取这一周里已经生成的日记（标题 + 正文），周总结就长在它们上面。

    直接读日记而不是重新读原始问答：一周的对话有几十万字，塞不进一次调用；
    日记本身已经是提炼过的，合起来正好是一次能吃下的量。
    """
    out = []
    for day in days:
        r = db.execute(
            "SELECT title, stored_name FROM materials WHERE user_id=? AND board=? AND title LIKE ? "
            "ORDER BY id DESC LIMIT 1", (user_id, CATEGORY, "%· " + day)).fetchone()
        if not r:
            continue
        path = os.path.join(_user_dir(user_id), r["stored_name"])
        try:
            with open(path, encoding="utf-8") as f:
                out.append((day, r["title"], f.read()[:6000]))
        except OSError as e:          # 文件被手工删了/搬走了：跳过这天，别让整周的总结挂掉
            print("  ! 读不到 %s 的日记（%s），跳过这天" % (day, e))
    return out


def summarize_week(notes, span):
    text = "\n\n".join("【%s %s】\n%s" % (d, t, body) for d, t, body in notes)[:24000]
    prompt = (
        "下面是我（公考考生）最近一周每天的 AI 学习问答日记。请合成一份**本周学习总结**，"
        "用简体中文 Markdown。这不是把七天的日记再抄一遍，而是要跳出单天看整周：\n"
        "**第一行**先单独写一行「标题：xxx」——不超过 16 个字，概括这周的主线"
        "（例：「资料分析速算＋定义判断打底」）。\n"
        "第二行起分这几块：\n"
        "## 这周学了什么（按模块归拢，几条说清主线）\n"
        "## 反复出现的考点（跨天出现过两次以上的，就是我真正在啃的东西）\n"
        "## 还没弄懂的 / 下周该补的（从我问的问题里看出来的薄弱处，说具体）\n"
        "## 值得背下来的（金句、口诀、辨析，能直接拿去复习）\n\n"
        "日记：\n%s" % text)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是备考教练，把一周的学习日记合成有判断、能指导下周的总结。简体中文 Markdown。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=3000)
    if err:
        print("  ! AI 调用失败：%s" % err)
        return None, ""
    return _split_title(reply)


def run_daily(db, day):
    users = [r["id"] for r in db.execute("SELECT id FROM users")]
    print("汇总 %s 的 AI 学习对话，共 %d 个用户" % (day, len(users)))
    n = 0
    for uid in users:
        # 今天已经生成过就不重复（防定时器重跑 / 手动重跑）。标题的**前半截是 AI 起的**，
        # 每次都不一样，只有「· 日期」这个尾巴是稳的 —— 认它，别再按整串标题比。
        dup = db.execute(
            "SELECT 1 FROM materials WHERE user_id=? AND board=? AND title LIKE ?",
            (uid, CATEGORY, "%· " + day)).fetchone()
        if dup:
            continue
        msgs = day_msgs(db, uid, day)
        chars = sum(len(c) for _, c in msgs)
        if chars < MIN_CHARS:
            continue
        md, topic = summarize(msgs, day)
        if not md or "今日无实质学习" in md[:40]:
            print("  用户 %d：当天无实质学习对话，跳过" % uid)
            continue
        save_note(db, uid, day, md, topic)
        n += 1
        print("  ✓ 用户 %d：《%s》（%d 字对话 → 笔记）" % (uid, topic or DEF_TITLE, chars))
    print("\n生成 %d 份学习笔记" % n)


def run_weekly(db, end):
    """把 end 往前数 7 天（含 end）的日记合成一份周总结。"""
    d1 = datetime.date.fromisoformat(end)
    days = [(d1 - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    span = "%s~%s" % (days[0][5:], days[-1][5:])
    users = [r["id"] for r in db.execute("SELECT id FROM users")]
    print("汇总 %s 这一周的学习日记，共 %d 个用户" % (span, len(users)))
    n = 0
    for uid in users:
        dup = db.execute(
            "SELECT 1 FROM materials WHERE user_id=? AND board=? AND title LIKE ?",
            (uid, CATEGORY, "%周报 · " + span)).fetchone()
        if dup:
            continue
        notes = week_notes(db, uid, days)
        if len(notes) < WEEK_MIN:
            print("  用户 %d：这周只有 %d 份日记，先不出周总结" % (uid, len(notes)))
            continue
        md, topic = summarize_week(notes, span)
        if not md:
            continue
        save_note(db, uid, span, md, (topic or "这一周") + " 周报",
                  note="由 AI 每周自动汇总 %s 的 %d 份学习日记" % (span, len(notes)))
        n += 1
        print("  ✓ 用户 %d：《%s 周报 · %s》（%d 份日记）" % (uid, topic or "这一周", span, len(notes)))
    print("\n生成 %d 份周总结" % n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--weekly", action="store_true", help="把最近 7 天的日记合成一份周总结")
    a = ap.parse_args()
    day = a.date or time.strftime("%Y-%m-%d")

    db = sqlite3.connect(DB, timeout=60)
    db.row_factory = sqlite3.Row
    if a.weekly:
        run_weekly(db, day)
    else:
        run_daily(db, day)


if __name__ == "__main__":
    main()
