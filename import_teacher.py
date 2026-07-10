#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入老师发的两份资料：
  · 逻辑填空高频成语1000词.pdf  —— 扫描件，OCR 取「成语 + 考频」，释义用本地权威成语库校正
  · 常见实词搭配100组.docx      —— 直接抽文本，解析「动词-宾语1/宾语2…」

写入 changkao_items(board='成语'/'实词')，并把考频回写 idiom_freq，供成语词语库按考频排序。
用法: python3 import_teacher.py [--dry]
"""
import os, re, sys, json, difflib, sqlite3, subprocess, tempfile, shutil, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
DRY = "--dry" in sys.argv

IDIOM_PDF = "逻辑填空高频成语1000词.pdf"
CIDA_DOCX = "常见实词搭配100组.docx"

# OCR 行： 49  休戚与共  考频21次 形容关系密切…
# 序号可能整个丢掉、成语里可能夹进 ] ” 之类噪声，所以只锚定「考频N次」，
# 成语从它前面的汉字里取，释义取它后面的。
ROW = re.compile(r"^\s*(\d{0,4})\s*(.*?)考\s*频\s*(\d+)\s*次(.*)$")
HAN = re.compile(r"[一-龥]+")
NOISE = re.compile(r'^[\s。”"\'’.,，、·:：;；]+')


def _stored(con, title):
    r = con.execute("SELECT user_id, stored_name FROM materials WHERE title=?", (title,)).fetchone()
    if not r:
        return None
    p = os.path.join(UPLOADS, str(r[0]), r[1])
    return p if os.path.exists(p) else None


def ocr_pdf(pdf):
    """整份 PDF 渲染成灰度图逐页 OCR（结果缓存，方便反复调解析规则）。"""
    cache = os.path.join(tempfile.gettempdir(), "idiom_ocr300_%s.txt" % os.path.basename(pdf))
    if os.path.exists(cache):
        print("  用上次的 OCR 缓存")
        return open(cache, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="idmocr_")
    try:
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", pdf, os.path.join(tmp, "p")],
                       check=True, timeout=900, capture_output=True)
        pages = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        out = []
        for i, f in enumerate(pages, 1):
            r = subprocess.run(["tesseract", os.path.join(tmp, f), "stdout",
                                "-l", "chi_sim", "--oem", "1", "--psm", "6"],
                               capture_output=True, timeout=180)
            out.append(r.stdout.decode("utf-8", "ignore"))
            print("  OCR 第 %d/%d 页" % (i, len(pages)), flush=True)
        txt = "\n".join(out)
        open(cache, "w", encoding="utf-8").write(txt)
        return txt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_index(con):
    """按字数分组的权威成语索引，供 OCR 错字纠正。"""
    idx = {}
    for (w,) in con.execute("SELECT word FROM ref_idiom"):
        idx.setdefault(len(w), []).append(w)
    return idx


def build_ci(con):
    """更大的通用词库，用来判断「不忘初心」这类现代四字词是真词还是 OCR 垃圾。"""
    return {w for (w,) in con.execute("SELECT word FROM ref_ci WHERE length(word)=4")}


def build_exp(con):
    """成语 → 释义（只留汉字），供「按释义反查成语」用。"""
    return {w: "".join(HAN.findall(e or ""))
            for w, e in con.execute("SELECT word, explanation FROM ref_idiom WHERE length(word)=4")}


def by_explanation(tip, raw, idx, expmap):
    """成语列 OCR 烂了（棚棚如生），但释义列是好的。
    先按字形取一批候选，再比对释义——释义对得上才认，避免张冠李戴。"""
    frag = "".join(HAN.findall(tip))
    if len(frag) < 8:
        return None
    cands = difflib.get_close_matches(raw, idx.get(4, []), n=20, cutoff=0.4)
    best, score = None, 0.0
    for c in cands:
        e = expmap.get(c)
        if not e:
            continue
        r = difflib.SequenceMatcher(None, frag[:40], e[:40]).ratio()
        if r > score:
            best, score = c, r
    return best if score >= 0.42 else None


def correct(word, idx):
    """OCR 结果纠正。表里全是四字成语，所以：
       · 5 字多半是前后粘了个字，取其中的四字子串再匹配
       · 命中权威库直接用；否则同字数里找最接近的（≥0.7，纠掉「五彩斑糊」这类）"""
    if len(word) == 5:
        for cand in (word[1:], word[:-1]):
            if cand in idx.get(4, []):
                return cand, True
        word = word[1:]
    same = idx.get(len(word), [])
    if word in same:
        return word, True
    hit = difflib.get_close_matches(word, same, n=1, cutoff=0.7)
    return (hit[0], True) if hit else (word, False)


def parse_idioms(text, con):
    idx, ci, expmap = build_index(con), build_ci(con), build_exp(con)
    rows, fixed, unknown, dropped, byexp = [], 0, 0, 0, 0
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        head, freq, tail = m.group(2), int(m.group(3)), m.group(4)
        raw = "".join(HAN.findall(head))[-5:]     # 「一甲]而尔」→「一甲而尔」
        if not 3 <= len(raw) <= 5 or not 1 <= freq <= 99:
            continue
        word, ok = correct(raw, idx)
        if len(word) != 4:                        # 这份表全是四字成语，其余都是 OCR 断裂
            continue
        tip = NOISE.sub("", tail).strip()
        tip = re.sub(r"\s{2,}", " ", tip)
        if not ok:
            # 字形错得太狠、相似度救不回来时，用释义去反查（棚棚如生 → 栩栩如生）
            hit = by_explanation(tip, word, idx, expmap)
            if hit:
                word, ok, byexp = hit, True, byexp + 1
        if word != raw:
            fixed += 1
        if not ok:
            unknown += 1
        rows.append({"word": word, "freq": freq, "tip": tip, "verified": ok})

    # 不按 seq 排序：序号列 OCR 很脏（32 处逆序，还有把释义里的数字读成序号的）。
    # OCR 的行顺序本身就是 PDF 顺序，而 PDF 已按考频从高到低排好。
    # 考频列反而很准（900 多行只有个位数违反非增），所以只修那几个孤立的异常值。
    corrected = 0
    for i, r in enumerate(rows):
        prev = rows[i - 1]["freq"] if i else None
        if prev is None or r["freq"] <= prev:
            continue
        nxt = next((x["freq"] for x in rows[i + 1:i + 4] if x["freq"] <= prev), None)
        # 夹在 prev 与 nxt 之间取中点：OCR 把 32 读成 52 时，(36+29)//2 = 32
        r["freq"] = (prev + nxt) // 2 if nxt is not None else prev
        corrected += 1

    seen, items = set(), []
    for r in rows:
        if r["word"] in seen:
            continue
        seen.add(r["word"])
        items.append(r)
    print("  解析 %d 条（字形纠错 %d，释义反查 %d，考频修正 %d，词典未收录 %d）"
          % (len(items), fixed, byexp, corrected, unknown))
    return items


def parse_cida(path):
    tmp = tempfile.mkdtemp(prefix="cida_")
    try:
        subprocess.run(["soffice", "--headless",
                        "-env:UserInstallation=file://" + os.path.join(tmp, "prof"),
                        "--convert-to", "txt:Text", "--outdir", tmp, path],
                       check=True, timeout=180, capture_output=True)
        txt = [f for f in os.listdir(tmp) if f.endswith(".txt")]
        if not txt:
            return []
        raw = open(os.path.join(tmp, txt[0]), encoding="utf-8", errors="ignore").read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    items = []
    for line in raw.splitlines():
        line = line.strip().lstrip("﻿")
        m = re.match(r"^(\d{1,3})[.、]\s*(.+)$", line)
        if not m:
            continue
        body = m.group(2).strip()
        if "-" not in body:                       # 99/100 那种成组表述，整条收录
            items.append({"head": body[:20], "coll": body, "kind": "表述"})
            continue
        head, coll = body.split("-", 1)
        items.append({"head": head.strip(), "coll": coll.strip(), "kind": "搭配"})
    print("  解析实词搭配 %d 组" % len(items))
    return items


def _ai(messages, max_tokens=4000):
    cfg_path = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    base = (cfg.get("ai_base") or "https://api.deepseek.com").rstrip("/")
    url = base if base.endswith("/chat/completions") else (
        base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions")
    os.environ.setdefault("NO_PROXY", "*")
    payload = {"model": cfg.get("ai_model") or "deepseek-chat", "temperature": 0.1,
               "max_tokens": max_tokens, "messages": messages,
               "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + cfg["ai_key"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"])


def ai_fix(items, con):
    """规则救不回来的（本本灌顶／四四扩扩），交给 AI 判一遍：
    是真实四字词就留着，是 OCR 错字就给出正确写法。一次调用搞定几十条。"""
    idx = build_index(con)
    known = set(idx.get(4, []))
    pend = [it for it in items if it["word"] not in known]
    if not pend:
        return 0
    lines = ["%s ｜ %s" % (it["word"], it["tip"][:40]) for it in pend]
    prompt = ("下面每行是 OCR 出的四字词和它的释义（释义基本正确，词可能有错字）。\n"
              "逐条判断：若这个四字词写法正确（含「不忘初心」「保驾护航」这类现代常用词）就原样返回；\n"
              "若是 OCR 错字，请依据释义给出正确的成语。\n"
              '只输出 JSON：{"items":[{"raw":"本本灌顶","correct":"醍醐灌顶"},{"raw":"不忘初心","correct":"不忘初心"}]}\n\n'
              + "\n".join(lines))
    try:
        d = _ai([{"role": "system", "content": "你是中文语文老师，熟悉成语与常见四字词，严格输出 JSON。"},
                 {"role": "user", "content": prompt}])
    except Exception as e:
        print("  ✗ AI 校对失败：%s（保留原样）" % e)
        return 0
    fix = {x.get("raw"): (x.get("correct") or "").strip() for x in d.get("items", [])}
    n = 0
    for it in items:
        c = fix.get(it["word"])
        if c and len(c) == 4 and c != it["word"]:
            it["word"] = c
            n += 1
    print("  AI 校对 %d 条待定词，改正 %d 条" % (len(pend), n))
    return n


def main():
    con = sqlite3.connect(DB, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS idiom_freq(
        word TEXT PRIMARY KEY, freq INTEGER DEFAULT 0)""")
    for col in ("freq", "source"):
        cols = {r[1] for r in con.execute("PRAGMA table_info(changkao_items)")}
        if col not in cols:
            con.execute("ALTER TABLE changkao_items ADD COLUMN %s %s"
                        % (col, "INTEGER DEFAULT 0" if col == "freq" else "TEXT"))
    con.commit()

    # ---- 成语 ----
    pdf = _stored(con, IDIOM_PDF)
    if not pdf:
        print("✗ 资料库里找不到", IDIOM_PDF)
    else:
        print("→ OCR", IDIOM_PDF)
        items = parse_idioms(ocr_pdf(pdf), con)
        if items:
            ai_fix(items, con)
            seen, dedup = set(), []          # AI 纠正后可能撞车，再去一次重
            for it in items:
                if it["word"] in seen:
                    continue
                seen.add(it["word"])
                dedup.append(it)
            items = dedup
        if items and not DRY:
            con.execute("DELETE FROM changkao_items WHERE board='成语'")   # 换成真题考频版
            for it in items:
                r = con.execute("SELECT explanation FROM ref_idiom WHERE word=?", (it["word"],)).fetchone()
                ref = (r[0] or "").strip() if r else ""
                # 讲义释义带「多用于否定句」「褒义词」这类考点提示，比词典释义更贴考试
                exp = it["tip"] if len(it["tip"]) >= 6 else ref
                note = "考频 %d 次" % it["freq"]
                if ref and len(it["tip"]) >= 6 and ref[:8] not in it["tip"]:
                    note += " · 词典：" + ref[:60]
                con.execute("INSERT OR REPLACE INTO changkao_items(board,title,content,note,freq,source) "
                            "VALUES('成语',?,?,?,?,?)", (it["word"], exp[:220], note, it["freq"], "老师资料"))
                con.execute("INSERT OR REPLACE INTO idiom_freq(word,freq) VALUES(?,?)",
                            (it["word"], it["freq"]))
            con.commit()
            print("✓ 成语入库 %d 条" % len(items))

    # ---- 实词搭配 ----
    doc = _stored(con, CIDA_DOCX)
    if not doc:
        print("✗ 资料库里找不到", CIDA_DOCX)
    else:
        print("→ 解析", CIDA_DOCX)
        items = parse_cida(doc)
        if items and not DRY:
            con.execute("DELETE FROM changkao_items WHERE board='实词'")
            for i, it in enumerate(items):
                con.execute("INSERT OR REPLACE INTO changkao_items(board,title,content,note,freq,source) "
                            "VALUES('实词',?,?,?,?,?)",
                            (it["head"][:40], it["coll"][:200],
                             "申论/逻辑填空常用" + it["kind"], 1000 - i, "老师资料"))
            con.commit()
            print("✓ 实词搭配入库 %d 组" % len(items))

    print("\n库内：成语 %d / 实词 %d / idiom_freq %d" % (
        con.execute("SELECT COUNT(*) FROM changkao_items WHERE board='成语'").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM changkao_items WHERE board='实词'").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM idiom_freq").fetchone()[0]))


if __name__ == "__main__":
    main()
