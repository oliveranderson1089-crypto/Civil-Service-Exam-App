"""把 30 套申论真题的「作答要求」抽出来，按题切开，量出文种/题位/字数/分值分布。"""
import os
import re
import subprocess
import sys

SCR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(SCR))
DB = os.path.join(APP, "app.db")
BASE = os.path.join(APP, "uploads", "drive")


def load_rows():
    """卷子清单直接从库里取，不依赖手工准备的 list.txt——否则换台机器/换个目录就跑不起来。"""
    import sqlite3
    con = sqlite3.connect(DB)
    return [(str(i), os.path.join(str(o), sn), n) for i, o, sn, n in con.execute(
        "SELECT id, owner_id, stored_name, name FROM drive_files "
        "WHERE deleted_at IS NULL AND is_dir=0 AND folder='公考/真题' ORDER BY name")]


rows = load_rows()

# 页眉页脚（申公宝 APP 整理的水印），切题之前必须清掉，否则题干里混一堆广告
NOISE = [r"申公宝APP.*?来源", r"第\s*\d+\s*页\s*共\s*\d+\s*页.*?仅供学习",
         r"^\s*\d{3}\s*$", r"^\s*\d00\s*$"]


def clean(t):
    for p in NOISE:
        t = re.sub(p, "", t, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", t)


def get_text(stored):
    # 文字缓存不落仓库：默认丢临时目录，重跑不重复抽取
    cache = os.environ.get("YY_TXT_CACHE",
                           os.path.join(os.environ.get("TMPDIR", "/tmp"), "yy-txt"))
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, os.path.basename(stored).replace(".pdf", ".txt"))
    if not os.path.exists(out):
        subprocess.run(["pdftotext", "-layout", os.path.join(BASE, stored), out], check=True)
    return clean(open(out, encoding="utf-8", errors="ignore").read())


def qsplit(text):
    """作答要求段落 → 按「一、二、三…」切成题。返回 [题干文本]。"""
    m = re.search(r"[三二]、\s*作答要求", text)
    if not m:
        return []
    body = text[m.end():]
    # 题号：行首的「一、」「二、」…（作答要求里用汉字序号），也兼容「第一题」
    idx = [(mm.start(), mm.group(1)) for mm in
           re.finditer(r"^\s*([一二三四五六])、", body, flags=re.M)]
    if not idx:
        return []
    qs = []
    for i, (pos, num) in enumerate(idx):
        end = idx[i + 1][0] if i + 1 < len(idx) else len(body)
        qs.append(re.sub(r"\s+", " ", body[pos:end]).strip())
    return qs


# 文种识别：长词优先（「调研报告」要先于「报告」），一个题干可能提到多个，取最先命中的
DOCTYPES = ["调研报告", "工作方案", "宣传稿", "宣传材料", "讲话稿", "发言稿", "演讲稿",
            "倡议书", "建议书", "公开信", "感谢信", "回信", "新闻稿", "短评", "评论",
            "编者按", "汇报材料", "情况汇报", "工作汇报", "汇报", "简报", "汇编",
            "案例", "经验介绍", "交流材料", "导言", "导语", "提纲", "方案", "通知",
            "报告", "总结", "手册", "指南", "解说稿", "串词", "主持词", "答复", "回复",
            "致辞", "贺信", "倡议", "推荐语", "留言", "问答", "访谈", "调查问卷"]


def find_doctype(q):
    hits = []
    for d in DOCTYPES:
        p = q.find(d)
        if p >= 0:
            hits.append((p, d))
    if not hits:
        return ""
    hits.sort()
    # 同一位置上的重叠词取最长的（"调研报告" vs "报告"）
    best = hits[0]
    for p, d in hits:
        if p <= best[0] + 2 and len(d) > len(best[1]):
            best = (p, d)
    return best[1]


def find_words(q):
    # PDF 里「不超过500字」会被折行成「不超 过500字」，正则前先把空白全去掉，
    # 否则整批「不超过」的字数一个都抽不到（实测漏了 7 道，其中 2 道是应用文）
    q = re.sub(r"\s+", "", q)
    m = re.findall(r"(?:不超过|不多于|控制在|限)\s*(\d{2,4})\s*(?:字|个字)", q)
    if m:
        return int(m[-1]) if len(m) == 1 else max(int(x) for x in m)
    m = re.findall(r"(\d{3,4})\s*[-~—]\s*(\d{3,4})\s*字", q)
    if m:
        return int(m[0][1])
    m = re.findall(r"(\d{3,4})\s*字(?:左右|以[上内])", q)
    return int(m[0]) if m else 0


def find_score(q):
    m = re.search(r"[（(]\s*(\d{1,2})\s*分\s*[)）]", q)
    return int(m.group(1)) if m else 0


print("paper\tseq\tscore\twords\tdoctype\tstem")
for pid, stored, name in rows:
    try:
        qs = qsplit(get_text(stored))
    except Exception as e:
        print("!! %s %s" % (name, e), file=sys.stderr)
        continue
    if not qs:
        print("!! 切不出题：%s" % name, file=sys.stderr)
        continue
    for i, q in enumerate(qs, 1):
        print("\t".join([name, str(i), str(find_score(q)), str(find_words(q)),
                         find_doctype(q), q[:260]]))
