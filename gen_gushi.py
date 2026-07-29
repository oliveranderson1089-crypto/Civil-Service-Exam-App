#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""古诗复习卡生成器：给「今日复习 · 古诗」这一路供货。

选诗只认两条硬标准（用户提的两个特点），两条都在**入库时**卡死，
复习那边只管出卡、不做判断：
  1. 话题得是常识判断真考的类型 —— topic 必须落在 gushi_meta.json 的 topics 白名单里；
  2. 篇中得有能直接当申论素材的句子 —— line 必须是该诗原文的子串（去标点后比对）。
第 2 条是校验，不是修辞：AI 张口就来的「名句」十有八九串篇（记岔了作者/拼接两首），
这种卡背下来是负分。核不上原文的一律丢掉，并在结尾报出丢了几条。

用法:
  python3 gen_gushi.py check          # 只核对种子池能不能在 classics 里对上号，不写库
  python3 gen_gushi.py seed           # 把种子池（人工精选）写进 gushi_cards，幂等
  python3 gen_gushi.py expand [N]     # 用 AI 从高频古诗里再挑 N 首（默认 20），同样过两道校验
  python3 gen_gushi.py list           # 看看库里现在有哪些卡
数据写入 gushi_cards（UNIQUE(classic_id,line) 幂等去重）。
"""
import json
import os
import re
import sqlite3
import sys

import aiclient

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
META_PATH = os.path.join(BASE, "gushi_meta.json")
os.environ.setdefault("NO_PROXY", "*")

CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
META = json.load(open(META_PATH, encoding="utf-8"))
TOPICS, THEMES = set(META["topics"]), set(META["themes"])
# 模型档位：fast —— 只做「判定 + 抽句 + 两句讲解」的结构化输出，flash 够用。
# 真实模型名不写在这儿：aiclient 负责 档位→模型名 的映射（见 mods/aiclient 的注释）。
TIER = "fast"

_PUNC = re.compile(r"[^一-鿿]")          # 比对只留汉字：标点、括注、换行、异体注全不算


def norm(s):
    return _PUNC.sub("", s or "")


def ai(messages, max_tokens=2500, temperature=0.3):
    return aiclient.chat(messages, tier=TIER, temperature=temperature,
                         max_tokens=max_tokens, timeout=240, json_mode=True, cfg=CFG)


def ensure_table(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS gushi_cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classic_id INTEGER NOT NULL,
            line TEXT NOT NULL, topic TEXT, theme TEXT,
            common TEXT, apply TEXT, freq INTEGER DEFAULT 0, source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(classic_id, line)
        );
        CREATE INDEX IF NOT EXISTS idx_gushi_freq ON gushi_cards(freq);
    """)
    con.commit()


def load_poems(con):
    """整表读进来做归一化子串匹配。12117 首、几 MB，比在 SQL 里 LIKE 一句句试快得多。"""
    rows = []
    for r in con.execute("SELECT id,title,author,dynasty,category,content FROM classics"):
        rows.append({"id": r[0], "title": r[1] or "", "author": r[2] or "", "dynasty": r[3] or "",
                     "category": r[4] or "", "content": r[5] or "", "n": norm(r[5])})
    return rows


def find_poem(poems, line, title="", author=""):
    """按名句反查原诗。同名诗一大堆（光《清明》就三首、《登鹳雀楼》两首），
    所以**以句定篇**：先要原文真含这句，再用标题/作者挑最像的那一首。"""
    key = norm(line)
    if not key:
        return None, "名句是空的"
    hit = [p for p in poems if key in p["n"]]
    if not hit:
        return None, "原文里没有这句"
    t, a = norm(title), norm(author)

    def score(p):
        s = 0
        if t and t == norm(p["title"]):
            s -= 4
        elif t and t in norm(p["title"]):
            s -= 2
        if a and a in norm(p["author"]):
            s -= 2
        return (s, len(p["n"]))          # 同分取短的：长篇合集里也可能撞上这句
    hit.sort(key=score)
    return hit[0], ""


def save_card(con, cid, line, topic, theme, common, apply_txt, freq, source):
    cur = con.execute(
        "INSERT OR IGNORE INTO gushi_cards(classic_id,line,topic,theme,common,apply,freq,source) "
        "VALUES(?,?,?,?,?,?,?,?)", (cid, line, topic, theme, common, apply_txt, freq, source))
    return cur.rowcount


def check_one(poems, it):
    """一条候选过两道闸。返回 (诗, 错误说明)。"""
    if it.get("topic") not in TOPICS:
        return None, "话题「%s」不在常识常考白名单里" % (it.get("topic") or "")
    if it.get("theme") not in THEMES:
        return None, "申论主题「%s」不在白名单里" % (it.get("theme") or "")
    return find_poem(poems, it.get("line", ""), it.get("title", ""), it.get("author", ""))


def cmd_check(con, write=False):
    poems = load_poems(con)
    ok, bad = 0, []
    for it in META["seed"]:
        p, err = check_one(poems, it)
        if not p:
            bad.append((it.get("title"), it.get("line"), err))
            continue
        ok += 1
        if write:
            save_card(con, p["id"], it["line"], it["topic"], it["theme"],
                      it["common"], it["apply"], 100, "seed")
        else:
            print("  ✓ %-14s %s·%s  ← %s" % (it["title"], p["dynasty"], p["author"], it["line"][:18]))
    if write:
        con.commit()
    print("种子池 %d 条：对上 %d，落空 %d" % (len(META["seed"]), ok, len(bad)))
    for t, ln, err in bad:
        print("  ✗ %s《%s》：%s" % (err, t, ln))
    return ok, bad


def cmd_seed(con):
    ok, bad = cmd_check(con, write=True)
    n = con.execute("SELECT COUNT(*) FROM gushi_cards").fetchone()[0]
    print("写库完成，gushi_cards 现有 %d 条" % n)


PROMPT = """下面是 %d 首古诗文。请逐首判断它是否适合进「公考古诗复习卡」，标准两条**必须同时满足**：
1) 这首诗涉及的话题属于行测常识判断真正常考的类型，只能从这个清单里选一个：%s
2) 篇中有可以直接写进申论文章的句子（哲理、家国、为民、奋斗、廉洁一类），且这句话必须**一字不差地出自给出的原文**，不许改写、不许拼接、不许凭印象写别的诗的句子。

对每一首输出：
{"idx":序号, "ok":true/false, "topic":"话题", "theme":"申论主题（只能选：%s）",
 "line":"原文里的名句（10~24字，逗号分句可保留）",
 "common":"这首在常识判断里的考点，60字内：作者朝代/文学地位/名句出处/所属流派体裁/易混点，挑最可能考的写",
 "apply":"申论怎么用它，40字内：适合哪类主题、放在什么位置"}
两条有一条不满足就 ok=false，其余字段留空——宁可少收，不许硬凑。
只输出 JSON：{"items":[...]}

原文：
%s"""


def cmd_expand(con, want=20):
    poems = load_poems(con)
    have = {r[0] for r in con.execute("SELECT classic_id FROM gushi_cards")}
    by_id = {p["id"]: p for p in poems}
    # 候选：考频高的在前（freq 由 mods/classics.py 的 _ensure_classic_freq 算），太长的不要——
    # 整篇《离骚》塞进 prompt 既费 token 又背不动。
    cand = []
    for r in con.execute("SELECT id FROM classics ORDER BY COALESCE(freq,0) DESC, id"):
        p = by_id.get(r[0])
        if not p or p["id"] in have or not (16 <= len(p["n"]) <= 260):
            continue
        cand.append(p)
        if len(cand) >= want * 3:        # AI 会毙掉一大半，候选按 3 倍备着
            break
    print("候选 %d 首，目标收 %d 条" % (len(cand), want))
    got, drop = 0, {}
    for i in range(0, len(cand), 8):
        if got >= want:
            break
        batch = cand[i:i + 8]
        body = "\n\n".join("%d.《%s》（%s·%s）\n%s" % (j, p["title"], p["dynasty"], p["author"],
                                                    p["content"][:400])
                           for j, p in enumerate(batch))
        try:
            reply = ai([{"role": "system", "content": "你是资深公考辅导老师，兼顾行测常识与申论运用，"
                                                     "宁缺毋滥，严格输出 JSON，用简体中文。"},
                        {"role": "user", "content": PROMPT % (len(batch), "、".join(META["topics"]),
                                                              "、".join(META["themes"]), body)}])
            items = json.loads(reply).get("items", [])
        except Exception as e:
            print("  第 %d 批 AI 失败：%s" % (i // 8 + 1, e))
            continue
        for it in items:
            if not it.get("ok"):
                drop["AI 自己判定不合标准"] = drop.get("AI 自己判定不合标准", 0) + 1
                continue
            try:
                p = batch[int(it.get("idx", -1))]
            except Exception:
                drop["序号对不上"] = drop.get("序号对不上", 0) + 1
                continue
            # 校验：句子必须出自**这一首**（不是别的诗），话题/主题必须在白名单里
            if norm(it.get("line", "")) not in p["n"]:
                drop["名句核不上原文（串篇了）"] = drop.get("名句核不上原文（串篇了）", 0) + 1
                continue
            if it.get("topic") not in TOPICS or it.get("theme") not in THEMES:
                drop["话题/主题不在白名单"] = drop.get("话题/主题不在白名单", 0) + 1
                continue
            got += save_card(con, p["id"], it["line"].strip(), it["topic"], it["theme"],
                             (it.get("common") or "").strip(), (it.get("apply") or "").strip(),
                             60, "ai")
            con.commit()
            print("  + %s《%s》%s" % (p["author"], p["title"], it["line"][:18]))
    print("新增 %d 条" % got)
    for k, v in drop.items():
        print("  丢弃 %d 条：%s" % (v, k))


def cmd_list(con):
    rows = con.execute(
        "SELECT g.topic,g.theme,c.dynasty,c.author,c.title,g.line,g.source "
        "FROM gushi_cards g JOIN classics c ON c.id=g.classic_id "
        "ORDER BY g.topic, g.id").fetchall()
    for r in rows:
        print("[%s|%s] %s·%s《%s》 %s  (%s)" % (r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
    print("共 %d 条" % len(rows))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    con = sqlite3.connect(DB)
    ensure_table(con)
    if cmd == "check":
        cmd_check(con)
    elif cmd == "seed":
        cmd_seed(con)
    elif cmd == "expand":
        cmd_expand(con, int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif cmd == "list":
        cmd_list(con)
    else:
        print(__doc__)
    con.close()


if __name__ == "__main__":
    main()
