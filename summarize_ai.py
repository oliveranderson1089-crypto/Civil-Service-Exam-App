#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天把「我和 AI 助手的学习对话」总结成一份笔记，存进资料库（分类：AI 学习问答）。

为什么要有它：跟 AI 一问一答学到的东西是散的、聊完就忘。每天收工时让 AI 把当天的问答
提炼成一份「今天问了什么、AI 讲了哪些要点、值得记住的知识点」的笔记，沉淀进资料库，
以后能翻、能复习。按用户各存各的。

用法：
    .venv/bin/python3 summarize_ai.py            # 总结「今天」的对话
    .venv/bin/python3 summarize_ai.py --date 2026-07-15
"""
import argparse
import os
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A  # noqa: E402

CATEGORY = "AI 学习问答"          # 资料库里新分的类
MIN_CHARS = 200                   # 当天对话太少（没怎么学）就不生成，免得净是空笔记


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
        "用简体中文 Markdown，聚焦学到的知识、而不是复述闲聊。分这几块：\n"
        "## 今天问了什么（一句话概括几个主题）\n"
        "## 知识要点（分条，把 AI 讲的干货、结论、易错点记下来，能直接背/复习）\n"
        "## 值得记住的表述 / 例子（如果有金句、典型例子、辨析）\n"
        "只保留对备考有用的；没营养的闲聊略过。若当天没什么实质学习内容，只回一行「（今日无实质学习对话）」。\n\n"
        "问答记录：\n%s" % text)
    reply, err = A._ai_call_or_error(
        [{"role": "system", "content": "你是学习助理，把一天的问答提炼成有条理、能复习的学习笔记。简体中文 Markdown。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=2500)
    if err:
        return None
    return reply


def save_note(db, user_id, day, md):
    """把总结存成资料库里的一份 .md（阅读模式能渲染），分类 = AI 学习问答。"""
    d = A._user_dir(user_id)
    stored = uuid.uuid4().hex + ".md"
    title = "AI 学习问答 · " + day
    header = "# %s\n\n> 由 AI 每日自动汇总当天的学习问答\n\n" % title
    with open(os.path.join(d, stored), "w", encoding="utf-8") as f:
        f.write(header + (md or ""))
    size = os.path.getsize(os.path.join(d, stored))
    db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (user_id, "", CATEGORY, title, title + ".md", stored, ".md", "text/markdown", size))
    db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天")
    a = ap.parse_args()
    day = a.date or time.strftime("%Y-%m-%d")

    db = sqlite3.connect(A.DB, timeout=60)
    db.row_factory = sqlite3.Row
    users = [r["id"] for r in db.execute("SELECT id FROM users")]
    print("汇总 %s 的 AI 学习对话，共 %d 个用户" % (day, len(users)))
    n = 0
    for uid in users:
        # 今天已经生成过就不重复（防定时器重跑 / 手动重跑）
        dup = db.execute(
            "SELECT 1 FROM materials WHERE user_id=? AND board=? AND title=?",
            (uid, CATEGORY, "AI 学习问答 · " + day)).fetchone()
        if dup:
            continue
        msgs = day_msgs(db, uid, day)
        chars = sum(len(c) for _, c in msgs)
        if chars < MIN_CHARS:
            continue
        md = summarize(msgs, day)
        if not md or "今日无实质学习" in md[:40]:
            print("  用户 %d：当天无实质学习对话，跳过" % uid)
            continue
        save_note(db, uid, day, md)
        n += 1
        print("  ✓ 用户 %d：已存入资料库（%d 字对话 → 笔记）" % (uid, chars))
    print("\n生成 %d 份学习笔记" % n)


if __name__ == "__main__":
    main()
