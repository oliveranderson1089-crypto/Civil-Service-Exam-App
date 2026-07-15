#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给高频实词补上「词义」（changkao_items.meaning）。

实词的 content 存的是**常用搭配**（履行→责任/职责/使命…），但没有「履行」这个词本身是啥意思。
这里补词义：先查内置词典 ref_ci（免费、离线），查不到的再让 AI 写一句公考向的简明释义。
跑一次即可；已经有 meaning 的默认跳过（--force 重写）。

用法：
    .venv/bin/python3 build_ck_meaning.py           # 补实词
    .venv/bin/python3 build_ck_meaning.py --force    # 全部重写
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A  # noqa: E402


def dict_meaning(db, word):
    """从内置词典 ref_ci 查词义，清洗成一句简明释义（去掉编号、乱码尾巴、例句）。"""
    r = db.execute("SELECT explanation FROM ref_ci WHERE word=?", (word,)).fetchone()
    if not r or not r["explanation"]:
        return ""
    t = r["explanation"]
    t = re.sub(r"[0-9a-f]{4}\b", "", t)          # ref_ci 里偶有 fdc7 这种乱码尾巴
    t = t.split("｜")[0].split("|")[0]           # 只要第一个义项/去掉竖线例句
    t = re.sub(r"^\s*[1-9１-９]\s*[.．、]\s*", "", t.strip())   # 去开头编号
    t = re.sub(r"\s+", " ", t).strip("；;。 ")
    # 太长（多半带例句）就截到第一句
    if len(t) > 40:
        t = re.split(r"[；;。]", t)[0]
    return t.strip()[:60]


def ai_meanings(words):
    """一次性让 AI 给一批实词写简明释义（公考向，一句话）。返回 {词: 释义}。"""
    lst = "、".join(words)
    prompt = (
        "下面是一批公考高频实词。请给每个词写**一句话的简明释义**（这个词本身是什么意思），"
        "面向公务员考试考生，准确、精炼，不要例句、不要搭配、不要拼音。\n"
        "词语：%s\n\n"
        '只输出 JSON：{"r":[{"w":"词","m":"释义"}]}' % lst)
    rep, err = A._ai_call_or_error(
        [{"role": "system", "content": "你是词典编辑，给词写简明释义。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=2000, timeout=120, json_mode=True)
    if err:
        return {}
    try:
        import json
        out = {}
        for x in json.loads(rep).get("r") or []:
            w, m = (x.get("w") or "").strip(), (x.get("m") or "").strip()
            if w and m:
                out[w] = re.sub(r"\s+", " ", m)[:60]
        return out
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="重写已有 meaning")
    ap.add_argument("--board", default="实词", help="给哪个板块补（默认实词）")
    a = ap.parse_args()

    db = sqlite3.connect(A.DB, timeout=60)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, title, meaning FROM changkao_items WHERE board=? ORDER BY id",
                      (a.board,)).fetchall()
    todo = [r for r in rows if a.force or not (r["meaning"] or "").strip()]
    print("%s 共 %d 条，要补 %d 条" % (a.board, len(rows), len(todo)))

    from_dict, need_ai = 0, []
    for r in todo:
        m = dict_meaning(db, r["title"])
        if m:
            db.execute("UPDATE changkao_items SET meaning=? WHERE id=?", (m, r["id"]))
            from_dict += 1
        else:
            need_ai.append(r)
    db.commit()
    print("  词典命中 %d 条" % from_dict)

    # 词典没收的，分批喂 AI（一批 20 个，省 token）
    ai_done = 0
    for i in range(0, len(need_ai), 20):
        batch = need_ai[i:i + 20]
        mp = ai_meanings([r["title"] for r in batch])
        for r in batch:
            m = mp.get(r["title"])
            if m:
                db.execute("UPDATE changkao_items SET meaning=? WHERE id=?", (m, r["id"]))
                ai_done += 1
        db.commit()
        print("  AI 批 %d：补了 %d/%d" % (i // 20 + 1, sum(1 for r in batch if mp.get(r["title"])), len(batch)))
    print("AI 补 %d 条；仍缺 %d 条" % (ai_done, len(need_ai) - ai_done))

    # 抽查
    print("\n抽查：")
    for r in db.execute("SELECT title, meaning, content FROM changkao_items WHERE board=? AND meaning<>'' "
                        "ORDER BY id LIMIT 6", (a.board,)):
        print("  %-6s 释义：%s" % (r["title"], r["meaning"]))


if __name__ == "__main__":
    main()
