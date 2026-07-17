"""小题训练：找点 + 写点（申论小题的两步练法）。

归纳概括 / 综合分析 / 提出对策，难点是同一个：**从材料里把要点找出来**。
所以拆成两步练，每步都能单独纠错：
第一步「找点」——在材料上勾画，判**找漏 / 找错 / 找重**（这一步不写字，只找）
第二步「写点」——照着勾画的地方写要点，判**概括到不到位**（抄原文、并成一坨、漏关键词）

判定的前提是：出题时就得存下「采分点 ↔ 材料原文的逐字依据」。没有依据就只能凭感觉批，
等于没批。所以 AI 出的每个采分点都要给 evidence，且**必须逐字出现在材料里**，服务端逐条核对。
"""
import json
import os
import random
import re
import tempfile
import uuid

from flask import Blueprint, jsonify, request

from core import get_db, log, uid
from mods.ai import _ai_call_or_error
from mods.files import IMAGE_EXT, _ocr_image, _pdf_text_or_ocr, _reflow, _strip_artifacts
from mods.gongwen import GW_DOCTYPES, GW_MAP
from mods.shenlun import (_SL_SCORE, _SL_TYPES, _classify_questions,
                          _sl_word_range, _sl_words, _split_paper)

bp = Blueprint("find", __name__)


FIND_TYPES = {
    "guina": ("归纳概括题", 15, 150, 250,
              "把材料里的同类信息抽出来、合并、分条 —— 不评价、不引申，材料有什么就写什么"),
    "zonghe": ("综合分析题", 20, 250, 350,
               "先亮观点/解释，再分层分析（是什么→为什么→怎么样），最后落回结论"),
    "duice": ("提出对策题", 20, 300, 400,
              "对策必须**从材料的问题里长出来**，一个问题对一条对策；要具体可执行，不许喊口号"),
    "guanche": ("贯彻执行题", 20, 400, 600,
                "先从材料里找全要点（这一步和归纳概括一样），再按指定文种的格式写成一篇 —— "
                "格式对、要点全、语言得体。含讲话稿/宣传稿/公开信/新闻稿/倡议书/汇报/调研报告/"
                "简报/案例介绍/编者按/方案/建议书/通知/短评等文种"),
}
# 断句：申论找点就是找句子，句子边界明确才判得准（自由划词区间对不齐，判定必然是玄学）。
# 两个坑（实测踩出来的）：
#   · 引号里的句号会把句子劈开，末尾剩个孤零零的「”」——闭引号/闭括号要并回上一句
#   · 「材料一」这种标题行也会成为「可勾画的句子」——要标成 head，不让点
_SENT_END = re.compile(r"(?<=[。！？；!?;])")
_CLOSERS = "”’\"'）)》】」』"
_MAT_HEAD = re.compile(r"^[（(]?\s*(?:给定)?[材资]\s*料\s*[一二三四五六七八九十\d]{1,3}\s*[）)]?[.、：:]?$")


def _find_sents(material):
    """材料 → 句子数组。前端按句渲染，勾画粒度就是句。head=True 的是标题行，不可勾画。"""
    out = []
    for pi, para in enumerate(material.split("\n")):
        para = para.strip()
        if not para:
            continue
        if _MAT_HEAD.match(para) or (len(para) <= 8 and not re.search(r"[。！？；，]", para)):
            out.append({"p": pi, "t": para, "head": True})
            continue
        parts = [x for x in _SENT_END.split(para) if x]
        merged = []
        for x in parts:
            # 「…了。」「”」被切成两段 —— 闭引号/闭括号开头的碎片并回上一句
            if merged and x[0] in _CLOSERS:
                merged[-1] += x
            elif merged and len(x.strip()) <= 3 and not re.search(r"[\u4e00-\u9fa5]", x):
                merged[-1] += x                     # 纯标点碎片也并回去
            else:
                merged.append(x)
        for x in merged:
            x = x.strip()
            if x:
                out.append({"p": pi, "t": x, "head": False})
    return out


def _find_locate(sents, evidence):
    """采分点的原文依据 → 落到哪几句上。整句包含、或句子被依据包含，都算。"""
    ev = re.sub(r"\s", "", evidence)
    hit = []
    for i, s in enumerate(sents):
        t = re.sub(r"\s", "", s["t"])
        if not t:
            continue
        if t in ev or ev in t:
            hit.append(i)
    return hit


def _find_build(db, uid_, qtype, stem, material, full, wmin, wmax, source, requirement=""):
    """材料 + 题干 → AI 标出采分点（逐字依据），存成一套可判的题。"""
    name, dfull, dmin, dmax = FIND_TYPES[qtype][0], FIND_TYPES[qtype][1], FIND_TYPES[qtype][2], FIND_TYPES[qtype][3]
    pts_full = full or dfull
    if qtype == "guanche":                          # 贯彻执行：格式另占约 1/4，采分点只分内容那部分
        pts_full = pts_full - max(2, round(pts_full * 0.25))
    prompt = (
        "下面是一道申论**%s**的给定资料和题干。请像阅卷组一样，把**采分点**标出来。\n\n"
        "【题干】%s\n\n【给定资料】\n%s\n\n"
        "【要求】\n"
        "1. 一个采分点 = 一个独立的得分要点。%d 分（内容部分）一般 5~8 个点。\n"
        "2. 每个点给：\n"
        "   · point：概括后的要点表述（12~30 字，这是**答案里该写的话**，不是原文）\n"
        "   · evidence：这个点在材料里的依据，**从材料里逐字复制**（一句或连续两句，"
        "一字不差，含标点）—— 对不上原文的点我会直接丢掉\n"
        "   · score：分值（所有点加起来 = %d 分）\n"
        "3. **材料里有干扰信息**（背景铺垫、无关细节、重复表述），不要把它们标成采分点。\n"
        "4. 同一个意思在材料里出现两次的，**只标一个点**，evidence 取最完整的那处。\n\n"
        '只输出 JSON：{"points":[{"point":"","evidence":"","score":0}]}'
        % (name, stem, material[:8000], pts_full, pts_full))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组组长。采分点的依据必须逐字来自材料，"
                                       "绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=2500, timeout=300, json_mode=True)
    if err:
        return None, err
    try:
        got = json.loads(rep).get("points") or []
    except Exception:
        return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)

    sents = _find_sents(material)
    flat = re.sub(r"\s", "", material)
    points = []
    for p in got:
        ev = (p.get("evidence") or "").strip()
        pt = (p.get("point") or "").strip()
        if not ev or not pt:
            continue
        if re.sub(r"\s", "", ev) not in flat:      # 对不上原文的直接丢（宁可少，不能错）
            continue
        hit = _find_locate(sents, ev)
        if not hit:
            continue
        points.append({"point": pt, "evidence": ev, "score": float(p.get("score") or 0), "sents": hit})
    if len(points) < 3:
        return None, (jsonify({"error": "AI 标出的采分点太少或对不上原文，请重试"}), 502)

    cur = db.execute(
        "INSERT INTO find_papers(user_id,qtype,type_name,stem,requirement,full,word_min,word_max,"
        "material,points,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (uid_, qtype, name, stem, requirement, full or dfull, wmin or dmin, wmax or dmax,
         material, json.dumps(points, ensure_ascii=False), source))
    db.commit()
    return cur.lastrowid, None


@bp.get("/api/find/types")
def find_types():
    db = get_db()
    n = {r["qtype"]: r["c"] for r in db.execute(
        "SELECT qtype, COUNT(*) c FROM find_papers WHERE user_id=? GROUP BY qtype", (uid(),))}
    return jsonify({"types": [
        {"key": k, "name": v[0], "full": v[1], "word_min": v[2], "word_max": v[3],
         "tip": v[4], "n": n.get(k, 0)} for k, v in FIND_TYPES.items()],
        # 贯彻执行题的文种（供前端选：写哪种公文）
        "doctypes": [{"k": d["k"], "cat": d["cat"], "min": d["min"], "max": d["max"]} for d in GW_DOCTYPES]})


def _find_fit_words(base_prompt, lo, hi, sys, tries=1, temperature=0.78):
    """出一则材料并把字数收进 [lo,hi]（对齐真题单则体量）。模型对「多少字」很不敏感，
    一次说不管用 → 实测字数后带上这一稿要求扩/缩，返工。返回正文（失败给最接近的一稿）。"""
    target = lo + int((hi - lo) * 0.5)
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": base_prompt}]
    best = ""
    for _ in range(tries + 1):
        rep, err = _ai_call_or_error(msgs, temperature=temperature,
                                     max_tokens=max(1400, int(hi * 2.4)), timeout=300)
        if err:
            break
        txt = re.sub(r"[*#`]+", "", (rep or "")).strip()
        n = _sl_words(txt)
        if lo <= n <= hi:
            return txt
        if not best or abs(n - target) < abs(_sl_words(best) - target):
            best = txt
        how = "扩写到" if n < lo else "压缩到"
        msgs = msgs[:1] + [
            {"role": "user", "content": base_prompt},
            {"role": "assistant", "content": txt},
            {"role": "user", "content": "这一稿 %d 字，不符合要求。请%s %d~%d 字（目标 %d 字），"
                                        "保持内容与结构，只输出正文。" % (n, how, lo, hi, target)}]
    return best


# 材料与题型一一对应，字数对齐真题：查 2025 四川省考、2026 国考真题——一道小题对应的
# 「给定资料N」通常由 2~4 则子材料组成、总量约 1800~2500 字（如国考归纳概括的给定资料1≈1800 字、
# 综合分析的给定资料2≈2100 字、提出对策的给定资料4≈2000 字）。所以按「多则、每则真题体量、
# 总量到位」出：3 则、每则约 550~750 字、合计约 1700~2200 字。
_FIND_MAT_SPEC = {
    "guina": (3, (520, 740), [
        "某地区/某单位在这方面的【具体做法与措施】：有主体、有动作、有数据、有干部或群众原话",
        "另一处的【做法与成效】：换个地方/主体，做法各有侧重，穿插一些无关背景作干扰",
        "第三处的【经验或问题】：或再补一个典型案例，或点出推进中的困难与短板（掺入干扰信息）"]),
    "zonghe": (3, (560, 780), [
        "摆出要分析的【现象 / 观点 / 一句话】本身：它是什么、从哪来、有哪些具体表现（事实、数据、场景）",
        "围绕它的【不同角度看法与成因】：不同主体怎么看、为什么会这样、正反两面（供『为什么』层）",
        "它的【影响、意义与走向】：带来了什么、启示是什么、该怎么办（供『怎么样』层，掺入干扰信息）"]),
    "duice": (3, (520, 740), [
        "这个话题当前存在的【问题 / 困难 / 矛盾 / 短板】：具体是什么、卡在哪、谁受影响，有一线声音和数据",
        "另一类【问题及其成因】：换个侧面把问题铺清楚（对策要从问题里长出来）",
        "相关【背景、零散做法或他山之石】：可借鉴的经验，并掺入【无关细节、同义重复】作干扰"]),
    "guanche": (3, (620, 820), [
        "这件事的【背景与基本情况】：来龙去脉、现状、有关数据（写公文的由头/依据都从这里来）",
        "各方的【具体做法 / 举措 / 经验】：分主体、有细节、有原话，是公文正文要点的主要来源",
        "【成效、问题与各方反响】：做出了什么效果、还存在什么问题（掺入干扰信息，供辨别取舍）"]),
}


def _find_gen_stem(name, full, wmin, wmax, tip, topic, material, doctype=""):
    """据材料 + 题型出一句题干（贴合材料内容）。贯彻执行题另指定文种 + 身份。"""
    if doctype:                                       # 贯彻执行：设身份、指定文种、按文种字数
        spec = GW_MAP.get(doctype, {})
        demo = spec.get("demo") or {}
        role, aud = demo.get("role") or "相关工作人员", demo.get("audience") or ""
        prompt = ("给一道申论**贯彻执行题**命制**题干**：设定一个身份，让考生根据给定资料撰写一份**%s**，"
                  "紧扣材料内容。参考身份「%s」%s。\n话题：%s。\n"
                  "按真题写法输出（形如「假如你是……，请根据给定资料，撰写一份%s。（%d 分）要求："
                  "格式规范、要点全面、条理清晰，不超过 %d 字。」），只输出题干本身，不要引号、不要解释。"
                  "\n\n给定资料节选：\n%s"
                  % (doctype, role, ("，面向「%s」" % aud if aud else ""), topic,
                     doctype, full, wmax, material[:1200]))
    else:
        prompt = ("给下面这道申论**%s**（%d 分，答案 %d~%d 字）命制**题干**：一句话，明确作答对象和范围，"
                  "紧扣给定资料的内容。%s\n话题：%s。\n"
                  "按真题写法输出（含「根据给定资料」「（%d 分）」「要求：…不超过 %d 字」这类），"
                  "只输出题干本身，不要引号、不要解释。\n\n给定资料节选：\n%s"
                  % (name, full, wmin, wmax, tip, topic, full, wmax, material[:1200]))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论命题人，题干简洁规范。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=260)
    if err:
        return "", err
    stem = re.sub(r"[*#`]+", "", (rep or "")).strip().split("\n")[0].strip()
    if not stem:
        if doctype:
            stem = ("假如你是相关工作人员，请根据给定资料，撰写一份%s。（%d 分）"
                    "要求：格式规范、要点全面、条理清晰，不超过 %d 字。" % (doctype, full, wmax))
        else:
            stem = "根据给定资料，完成本题。（%d 分）要求：全面、准确、有条理，不超过 %d 字。" % (full, wmax)
    return stem, None


def _find_gen_material(qtype, name, full, wmin, wmax, tip, topic, doctype=""):
    """按【题型】出对应的给定资料 —— 每则都对齐真题单则字数（用户要求：宁可少出、每则要够）。
    再据材料出题干。返回 (material, stem, err)。贯彻执行题另传文种 doctype。"""
    n_pass, per, angles = _FIND_MAT_SPEC.get(qtype, _FIND_MAT_SPEC["guina"])
    lo, hi = per
    sys = ("你是申论命题人。给定资料贴近国考/省考真题：**单则材料就有真题的体量（%d~%d 字）**，"
           "有具体地名、人名、数据、对话，并**掺入干扰信息**（背景铺垫、无关细节、同义重复、反面例子）"
           "供考生练找点。直接输出材料正文，不要「材料N」标题、不要 Markdown 记号。" % (lo, hi))
    if doctype:                                       # 贯彻执行：材料要能支撑该文种的写作
        sys += "这份给定资料将用于让考生写一篇「%s」，材料要提供足够支撑该文种的素材（由头、要点、事例）。" % doctype
    passages, sofar = [], []
    for i in range(n_pass):
        angle = angles[i % len(angles)]
        avoid = ("（避免和已写材料重复主旨：" + "；".join(sofar) + "）") if sofar else ""
        p = ("请命制一份申论试卷的「给定资料」中的一则，主题：%s，服务于一道**%s**。\n"
             "本则材料写：%s%s\n"
             "字数 %d~%d 字（对齐真题单则材料体量，硬性要求，别写短）。" %
             (topic, name, angle, avoid, lo, hi))
        txt = _find_fit_words(p, lo, hi, sys)
        if txt:
            passages.append(txt)
            sofar.append(txt[:40])
    if not passages:
        return None, None, (jsonify({"error": "AI 没出好材料，请重试"}), 502)
    cn = "一二三四五六七八九十"
    material = "\n\n".join("材料%s\n%s" % (cn[i] if i < len(cn) else str(i + 1), t)
                           for i, t in enumerate(passages))
    stem, err = _find_gen_stem(name, full, wmin, wmax, tip, topic, material, doctype)
    if err:
        return None, None, err
    return material, stem, None


@bp.post("/api/find/gen")
def find_gen():
    """AI 按考试标准出一道：先造材料（含干扰信息、够真题字数），再标采分点。"""
    d = request.get_json(silent=True) or {}
    qtype = (d.get("qtype") or "guina").strip()
    if qtype not in FIND_TYPES:
        return jsonify({"error": "题型不对"}), 400
    topic = (d.get("topic") or "").strip()
    name, full, wmin, wmax, tip = FIND_TYPES[qtype]

    doctype = ""
    if qtype == "guanche":                           # 贯彻执行：定文种，字数按该文种真题规格走
        doctype = (d.get("doctype") or "").strip()
        if doctype not in GW_MAP:
            doctype = random.choice(GW_DOCTYPES)["k"]  # 没指定就随机挑一个文种
        wmin, wmax = GW_MAP[doctype]["min"], GW_MAP[doctype]["max"]

    db = get_db()
    if not topic:                                    # 话题从最近的时政/概括句里挑，贴近真考
        r = db.execute("SELECT topic FROM gaikuo_items WHERE topic!='' "
                       "ORDER BY RANDOM() LIMIT 1").fetchone()
        topic = r[0] if r else "基层治理"

    material, stem, err = _find_gen_material(qtype, name, full, wmin, wmax, tip, topic, doctype)
    if err:
        return err

    src = "AI 命题 · " + (doctype + " · " if doctype else "") + topic
    pid, err = _find_build(db, uid(), qtype, stem, material, full, wmin, wmax, src)
    if err:
        return err
    return jsonify({"id": pid}), 201


@bp.get("/api/find/papers")
def find_papers():
    rows = get_db().execute(
        "SELECT id,qtype,type_name,stem,full,source,created_at,"
        "(SELECT COUNT(*) FROM find_records r WHERE r.paper_id=find_papers.id) done "
        "FROM find_papers WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


def _find_paper(db, pid):
    r = db.execute("SELECT * FROM find_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    return r


@bp.get("/api/find/paper/<int:pid>")
def find_paper(pid):
    """做题用：只给材料（按句切好）和题干 —— **采分点绝不下发**，否则前端一翻就看见答案了。"""
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    sents = _find_sents(r["material"])
    npt = len(json.loads(r["points"] or "[]"))
    doctype = _find_doctype(r)                         # 贯彻执行题：认出文种，把格式骨架带给前端
    return jsonify({"id": r["id"], "qtype": r["qtype"], "type_name": r["type_name"],
                    "stem": r["stem"], "full": r["full"],
                    "word_min": r["word_min"], "word_max": r["word_max"],
                    "source": r["source"], "n_points": npt,
                    "material_words": _sl_words(r["material"]),   # 给定资料总字数（像范文推荐那样显示）
                    "doctype": doctype,
                    "doctype_fmt": (GW_MAP.get(doctype, {}).get("fmt", "") if doctype else ""),
                    "sents": [{"i": i, "p": s["p"], "t": s["t"]} for i, s in enumerate(sents)]})


@bp.post("/api/find/check")
def find_check():
    """第一步判定：我勾画的这些句子，找对了没有？找漏了什么？找错了什么？找重了什么？"""
    d = request.get_json(silent=True) or {}
    pid = int(d.get("paper_id") or 0)
    picked = sorted({int(x) for x in (d.get("sents") or [])})
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    if not picked:
        return jsonify({"error": "先在材料里勾画你认为的要点句"}), 400
    points = json.loads(r["points"] or "[]")
    sents = _find_sents(r["material"])

    hit_by_point = []          # 每个采分点被我勾中了几句
    for p in points:
        ps = set(p["sents"])
        got = [i for i in picked if i in ps]
        hit_by_point.append(got)

    got_points = [i for i, g in enumerate(hit_by_point) if g]
    missed = [i for i, g in enumerate(hit_by_point) if not g]
    # 找错：勾了但不属于任何采分点 —— 这就是被干扰信息骗了
    all_pt_sents = {i for p in points for i in p["sents"]}
    wrong = [i for i in picked if i not in all_pt_sents]
    # 找重：同一个采分点勾了不止一句（同义重复／把整段都涂了）
    dup = [{"point": points[i]["point"], "sents": g} for i, g in enumerate(hit_by_point) if len(g) > 1]

    acc = round(100.0 * len(got_points) / len(points)) if points else 0
    return jsonify({
        "total": len(points), "found": len(got_points), "acc": acc,
        "ok": [{"point": points[i]["point"], "score": points[i]["score"],
                "sents": hit_by_point[i]} for i in got_points],
        "missed": [{"point": points[i]["point"], "score": points[i]["score"],
                    "sents": points[i]["sents"],
                    "evidence": points[i]["evidence"]} for i in missed],
        "wrong": [{"i": i, "t": sents[i]["t"]} for i in wrong if i < len(sents)],
        "dup": dup,
    })


def _find_doctype(r):
    """贯彻执行题：从题干里认出是哪种文种（AI 命题和上传真题都靠题干判）。返回文种名或 ''。"""
    if r["qtype"] != "guanche":
        return ""
    stem = r["stem"] or ""
    # 题干通常写「撰写一份短评/调研报告…」；长名优先，免得「报告」先命中把「调研报告」盖掉
    for k in sorted(GW_MAP.keys(), key=len, reverse=True):
        if k in stem:
            return k
    return ""


@bp.post("/api/find/grade")
def find_grade():
    """第二步判定：照着找到的点写出来的答案，概括到不到位。贯彻执行题另判格式。"""
    d = request.get_json(silent=True) or {}
    pid = int(d.get("paper_id") or 0)
    answer = (d.get("answer") or "").strip()
    picked = sorted({int(x) for x in (d.get("sents") or [])})
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    if len(answer) < 20:
        return jsonify({"error": "答案太短了"}), 400
    points = json.loads(r["points"] or "[]")
    std = "\n".join("%d. %s（%g 分）依据：%s" % (i + 1, p["point"], p["score"], p["evidence"][:60])
                    for i, p in enumerate(points))

    # 贯彻执行题：除了内容采分点，还要判「格式」（标题/称谓/正文结构/落款是否合该文种），并**计入总分**
    doctype = _find_doctype(r)
    fmt_rule, fmt_json, fmt_full = "", "", 0
    if doctype:
        spec = GW_MAP.get(doctype, {})
        fmt_full = max(2, round(int(r["full"]) * 0.25))     # 格式占约 1/4（20 分题≈5 分格式 + 15 分内容）
        fmt_rule = (
            "\n5. 【这是贯彻执行题，还要判格式】文种：%s。该文种的规范格式骨架：%s。\n"
            "   逐项检查考生答案是否具备这些格式要件（标题、称谓、正文的分层结构、落款/署名日期等，"
            "视文种而定），有的算 ok、缺的或写错的算 miss，给一个总体档次。\n"
            "   **格式满分 %d 分**，按规范程度给 format.score（0~%d）。内容采分点的得分照常填在 items 和 score 里，"
            "两者分开算。\n"
            % (doctype, spec.get("fmt", ""), fmt_full, fmt_full))
        fmt_json = ('"format":{"doctype":"%s","score":0,"ok":["具备的格式要件"],"miss":["缺失/写错的格式要件"],'
                    '"grade":"优|良|中|差","comment":"一句话点评格式规范程度"},') % doctype

    style_note = ("有没有抄原文、有没有加自己的评论（归纳概括题不许评价）、有没有分条、"
                  "字数够不够（当前 %d 字）" % len(re.sub(r"\s", "", answer)))
    if doctype:
        style_note = "语言是否得体（贯彻执行讲究语气和对象感）、有没有抄原文、字数够不够（当前 %d 字）" \
            % len(re.sub(r"\s", "", answer))

    prompt = (
        "批改一道申论**%s**（%d 分，要求 %d~%d 字）。\n\n"
        "【题干】%s\n\n"
        "【采分点】（阅卷标准，考生看不到）\n%s\n\n"
        "【考生答案】\n%s\n\n"
        "【怎么批】\n"
        "1. 逐个采分点判：**写到了 / 沾边但不到位 / 没写**。判「写到了」的标准是"
        "**意思对上**，不要求用词一样。\n"
        "2. 「沾边但不到位」要说清差在哪：是抄原文没概括？是几个点并成了一坨？"
        "还是漏了关键限定词？\n"
        "3. 另外指出**表述问题**：%s。\n"
        "4. 给分要实在，别送分。%s\n\n"
        "只输出 JSON：\n"
        '{"score":0,"items":[{"point":"采分点原话","got":"full|part|miss","score":0,'
        '"comment":"一句话说清写到没写到、差在哪"}],'
        '%s"style":["表述问题，每条一句话"],"advice":"一句话：下次怎么改进"}'
        % (r["type_name"], r["full"], r["word_min"], r["word_max"], r["stem"], std, answer,
           style_note, fmt_rule, fmt_json))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组组长。逐个采分点对照批改，"
                                       "给分实在，说清差在哪。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=2500, timeout=300, json_mode=True)
    if err:
        return err
    try:
        g = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    if doctype and fmt_full:
        # 贯彻执行：总分 = 内容（按采分点得分，折算到 full-fmt_full）+ 格式（0~fmt_full）
        content_full = sum(float(p.get("score") or 0) for p in points) or float(r["full"])
        content_raw = float(g.get("score") or 0)                  # AI 给的内容采分点得分合计
        content_target = int(r["full"]) - fmt_full
        content_final = round(content_raw / content_full * content_target, 1) if content_full else 0
        fm = g.get("format") or {}
        fmt_score = max(0.0, min(float(fmt_full), float(fm.get("score") or 0)))
        fm["score"], fm["full"] = round(fmt_score, 1), fmt_full
        g["format"] = fm
        g["content_score"], g["content_full"] = content_final, content_target
        g["score"] = round(content_final + fmt_score, 1)
    score = float(g.get("score") or 0)
    db.execute("INSERT INTO find_records(user_id,paper_id,marks,find_result,answer,grade,score,full) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (uid(), pid, json.dumps(picked), json.dumps(d.get("find_result") or {}, ensure_ascii=False),
                answer, json.dumps(g, ensure_ascii=False), score, r["full"]))
    db.commit()
    g["full"] = r["full"]
    return jsonify(g)


@bp.get("/api/find/records")
def find_records_list():
    """找点/写点的历史记录：每次批改留一条，可回看。贯彻执行题带内容/格式分。"""
    rows = get_db().execute(
        "SELECT r.id, r.paper_id, r.score, r.full, r.grade, r.created_at, "
        "p.qtype, p.type_name, p.stem, p.source "
        "FROM find_records r JOIN find_papers p ON p.id=r.paper_id "
        "WHERE r.user_id=? ORDER BY r.id DESC LIMIT 80", (uid(),)).fetchall()
    out = []
    for r in rows:
        d = {"id": r["id"], "paper_id": r["paper_id"], "score": r["score"], "full": r["full"],
             "qtype": r["qtype"], "type_name": r["type_name"], "stem": (r["stem"] or "")[:52],
             "source": r["source"] or "", "created_at": r["created_at"]}
        try:                                          # 贯彻执行：从批改 JSON 里取内容/格式分
            g = json.loads(r["grade"] or "{}")
            fm = g.get("format")
            if g.get("content_score") is not None and fm:
                d.update(content_score=g.get("content_score"), content_full=g.get("content_full"),
                         format_score=fm.get("score"), format_full=fm.get("full"),
                         doctype=fm.get("doctype"), format_grade=fm.get("grade"))
        except Exception:
            log.warning("find 记录的 grade JSON 解析失败，这条会少字段", exc_info=True)
        out.append(d)
    return jsonify({"items": out})


@bp.get("/api/find/record/<int:rid>")
def find_record(rid):
    """一条历史记录的详情：题干 + 完整批改（采分点/格式）+ 我写的答案。"""
    r = get_db().execute(
        "SELECT r.id, r.paper_id, r.score, r.full, r.grade, r.answer, r.created_at, "
        "p.qtype, p.type_name, p.stem, p.word_min, p.word_max, p.source "
        "FROM find_records r JOIN find_papers p ON p.id=r.paper_id "
        "WHERE r.id=? AND r.user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({"id": r["id"], "paper_id": r["paper_id"], "score": r["score"], "full": r["full"],
                    "qtype": r["qtype"], "type_name": r["type_name"], "stem": r["stem"],
                    "word_min": r["word_min"], "word_max": r["word_max"], "source": r["source"] or "",
                    "answer": r["answer"] or "", "created_at": r["created_at"],
                    "grade": json.loads(r["grade"] or "{}")})


@bp.post("/api/find/upload")
def find_upload():
    """上传真题文档 → 拆出材料和小题 → 留归纳概括/综合分析/提出对策/贯彻执行，各标一套采分点（大作文跳过）。
       抽文本、拆题、判题型全部复用真题批改那条管线（_split_paper / _classify_questions）。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    mime = (f.mimetype or "").lower()
    tmp = os.path.join(tempfile.gettempdir(), "find_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    try:
        text = _ocr_image(tmp) if (mime.startswith("image/") or ext in IMAGE_EXT) \
            else _pdf_text_or_ocr(tmp, ext)
    except Exception:
        text = ""
    finally:
        try:
            os.remove(tmp)
        except Exception:
            log.debug("临时文件没删掉", exc_info=True)
    text = (text or "").strip()
    if len(text) < 200:
        return jsonify({"error": "没能从文件里读到足够的文字（扫描件太糊或是纯图片）"}), 400

    material, _qtext, qs = _split_paper(text)
    if not qs:
        return jsonify({"error": "没识别出题目。请确认文件里有「作答要求」部分"}), 400
    cls = _classify_questions(qs)

    db = get_db()
    made, skipped = [], []
    for q in qs:
        c = cls.get(q["seq"], {})
        key = c.get("qtype") or "guina"
        if key not in FIND_TYPES:                 # 大作文不属于「找点」训练（贯彻执行已纳入）
            skipped.append(_SL_TYPES.get(key, {}).get("name") or key)
            continue
        lo, hi = _sl_word_range(q["body"])
        m = _SL_SCORE.search(q["body"])
        full = int(m.group(1)) if m else int(c.get("full") or FIND_TYPES[key][1])
        pid, err = _find_build(db, uid(), key, q["body"][:1200], material, full,
                               lo or int(c.get("word_min") or 0), hi or int(c.get("word_max") or 0),
                               "真题 · " + os.path.splitext(f.filename)[0][:40])
        if not err:
            made.append({"id": pid, "type": FIND_TYPES[key][0], "seq": q["seq"]})
    if not made:
        return jsonify({"error": "这份卷子里没有归纳概括/综合分析/提出对策/贯彻执行题"
                                 + ("（识别到：%s）" % "、".join(skipped) if skipped else "")}), 400
    return jsonify({"made": made, "skipped": skipped}), 201


@bp.post("/api/shenlun/paper/upload")
def shenlun_paper_upload():
    """上传真题（PDF/Word/图片/文本）→ 拆出给定资料与各小题，自动判题型和字数要求。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    mime = (f.mimetype or "").lower()
    tmp = os.path.join(tempfile.gettempdir(), "slpaper_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    try:
        if mime.startswith("image/") or ext in IMAGE_EXT:
            text = _ocr_image(tmp)
        else:
            text = _pdf_text_or_ocr(tmp, ext)
    except Exception:
        # 回给用户的是「扫描件太糊」，可真实原因也可能是 OCR 引擎挂了/依赖缺失——
        # 那句提示会把人往错方向带，真因得留在日志里。
        log.warning("申论卷解析失败 %s，将按「读不到文字」回给用户", f.filename, exc_info=True)
        text = ""
    finally:
        try:
            os.remove(tmp)
        except Exception:
            log.debug("临时文件没删掉", exc_info=True)
    text = (text or "").strip()
    if len(text) < 200:
        return jsonify({"error": "没能从文件里读到足够的文字（扫描件太糊或是纯图片）"}), 400

    material, qtext, qs = _split_paper(text)
    if not qs:
        return jsonify({"error": "没识别出题目。请确认文件里有「作答要求」部分"}), 400
    cls = _classify_questions(qs)

    title = (request.form.get("title") or "").strip() or os.path.splitext(f.filename)[0][:60]
    db = get_db()
    cur = db.execute("INSERT INTO shenlun_papers(user_id,title,material,source) VALUES(?,?,?,?)",
                     (uid(), title, material[:60000], f.filename))
    pid = cur.lastrowid
    for q in qs:
        c = cls.get(q["seq"], {})
        key = c.get("qtype") if c.get("qtype") in _SL_TYPES else "guina"
        t = _SL_TYPES[key]
        lo, hi = _sl_word_range(q["body"])
        lo = lo or int(c.get("word_min") or 0) or t["word_min"]
        hi = hi or int(c.get("word_max") or 0) or t["word_max"]
        m = _SL_SCORE.search(q["body"])
        full = int(m.group(1)) if m else int(c.get("full") or t["full"])
        db.execute("INSERT INTO shenlun_questions(paper_id,seq,qtype,type_name,stem,requirement,"
                   "full,word_min,word_max) VALUES(?,?,?,?,?,?,?,?,?)",
                   (pid, q["seq"], key, t["name"], q["body"][:3000], "", full, lo, hi))
    db.commit()
    return jsonify(_paper_detail(db, pid)), 201


def _paper_detail(db, pid):
    p = db.execute("SELECT * FROM shenlun_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    if not p:
        return None
    qs = db.execute("SELECT * FROM shenlun_questions WHERE paper_id=? ORDER BY seq", (pid,)).fetchall()
    best = {}
    for r in db.execute("SELECT question_id, id, score, full FROM shenlun_grade "
                        "WHERE user_id=? AND paper_id=? ORDER BY id", (uid(), pid)):
        best[r["question_id"]] = {"grade_id": r["id"], "score": r["score"], "full": r["full"]}
    def clean_q(q):
        q = dict(q)
        q["body"] = _strip_artifacts(q.get("body") or "")
        return dict(q, done=best.get(q["id"]))
    # 老数据也顺手洗一遍：页眉页脚 / 答题卡行号去掉，材料硬换行拼回自然段
    return {"id": p["id"], "title": p["title"],
            "material": _reflow(_strip_artifacts(p["material"] or "")),
            "created_at": p["created_at"],
            "questions": [clean_q(q) for q in qs]}


@bp.get("/api/shenlun/papers")
def shenlun_papers():
    rows = get_db().execute(
        "SELECT p.id, p.title, p.created_at,"
        "(SELECT COUNT(*) FROM shenlun_questions q WHERE q.paper_id=p.id) total,"
        "(SELECT COUNT(DISTINCT g.question_id) FROM shenlun_grade g "
        " WHERE g.paper_id=p.id AND g.user_id=p.user_id) done "
        "FROM shenlun_papers p WHERE p.user_id=? ORDER BY p.id DESC LIMIT 40", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/shenlun/paper/<int:pid>")
def shenlun_paper(pid):
    d = _paper_detail(get_db(), pid)
    return (jsonify(d), 200) if d else (jsonify({"error": "未找到"}), 404)


@bp.delete("/api/shenlun/paper/<int:pid>")
def shenlun_paper_del(pid):
    db = get_db()
    if not db.execute("SELECT 1 FROM shenlun_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone():
        return jsonify({"error": "未找到"}), 404
    db.execute("DELETE FROM shenlun_questions WHERE paper_id=?", (pid,))
    db.execute("DELETE FROM shenlun_papers WHERE id=?", (pid,))
    db.execute("UPDATE shenlun_grade SET paper_id=NULL, question_id=NULL WHERE paper_id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


def _gen_reference(t, question, material, wmin, wmax, tries=2):
    """单独生成参考范文，按题目要求的字数区间严格校验，超/欠就让它重写。
    塞进批改那个 JSON 里是行不通的——模型为了不把 JSON 撑爆，总会把范文写短。"""
    target = wmin + int((wmax - wmin) * 0.4)      # 目标压在区间偏下，模型习惯性写多
    is_essay = t["key"] == "zuowen"
    frame = ("按「开头点题 — 分论点1 — 分论点2 — 分论点3 — 结尾升华」写一篇完整议论文，自拟标题。"
             if is_essay else "按该题型的规范答案框架分条作答，要点齐全、语言书面化。")
    mat = ("【给定资料】\n" + material[:9000]) if material else ""
    base = ("你是申论阅卷老师，现在写一份可以拿满分的参考答案。\n\n【题干】\n%s\n\n%s\n\n"
            "%s\n题目要求字数 %d~%d 字，请写到 %d 字左右——字数是硬性要求，宁可略少也不要超。\n"
            "只输出答案正文：不要 Markdown 记号（不要 ** ##），不要任何解释、标注或字数统计。" %
            (question[:2000], mat, frame, wmin, wmax, target))
    msgs = [{"role": "system", "content": "你是资深申论老师，参考答案规范、切题、字数精准。"},
            {"role": "user", "content": base}]
    best, budget = "", max(1200, int(wmax * 2.2))
    for _ in range(tries + 1):
        rep, err = _ai_call_or_error(msgs, temperature=0.4, max_tokens=budget, timeout=300)
        if err:
            break
        ref = re.sub(r"[*#`]+", "", rep).strip()
        n = _sl_words(ref)
        if wmin <= n <= wmax:
            return ref
        # 留着离区间最近的那版兜底
        if not best or _sl_gap(n, wmin, wmax) < _sl_gap(_sl_words(best), wmin, wmax):
            best = ref
        how = "扩写到" if n < wmin else "压缩到"
        msgs = msgs[:1] + [
            {"role": "user", "content": base},
            {"role": "assistant", "content": ref},
            {"role": "user", "content": "这份答案 %d 字，不符合要求。请%s %d~%d 字（目标 %d 字），"
                                        "保持要点与结构，只输出答案正文。" % (n, how, wmin, wmax, target)}]
    return best


def _sl_gap(n, lo, hi):
    return 0 if lo <= n <= hi else (lo - n if n < lo else n - hi)


# 大作文固定四维（与主流阅卷口径一致，合计 35 分）
_SL_DIMS = [("立意", 10), ("结构", 7), ("论证与材料运用", 10), ("语言", 8)]

SL_SYS = ("你是阅卷经验丰富的申论老师，严格对照给定资料的采分点批改，只认材料里有的要点，"
          "不编造材料里没有的内容。评分克制、有依据，严格输出 JSON。")


@bp.post("/api/shenlun/grade")
def shenlun_grade():
    """逐点批改：像阅卷老师一样对照采分点，逐条说清答到没答到、错在哪、怎么补。
    传 question_id 时，题干/材料/满分/字数要求都从真题卷里取，批完顺带告诉前端下一题是哪道。"""
    d = request.get_json(silent=True) or {}
    db = get_db()

    qrow = None
    qid = int(d.get("question_id") or 0)
    if qid:
        qrow = db.execute(
            "SELECT q.*, p.material, p.id pid FROM shenlun_questions q "
            "JOIN shenlun_papers p ON p.id=q.paper_id WHERE q.id=? AND p.user_id=?",
            (qid, uid())).fetchone()
        if not qrow:
            return jsonify({"error": "题目不存在"}), 404

    key = (qrow["qtype"] if qrow else (d.get("type") or "")).strip()
    t = _SL_TYPES.get(key)
    if not t:
        return jsonify({"error": "请选择题型"}), 400

    question = (qrow["stem"] if qrow else (d.get("question") or "")).strip()
    material = (qrow["material"] if qrow else (d.get("material") or "")).strip()
    answer = (d.get("answer") or "").strip()
    if not question:
        return jsonify({"error": "请填写题干"}), 400
    if len(answer) < 10:
        return jsonify({"error": "请填写你的答案（至少 10 个字）"}), 400

    full = int((qrow["full"] if qrow else 0) or d.get("full") or t["full"])
    wmin = int((qrow["word_min"] if qrow else 0) or d.get("word_min") or t["word_min"])
    wmax = int((qrow["word_max"] if qrow else 0) or d.get("word_max") or t["word_max"])
    words = _sl_words(answer)

    is_essay = key == "zuowen"
    if is_essay:
        dims = "、".join("%s（0-%d 分）" % (n, m) for n, m in _SL_DIMS)
        rubric = ("按固定的四个维度打分，points 里每个维度一条，顺序不变：%s。\n"
                  "（若本题满分不是 35 分，请按比例折算各维度满分。）\n"
                  'name=维度名，max=该维度满分，got=实际得分，yours=引用考生原文中最能体现该维度的一句，\n'
                  'hits=做得好的地方，misses=扣分点，material=（留空字符串）。' % dims)
    else:
        rubric = ("先从给定资料中提炼出这道题的采分点（每个采分点一条），再逐条对照考生答案：\n"
                  'name=采分点名（如「总领」「接近、启发村民」），max=该点分值，got=实际得分，\n'
                  'yours=考生答案里对应这一点的原文（没写到就填空字符串），\n'
                  'hits=已写到的要点，misses=未写到的要点，partial=部分写到的要点，\n'
                  'material=支撑这个采分点的给定资料原文（务必逐字摘自材料）。')

    # 字数是硬性要求，超/欠都要在「语言」或总分上体现
    wtip = ("本题要求 %d~%d 字，考生实际写了 %d 字。%s\n" %
            (wmin, wmax, words,
             "字数达标。" if wmin <= words <= wmax else
             ("字数不足，请在评分与建议中指出。" if words < wmin else "字数超出，请在评分与建议中指出。")))

    mat = ("【给定资料】\n" + material[:9000]) if material else "（考生没有提供给定资料，请基于题干与常识判断，material 一律留空）"
    prompt = (
        "题型：%s（满分 %d 分）\n\n【题干】\n%s\n\n%s\n\n%s\n【考生答案】（%d 字）\n%s\n\n"
        "%s\n\n"
        "另外给出 advice（不超过 3 条、具体可操作的改进建议）、level（优秀/达标/待提升）。\n"
        "points 不超过 6 条，每条 material 摘录不超过 80 字。不要输出参考答案。\n"
        '严格只输出这个结构的 JSON：{"score":9,"full":%d,"level":"优秀","points":[{"name":"","max":2,"got":1,'
        '"yours":"","hits":[],"misses":[],"partial":[],"material":""}],"advice":[]}'
        % (t["name"], full, question[:2000], mat, wtip, words, answer[:8000], rubric, full))

    msgs = [{"role": "system", "content": SL_SYS}, {"role": "user", "content": prompt}]
    res = None
    for attempt in range(2):
        rep, err = _ai_call_or_error(msgs, temperature=0.2, max_tokens=4000,
                                     timeout=300, json_mode=True)
        if err:
            return err
        try:
            res = json.loads(rep)
            break
        except Exception:
            msgs = msgs[:2] + [
                {"role": "assistant", "content": rep[:200]},
                {"role": "user", "content": "上次的 JSON 没有输出完整。请重新输出完整、合法的 JSON："
                                            "points 精简到 4 条、每条 hits/misses 各不超过 2 句、material 不超过 40 字。"}]
    if res is None:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    # 参考范文单独生成：塞进同一个 JSON 里，模型为了不超长会把范文写短，字数根本压不住
    res["reference"] = _gen_reference(t, question, material, wmin, wmax)

    res["full"] = full
    try:
        res["score"] = max(0, min(full, float(res.get("score") or 0)))
    except Exception:
        res["score"] = 0
    pts = res.get("points") or []
    res["hit_n"] = sum(1 for p in pts if not (p.get("misses") or p.get("partial")))
    res["part_n"] = sum(1 for p in pts if p.get("partial"))
    res["miss_n"] = sum(1 for p in pts if p.get("misses") and not p.get("yours"))
    res.update({"words": words, "word_min": wmin, "word_max": wmax,
                "ref_words": _sl_words(res.get("reference") or ""),
                "question": question, "material": material, "answer": answer,
                "type_name": t["name"], "qtype": key})

    cur = db.execute(
        "INSERT INTO shenlun_grade(user_id,qtype,type_name,question,material,answer,score,full,result,"
        "paper_id,question_id,words,word_min,word_max) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid(), key, t["name"], question, material, answer, res["score"], full,
         json.dumps(res, ensure_ascii=False),
         qrow["pid"] if qrow else None, qid or None, words, wmin, wmax))
    db.commit()
    res["id"] = cur.lastrowid

    # 做完一题，告诉前端下一题是哪道
    if qrow:
        nx = db.execute("SELECT id, seq, type_name, full FROM shenlun_questions "
                        "WHERE paper_id=? AND seq>? ORDER BY seq LIMIT 1",
                        (qrow["pid"], qrow["seq"])).fetchone()
        res["paper_id"] = qrow["pid"]
        res["seq"] = qrow["seq"]
        res["next"] = dict(nx) if nx else None
    return jsonify(res)


@bp.post("/api/shenlun/record/<int:rid>/reference")
def sl_regen_reference(rid):
    """单独重生成参考范文：批改时这一步是独立的一次 AI 调用，超时/失败就会是空的，
       没必要为了一篇范文把整个批改重跑一遍（那要两次调用）。"""
    db = get_db()
    r = db.execute("SELECT * FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404
    res = json.loads(r["result"] or "{}")
    t = _SL_TYPES.get(r["qtype"]) or {"name": r["type_name"] or "申论", "key": r["qtype"]}
    ref = _gen_reference(t, r["question"] or "", r["material"] or "",
                         r["word_min"] or 200, r["word_max"] or 400)
    if not ref:
        return jsonify({"error": "AI 还是没给出范文，请稍后再试"}), 502
    res["reference"] = ref
    res["ref_words"] = _sl_words(ref)
    db.execute("UPDATE shenlun_grade SET result=? WHERE id=?", (json.dumps(res, ensure_ascii=False), rid))
    db.commit()
    return jsonify({"reference": ref, "ref_words": res["ref_words"]})


@bp.get("/api/shenlun/history")
def shenlun_history():
    rows = get_db().execute(
        "SELECT g.id, g.qtype, g.type_name, substr(g.question,1,60) question, g.score, g.full, "
        "g.words, g.word_min, g.word_max, g.created_at, g.paper_id, g.question_id, "
        "p.title paper_title, q.seq "
        "FROM shenlun_grade g "
        "LEFT JOIN shenlun_papers p ON p.id=g.paper_id "
        "LEFT JOIN shenlun_questions q ON q.id=g.question_id "
        "WHERE g.user_id=? ORDER BY g.id DESC LIMIT 60", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/shenlun/record/<int:rid>")
def shenlun_record(rid):
    db = get_db()
    r = db.execute("SELECT * FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    d = dict(r)
    try:
        d["result"] = json.loads(d["result"])
    except Exception:
        d["result"] = {}
    # 老记录的 result 里没有原题/材料/作答原文，从行里补上，保证回看时四个页签都有内容
    res = d["result"]
    res.setdefault("question", d["question"])
    res.setdefault("material", d["material"])
    res.setdefault("answer", d["answer"])
    res.setdefault("type_name", d["type_name"])
    res.setdefault("words", d.get("words") or _sl_words(d["answer"]))
    res.setdefault("word_min", d.get("word_min"))
    res.setdefault("word_max", d.get("word_max"))
    res["id"] = d["id"]
    if d.get("question_id"):
        nx = db.execute("SELECT id, seq, type_name, full FROM shenlun_questions WHERE paper_id=? AND seq>"
                        "(SELECT seq FROM shenlun_questions WHERE id=?) ORDER BY seq LIMIT 1",
                        (d["paper_id"], d["question_id"])).fetchone()
        res["paper_id"] = d["paper_id"]
        res["next"] = dict(nx) if nx else None
    return jsonify(d)


@bp.delete("/api/shenlun/record/<int:rid>")
def shenlun_record_del(rid):
    db = get_db()
    db.execute("DELETE FROM shenlun_grade WHERE id=? AND user_id=?", (rid, uid()))
    db.commit()
    return jsonify({"ok": True})
