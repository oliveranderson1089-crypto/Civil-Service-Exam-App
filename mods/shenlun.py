"""申论：四大题型讲义 + 真题卷自动拆题。

「真题卷」这段没有自己的路由，是纯设施：_split_paper / _classify_questions /
_sl_words / _sl_word_range / _SL_SCORE 五个符号全被小题训练用——它得先在这儿，
小题训练才拆得动。

_SL_* 那几条拆题正则曾在抽 mods/files.py 时被误删过一次（测试全绿、pyflakes 抓回）。
"""
import json
import os
import re

from flask import Blueprint, jsonify

from core import BASE, get_db, uid
from mods.ai import _ai_call_or_error
from mods.files import _reflow, _strip_artifacts

bp = Blueprint("shenlun", __name__)


# ---- 申论（四大题型讲义 + AI 逐点批改） ----
try:
    with open(os.path.join(BASE, "shenlun_meta.json"), encoding="utf-8") as _fp:
        _SL_META = json.load(_fp)
except Exception:
    _SL_META = {"types": []}

_SL_TYPES = {t["key"]: t for t in _SL_META.get("types", [])}


@bp.get("/api/shenlun/types")
def shenlun_types():
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM shenlun_grade WHERE user_id=?", (uid(),)).fetchone()[0]
    return jsonify({"types": [{k: v for k, v in t.items() if k != "map"} for t in _SL_META["types"]],
                    "graded": n})


@bp.get("/api/shenlun/type/<key>")
def shenlun_type(key):
    t = _SL_TYPES.get(key)
    if not t:
        return jsonify({"error": "没有这个题型"}), 404
    return jsonify(t)


# ---- 申论真题卷：上传 → 自动拆题 ----
def _sl_words(t):
    """申论字数：不含空白，标点计入（与考试口径一致）。"""
    return len(re.sub(r"\s+", "", t or ""))


# 页眉页脚、水印、答题卡行号 —— 从真题里抽出来的杂质，混进材料/题干会很难看


def _sl_word_range(text):
    """从「字数1000-1200字」「不超过200字」这类要求里读出字数区间。"""
    m = re.search(r"(\d{2,4})\s*[-~—－至]\s*(\d{2,4})\s*字", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"不\s*超\s*过\s*(\d{2,4})\s*字", text)
    if m:
        n = int(m.group(1))
        return int(n * 0.8), n
    m = re.search(r"不\s*少\s*于\s*(\d{2,4})\s*字", text)
    if m:
        n = int(m.group(1))
        return n, int(n * 1.3)
    m = re.search(r"(\d{2,4})\s*字\s*(?:左右|以内|以下)", text)
    if m:
        n = int(m.group(1))
        return int(n * 0.85), n
    return None, None


def _sl_sections(text):
    """定位材料段起点与作答要求起点。独立成行的大标题最可信；退一步用「材料1」；再退一步宽松匹配。"""
    req = None
    tr = list(_SL_TITLE_REQ.finditer(text))
    if tr:
        req = tr[-1]
    else:
        loose = list(_SL_HEAD_REQ.finditer(text))
        if loose:
            req = loose[-1]          # 注意事项里那次在前，真正的标题在后
    req_start = req.start() if req else max(0, len(text) - 3000)
    req_end = req.end() if req else req_start

    mat_start = 0
    tm = [m for m in _SL_TITLE_MAT.finditer(text) if m.end() < req_start]
    if tm:
        mat_start = tm[-1].end()
    m1 = _SL_MAT_1.search(text[:req_start])
    if m1 and (not tm or m1.start() >= mat_start):
        mat_start = m1.start()       # 直接从「材料1」开始，把注意事项甩掉
    if not tm and not m1:
        lm = [m for m in _SL_HEAD_MAT.finditer(text) if m.end() < req_start]
        if lm:
            mat_start = lm[-1].end()
    return mat_start, req_start, req_end


# 申论卷拆题用的正则（不属于文件设施，随 mods/files.py 抽取时被误删过一次，pyflakes 抓回来的）
_SL_TITLE_MAT = re.compile(r"^[ \t]*(?:[二2][、.．]\s*)?给\s*定\s*资\s*料[ \t]*$", re.M)
_SL_TITLE_REQ = re.compile(r"^[ \t]*(?:[三3][、.．]\s*)?作\s*答\s*(?:要\s*求|任\s*务)[ \t]*$", re.M)
_SL_HEAD_MAT = re.compile(r"给\s*定\s*资\s*料")
_SL_HEAD_REQ = re.compile(r"作\s*答\s*要\s*求|作\s*答\s*任\s*务")
_SL_MAT_1 = re.compile(r"^[ \t]*(?:给定)?材\s*料\s*[一1][ \t]*$|^[ \t]*(?:给定)?材\s*料\s*[一1][：:，,]", re.M)
# 题号形式：第一题 / 1. / （2） / 三、  —— 只在「作答要求」之后的文本里找，不会误伤材料
_SL_Q_HEAD = re.compile(
    r"^[ \t]*(?:第\s*([一二三四五六七八九十\d]+)\s*题[.、．:：]?"
    r"|[（(]?\s*(\d{1,2})\s*[.、．)）]"
    r"|([一二三四五六七八九十]{1,3})\s*[、.．])\s*", re.M)
_SL_SCORE = re.compile(r"[（(]\s*(\d{1,2})\s*分\s*[）)]")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

def _split_paper(text):
    """本地切分：材料段 / 作答要求段 / 各小题。AI 只负责判题型，省钱也更稳。"""
    text = _strip_artifacts(text)    # 先洗掉页眉页脚 / 答题卡行号
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    mat_start, req_start, req_end = _sl_sections(text)
    material = _reflow(text[mat_start:req_start].strip())
    if len(material) < 60:           # 切歪了，宁可把作答要求之前的全文当材料
        material = _reflow(text[:req_start].strip())
    qtext = text[req_end:].strip()

    heads = list(_SL_Q_HEAD.finditer(qtext))
    qs = []
    for i, h in enumerate(heads):
        cn = h.group(1) or h.group(3) or ""
        seq = _CN_NUM.get(cn, 0) or (int(h.group(2)) if h.group(2) else 0)
        body = qtext[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(qtext)].strip()
        if len(body) < 15:            # 误命中列表项
            continue
        qs.append({"seq": seq or (len(qs) + 1), "body": body})
    # 题号乱了就按出现顺序重编
    if not qs or len({q["seq"] for q in qs}) != len(qs):
        for i, q in enumerate(qs, 1):
            q["seq"] = i
    return material, qtext, qs


def _classify_questions(qs):
    """一次 AI 调用给所有小题定题型（题干短，很便宜）。"""
    lines = ["%d. %s" % (q["seq"], q["body"][:300].replace("\n", " ")) for q in qs]
    prompt = ("下面是一份申论真题的各道小题。请判断每题的题型，只能从这五个里选：\n"
              "guina=归纳概括题，zonghe=综合分析题，duice=提出对策题，guanche=贯彻执行题（要写公文/文书），"
              "zuowen=文章写作（大作文）。\n"
              "同时给出这道题的满分（题干里有「（X分）」就用它），以及题目要求的字数区间"
              "（题干里有「1000-1200字」「不超过200字」就照抄成 word_min/word_max，没有就填 0）。\n"
              '只输出 JSON：{"items":[{"seq":1,"qtype":"guina","full":15,"word_min":150,"word_max":200}]}\n\n'
              + "\n\n".join(lines))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论教研老师，熟悉各题型的判别特征，严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200, json_mode=True, tier="pro")
    if err:
        return {}
    try:
        return {int(x["seq"]): x for x in json.loads(rep).get("items", [])}
    except Exception:
        return {}

