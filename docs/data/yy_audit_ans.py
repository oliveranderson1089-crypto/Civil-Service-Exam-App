"""申论真题**答案文件**格式体检（可重跑）。

为什么先做这个：真题库那次的教训是「命门是答案对齐，不是抠出多少条」。
这批 145 个带答案的申论文件横跨 2000-2026、来自不同机构，解析结构大概率不统一。
灌库之前先分桶，知道哪些能直接用、哪些要另想办法，别一头灌进去再回头修。

用法：
    python3 docs/data/yy_audit_ans.py            # 全量体检，出报告
    python3 docs/data/yy_audit_ans.py --csv      # additionally 落一份明细 CSV
文字缓存放 <scratch>/ansaudit/，重跑不重复抽取。
"""
import argparse
import csv
import os
import re
import sqlite3
import subprocess
import sys

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(APP, "app.db")
BLOB = os.path.join(APP, "uploads", "drive")
CACHE = os.environ.get("YY_AUDIT_CACHE",
                       os.path.join(os.environ.get("TMPDIR", "/tmp"), "yy-ansaudit"))

# 抽答案文件：申论 + 名字里带「答案」。「真题」目录那 30 套是题面，不在这儿。
# 两处排除是体检第一轮实测出来的假阳性：
#   · folder LIKE '%申论%' 会把「行测+申论」合并目录里的**行测**答案捞进来（3 个）
#   · 「无答案版」名字里也有「答案」两个字（2 个）
SQL = """
SELECT id, owner_id, folder, name, stored_name, ext, size
  FROM drive_files
 WHERE deleted_at IS NULL AND is_dir=0 AND folder LIKE '公考%%'
   AND (name LIKE '%%申论%%' OR folder LIKE '%%申论%%')
   AND name LIKE '%%答案%%'
   AND name NOT LIKE '%%行测%%'
   AND name NOT LIKE '%%无答案%%'
 ORDER BY folder, name
"""

# ---- 结构特征：每一项都是「原文里出现了什么字面」，不做语义猜测 ----
FEAT = {
    "answer":   r"参考答案|答案要点|【答案|参考例文|参考作文",
    "explain":  r"参考答案说明|答案说明|【说明】",
    "shenti":   r"第一步[—\-－]{0,3}审题|审题[：:]|【审题",
    "findpt":   r"第二步[—\-－]{0,3}阅读资料|寻找要点|要点梳理|采分点",
    "score":    r"评分标准|分档|赋分",
}
# 题号锚点：各家格式差得很远——国考解析用「【试题三】」，四川老卷答案直接用「1、2、3、」。
# 所以不在全文瞎数，而是**在答案锚点之后**数行首序号：那才是「答案能不能按题切开」的指标。
# 切题锚点候选，按可靠性排。**不能只用一个**——各家格式差得远，实测三轮才定下来：
#   ① 只取最后一个「参考答案」→ 国考解析每题一个标记，等于只留最后一题，序号数恒为 0
#   ② 改数「参考答案」总数 → 「参考答案说明」里也含它，且目录和解析里重复出现，
#      2023 副省卷 5 道题数出 21 个，A 桶 4 个最好的文件对齐率显示成 0/4
#   ③ 现在：多锚点候选，**取计数落在题数区间的那个**，并记下靠哪个切开的——
#      这一条直接告诉 P0.5 的解析器要写几个分支
ANCHORS = [
    ("试题号", r"【试题[一二三四五六]】"),
    ("答案要点", r"答案要点"),
    ("题号", r"^[ \t]*第[一二三四五六]题"),
    ("参考答案", r"参考答案(?!说明)"),
    ("行首序号", r"^[ \t]*(?:[一二三四五六1-9][、．.](?=\S))"),
]
NQ_LO, NQ_HI = 3, 6      # 申论一卷 3~5 题，留一格容差


def pick_anchor(text, after=0):
    """挑一个计数落在题数区间的锚点。返回 (锚点名, 计数)；都不合就返回 ('', 0)。"""
    seg = text[after:] if after > 0 else text
    for name, pat in ANCHORS:
        n = len(re.findall(pat, seg, flags=re.M))
        if NQ_LO <= n <= NQ_HI:
            return name, n
    return "", 0


def ans_first(text):
    m = re.search(FEAT["answer"], text)
    return m.start() if m else -1


def scratch(p):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, p)


def pdf_text(path):
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                             capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def office_text(path, key):
    """doc/docx 走 soffice → pdf → pdftotext，和 mods/files.py 里那条链路同源。"""
    outdir = scratch("conv")
    os.makedirs(outdir, exist_ok=True)
    pdf = os.path.join(outdir, key + ".pdf")
    if not os.path.exists(pdf):
        # soffice 按源文件名输出，先拷成 key.ext 再转，避免中文名和重名互相踩
        tmp = os.path.join(outdir, key + os.path.splitext(path)[1])
        if not os.path.exists(tmp):
            with open(path, "rb") as a, open(tmp, "wb") as b:
                b.write(a.read())
        prof = "file://" + scratch("lo_profile")
        try:
            subprocess.run(["soffice", "--headless", "-env:UserInstallation=" + prof,
                            "--convert-to", "pdf", "--outdir", outdir, tmp],
                           timeout=180, check=True, capture_output=True)
        except Exception as e:
            return "", "转换失败：%s" % str(e)[:60]
    if not os.path.exists(pdf):
        return "", "转换后没有 PDF"
    return pdf_text(pdf), ""


def get_text(r):
    key = r["stored_name"].rsplit(".", 1)[0]
    cached = scratch(key + ".txt")
    if os.path.exists(cached):
        return open(cached, encoding="utf-8", errors="ignore").read(), ""
    src = os.path.join(BLOB, str(r["owner_id"]), r["stored_name"])
    if not os.path.exists(src):
        return "", "文件不在盘上"
    ext = (r["ext"] or "").lower()
    if ext == ".pdf":
        t, err = pdf_text(src), ""
    else:
        t, err = office_text(src, key)
    if t:
        open(cached, "w", encoding="utf-8").write(t)
    return t, err


def year_of(name):
    m = re.search(r"(19|20)\d{2}", name)
    return int(m.group(0)) if m else 0


def bucket(f):
    """分桶。顺序即优先级：先看能不能读，再看结构完整度。"""
    if f["err"]:
        return "E·读不出"
    if f["chars"] < 1500:
        return "D·文字层缺失(疑扫描件)"
    if not f["answer"]:
        return "C·抽不到答案字样"
    if f["explain"] and f["shenti"]:
        return "A·答案+说明+审题"
    if f["shenti"] or f["findpt"] or f["score"]:
        return "B·答案+解析(无说明)"
    return "B2·只有答案"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(SQL).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    out = []
    for i, r in enumerate(rows, 1):
        print("\r抽取 %d/%d …" % (i, len(rows)), end="", file=sys.stderr, flush=True)
        t, err = get_text(r)
        # 只压行内空白，**保住换行**：题号锚点靠行首定位，把 \n 也压掉就全认不出来了
        flat = re.sub(r"[ \t]+", "", t)
        pos = ans_first(flat)
        anchor, nq = pick_anchor(flat, pos if pos >= 0 else 0)
        f = dict(id=r["id"], folder=r["folder"], name=r["name"], ext=r["ext"],
                 year=year_of(r["name"]), chars=len(flat), err=err,
                 anchor=anchor, nq=nq,
                 ans_at=round(100.0 * pos / len(flat)) if pos >= 0 and flat else -1)
        for k, pat in FEAT.items():
            f[k] = 1 if re.search(pat, flat) else 0
        f["align"] = 1 if anchor else 0
        f["bucket"] = bucket(f)
        out.append(f)
    print("", file=sys.stderr)

    from collections import Counter, defaultdict
    print("答案文件体检 · 共 %d 个（%s）\n" % (len(out), ", ".join(
        "%s×%d" % kv for kv in Counter(x["ext"] for x in out).most_common())))

    print("== 分桶 ==")
    for k, v in sorted(Counter(x["bucket"] for x in out).items()):
        print("  %-24s %3d  (%.0f%%)" % (k, v, 100.0 * v / len(out)))

    print("\n== 结构特征命中率 ==")
    ok = [x for x in out if not x["err"] and x["chars"] >= 1500]
    for k in FEAT:
        n = sum(x[k] for x in ok)
        print("  %-8s %3d/%d  %.0f%%" % (k, n, len(ok), 100.0 * n / max(1, len(ok))))

    print("\n== 标尺窗口（2018 年起）==")
    win = [x for x in out if x["year"] >= 2018]
    print("  %d 个文件；分桶：%s" % (len(win), "、".join(
        "%s×%d" % kv for kv in Counter(x["bucket"] for x in win).most_common())))

    print("\n== 按年份 × 桶 ==")
    by = defaultdict(Counter)
    for x in out:
        by[x["year"]][x["bucket"][:1]] += 1
    for y in sorted(by):
        print("  %s  %s" % (y or "无年份",
                            " ".join("%s:%d" % kv for kv in sorted(by[y].items()))))

    print("\n== 答案对齐可行性（按题切得开吗）==")
    print("  切得开：%d/%d = %.0f%%"
          % (sum(x["align"] for x in ok), len(ok),
             100.0 * sum(x["align"] for x in ok) / max(1, len(ok))))
    print("  靠哪个锚点切开的（= 解析器要写的分支）：")
    for k, v in Counter(x["anchor"] or "（切不开）" for x in ok).most_common():
        print("    %-10s %3d" % (k, v))
    print("  分桶看：")
    for b in sorted(set(x["bucket"] for x in ok)):
        g = [x for x in ok if x["bucket"] == b]
        print("    %-24s %d/%d" % (b, sum(x["align"] for x in g), len(g)))

    bad = [x for x in out if x["bucket"][0] in "CDE"]
    if bad:
        print("\n== 要另想办法的文件 ==")
        for x in bad:
            print("  [%s] %s  chars=%d %s" % (x["bucket"], x["name"][:52], x["chars"],
                                              x["err"]))

    if args.csv:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yy-答案体检.csv")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
        print("\n明细 → %s" % p)


if __name__ == "__main__":
    main()
