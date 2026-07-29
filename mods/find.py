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


def _lcs_len(a, b):
    """最长公共子串长度（近似匹配用）。句子都不长，O(n*m) 足够。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _find_locate(sents, evidence):
    """采分点的原文依据 → 落到哪几句上。先精确（整句包含/被包含），
    对不齐再兜底：找与依据重合度最高的那句（AI 的依据偶尔略有出入/是跨句概括）。"""
    ev = re.sub(r"\s", "", evidence)
    if not ev:
        return []
    hit = [i for i, s in enumerate(sents)
           if (t := re.sub(r"\s", "", s["t"])) and (t in ev or ev in t)]
    if hit:
        return hit
    # 兜底：逐句取最长公共子串，够长（≥12 字或该句一半）就认它 —— 近似原文也能锚到原句
    best_i, best_ov = -1, 0
    for i, s in enumerate(sents):
        t = re.sub(r"\s", "", s["t"])
        if len(t) < 10:
            continue
        ov = _lcs_len(ev, t)
        if ov > best_ov and ov >= min(12, len(t) // 2):
            best_ov, best_i = ov, i
    return [best_i] if best_i >= 0 else []


# ---------------------------------------------------------------- 采分点的「覆盖度」
# 实测出来的病：采分点会全挤在材料前段。2026 国考副省级第 1 题（H 市城市用光）23 句材料，
# 5 个点全落在句 3~9，句 10~22 连续 13 句零覆盖 —— 智慧照明整段、长效机制整段一个点没标，
# 而这两块正是真题标准答案里的第 4、5 点。另一道 K 市安全生产 48 句，句 0~12 同样零覆盖。
# 成因不是模型笨：是「evidence 必须逐字照抄」这个硬约束，让模型偏向去句式规整、信息密集、
# 好照抄的段落里凑够点数（H 市题里句 3/4/5 本属同一个「规划管控」大点，被拆成三个占满名额），
# 叙述性强、夹引语和设备清单的段落就整段跳过。
# 所以必须有个服务端能算的硬指标，出题时当闸门用，audit 时当验收标准用 —— 两边共用这一个函数。
#
# 为什么按「句索引」分块而不是按自然段：H 市那份材料 OCR 出来只有 2 个自然段（句 0~8 一段、
# 句 9~22 一段），按段扫等于没扫。句索引才是这个模块真正的粒度（勾画粒度也是句）。
_FIND_BLOCK = 7            # 每 7 句算一块（≈ 一个可独立成点的信息单元）
_FIND_GAP_MAX = 8          # 连续 8 句无采分点 = 有整块材料被漏掉
_FIND_COV_MIN = 0.6        # 有点的块数占比低于此 = 找点集中在局部


def _find_coverage(sents, points, block=_FIND_BLOCK):
    """采分点在材料里铺得开不开。只算可勾画的句（标题行不参与）。

    返回 max_gap（最长连续无采分点句数，跟块大小无关，最客观）、coverage（有点块占比）、
    blanks（空白区间 [(起句,止句)]，补点时直接拿它去定向追问）。"""
    idx = [i for i, s in enumerate(sents) if not s.get("head")]
    hit = {i for p in points for i in (p.get("sents") or [])}
    if not idx:
        return {"n_sents": 0, "n_blocks": 0, "cov_blocks": 0, "coverage": 0.0,
                "max_gap": 0, "gap_range": None, "blanks": []}
    blocks = [idx[i:i + block] for i in range(0, len(idx), block)]
    cov = sum(1 for b in blocks if any(i in hit for i in b))
    # 最长空白带：在「可勾画句」序列上数连续未命中，顺带记下每一段空白的首末句号
    blanks, run = [], []
    for i in idx:
        if i in hit:
            if run:
                blanks.append((run[0], run[-1]))
            run = []
        else:
            run.append(i)
    if run:
        blanks.append((run[0], run[-1]))
    spans = [(a, b, sum(1 for i in idx if a <= i <= b)) for a, b in blanks]
    mg = max(spans, key=lambda x: x[2]) if spans else None
    return {"n_sents": len(idx), "n_blocks": len(blocks), "cov_blocks": cov,
            "coverage": round(cov / len(blocks), 3),
            "max_gap": mg[2] if mg else 0,
            "gap_range": (mg[0], mg[1]) if mg else None,
            "blanks": [(a, b) for a, b, n in spans]}


def _find_needs_more(cov):
    """要不要触发定向补点：材料里还有整块没被碰过。"""
    return cov["max_gap"] >= _FIND_GAP_MAX or cov["coverage"] < _FIND_COV_MIN


# 标采分点用的题型表 = 小题训练那四种 + **大作文**。
# 大作文不进 FIND_TYPES（小题训练只练找点+写点，大作文不属于那儿），但真题批改的
# **练习模式**要给它也配一套「找点」—— 议论文动笔前同样得先从材料里定位：题目引的那句话
# 出自哪儿、有哪些侧面可以当分论点、哪些案例数据能直接引。所以单开一张表，只在这儿用。
_PT_TYPES = dict(FIND_TYPES, zuowen=(
    "文章写作（大作文）", 35, 1000, 1200,
    "从材料里立意、自选角度成文 —— 论点要从材料来，论据要有材料支撑"))
# 大作文的点数不按分值算（35 分照每 2~3 分一个点会算出十几个点，没意义）：
# 议论文动笔前圈出来的东西，六到十条正好够搭一篇三分论点的文章。
_PT_N = {"zuowen": (6, 10)}

_FIND_TYPE_FOCUS = {
    "guina": "抓「做法／措施／表现／成效」",
    "zonghe": "抓「是什么—为什么—怎么样」各层的要点",
    # 对策题必须单独说清楚，否则整个「问题段」会被漏光：实测一道 58 句的对策题，
    # 前 32 句全是问题描述（一票否决、资金分摊无标准、维保没人管），后面才是他山之石，
    # 结果采分点全落在后面 —— 因为模型认为「对策」在前 32 句里找不到原文依据。
    # 可对策题的标准答案本来就是「一个问题配一条对策」，对策是从问题推出来的，
    # 材料里没有现成原话是常态。所以这里明确：**问题句就是依据**。
    "duice": ("抓「问题 → 对策」：材料里**每一个问题／困难／矛盾／短板都要落一个采分点**，"
              "point 写成「针对…（问题），…（对策）」，sent 指向**描述这个问题的那一句** —— "
              "对策是你从问题推出来的，材料里往往没有现成原话，这很正常，不要因此跳过问题段；"
              "材料里若另有现成的做法或他山之石（别地的成功经验），也各落一个点"),
    "guanche": "抓「正文该写进去的内容要点」（由头、举措、成效、号召）",
    # 大作文没有「采分点」—— 它的找点是**动笔前的备料**：论点从哪儿来、论据拿什么撑。
    # 判卷时四个维度（立意/结构/论证/语言）里，「立意」和「论证与材料运用」两项直接取决于
    # 有没有把这些句子找出来，所以这一步值得单独练。
    "zuowen": ("抓「立意与论据」，分三类，每条 point 用「【类别】…」开头标明是哪一类：\n"
               "   · 【立意】题干引用的那句话在材料里的**出处及其阐释**，以及点明主旨、"
               "揭示核心矛盾的句子 —— 总论点的根，找不到它整篇就跑题\n"
               "   · 【分论点】材料里体现这个主题**不同侧面**的句子（不同主体、不同层面、"
               "正面反面），一个侧面一条，这是分论点的来源\n"
               "   · 【论据】能直接写进文章的**具体案例、数据、人物原话** —— "
               "议论文最缺的就是这个，空谈道理拿不到分\n"
               "   三类都要有，别全挑成一类；纯背景铺垫、与主题无关的细节不算"),
}


def _find_numbered(sents, lo=0, hi=None, block=_FIND_BLOCK):
    """材料 → 带【第N块】和句号的文本。

    句号是这套流程的地基：给了句号，模型就能直接报「这个点出自第几句」，
    服务端拿它当锚点、拿 evidence 当校验，比只给 evidence 再回头去猜位置稳得多。
    块号则是**逼它扫全文**的抓手 —— 要求逐块表态（有要点就列、没有就写"无"），
    模型跳过某一块就会在输出里露馅，不像一次性提问那样悄悄漏掉半篇材料。"""
    hi = len(sents) - 1 if hi is None else hi
    out, cur_blk = [], None
    for i, s in enumerate(sents):
        if i < lo or i > hi:
            continue
        blk = i // block + 1
        if blk != cur_blk:
            out.append("【第%d块】" % blk)
            cur_blk = blk
        out.append(("   -- %s" % s["t"]) if s.get("head") else ("[%d] %s" % (i, s["t"])))
    return "\n".join(out)


# 分块扫描用哪个档位。扫描本质是**提取**（哪一句是要点、把原句抄出来），按档位分工
# 本该是 fast 的活；真正需要判断力的是「合并定分」那一步（哪些点该并、名额给谁）。
# 用 pro 扫一道 23 句的题要跑十分钟（推理段吃掉大量 token），一份 4 题的真题就是 40 分钟，
# 出题慢到没法用。所以留成可切的：GONGKAO_FIND_SCAN_TIER=pro 可以切回去对比。
# 逼出覆盖率的是**分块结构**，不是档位 —— 老流程用的也是 flash，坏在一次性提问。
_SCAN_TIER = os.environ.get("GONGKAO_FIND_SCAN_TIER", "fast")


def _find_json(msgs, max_tokens, what, tier="pro"):
    """调一次 AI 拿 JSON。失败返回 (None, err)；解析不了也算失败（上游一律重试/兜底）。"""
    rep, err = _ai_call_or_error(
        msgs, temperature=0.25, max_tokens=max_tokens, timeout=300,
        json_mode=True, tier=tier)
    if err:
        return None, err
    try:
        return json.loads(rep), None
    except Exception:
        log.warning("find %s 的 JSON 解析失败：%s", what, (rep or "")[:200])
        # 普通 dict 而非 jsonify：这条链路会被 audit_find.py 在 Flask 之外调到
        return None, ({"error": "AI 返回格式异常，请重试"}, 502)


_FIND_SYS = ("你是申论阅卷组组长，负责制定这道题的标准答案与评分细则。"
             "采分点要**铺满整篇材料**（真题的标准答案从来不会只出自开头几段），"
             "每个点必须指明出自材料第几句、并照抄该句原文作依据，绝不改写、不编造。"
             "严格输出 JSON。")

# 大作文整条链路都要换一套说法。只改 _FIND_TYPE_FOCUS 是不够的 —— 实测那样改完，
# 标出来的还是「认识传统工艺成本高效率低但品牌价值独特」这种**综合分析式的要点**，
# 【立意】【分论点】【论据】三个标签一个都没出现：因为它被塞进的是「找出可以**得分**的
# 要点」这个框架，后面合并那步又按「像阅卷组定评分细则、合计正好 N 分」重新收口一遍，
# 大作文的口径被这两层采分点框架冲掉了。所以系统提示、任务说法、合并规则都得分开。
_ZW_SYS = ("你是申论大作文的指导老师。学生动笔前要先从给定资料里把**备料**圈出来："
           "总论点的根在哪句、有哪些侧面可以做分论点、哪些案例数据能直接引用。"
           "每条都必须指明出自材料第几句、并照抄该句原文作依据，绝不改写、不编造。"
           "严格输出 JSON。")


def _is_zw(qtype):
    return qtype == "zuowen"


def _find_scan(name, stem, sents, qtype):
    """Pass 1：逐块扫描候选要点。**这一步不定分值、不去重**，只求把全材料过一遍。

    为什么要单独一步：老流程一次性问「标出 4~6 个采分点」，模型会去句式规整、
    信息密集、好照抄的段落里凑够数就收工 —— 实测 11 道题里 8 道有整块材料零覆盖，
    最狠的一道 58 句材料前 32 句一个点没有。先按块逼它表态，凑数的动机就没了。"""
    n_blk = (len(sents) - 1) // _FIND_BLOCK + 1
    zw = _is_zw(qtype)
    task = ("**逐块**找出动笔前必须圈出来的**备料**（大作文没有采分点，别按采分点的路子写）"
            if zw else "**逐块**找出可以得分的要点")
    what = "备料" if zw else "要点"
    # 类别标签必须写在 **point 字段的说明里**。实测只写在上面那段 focus 里不管用 ——
    # 模型填 point 时看的是字段说明，照着「概括后的表述」写，标签一条都不带。
    point_rule = ("**必须以【立意】或【分论点】或【论据】开头**标明这是哪一类，"
                  "再接 10~28 字的表述。例：「【论据】巴黎展会限量丝巾售价 500 欧元被抢购」。"
                  "**三类缺一不可**：材料里论据最多、最好找，但只挑论据等于没找立意 —— "
                  "**题干引用的那句话在材料里的原句（往往在材料末尾的总结处）必须标成【立意】**，"
                  "找不到它整篇文章就会跑题"
                  if zw else "概括后的要点表述（10~28 字，点到关键词，**不是照抄原文**）")
    d, err = _find_json(
        [{"role": "system", "content": _ZW_SYS if zw else _FIND_SYS},
         {"role": "user", "content":
          "下面是一道申论**%s**的题干和给定资料。资料已按每 %d 句切成 %d 块，每句前面是句号。\n\n"
          "【题干】%s\n\n【给定资料】\n%s\n\n"
          "【任务】%s，%s。\n"
          "1. **必须把第 1 块到第 %d 块每一块都过一遍**，一块都不许跳过。某一块确实全是背景铺垫、"
          "无关细节、同义重复、反面例子这类干扰信息，就把这一块的 points 写成空数组 —— "
          "但你得明确表态，不能不提这一块。\n"
          "2. 每个%s给：\n"
          "   · sent：它出自**哪一句**的句号（就是材料里 [] 里的数字）。跨句总结的，"
          "填**最能支撑它的那一句**。\n"
          "   · point：%s\n"
          "   · evidence：把 sent 那一句**开头的 10~20 个字原封不动复制**过来（用来核对你没报错句号，"
          "所以一个字都不能改、不能概括；**不用抄整句**）\n"
          "3. 要具体：一条只讲一件事，别写「加强管理」「提升水平」这种空话。\n"
          "4. 允许一块出多条，也允许一块零条 —— 按材料实际情况来，别为了均匀硬凑。\n\n"
          '只输出 JSON：{"blocks":[{"block":1,"points":[{"sent":0,"point":"","evidence":""}]}]}'
          % (name, _FIND_BLOCK, n_blk, stem, _find_numbered(sents)[:14000],
             task, _FIND_TYPE_FOCUS.get(qtype, ""), n_blk, what, point_rule)}],
        # 这里给的是**正文额度**（推理段由 aiclient.budget() 另外加）。
        # 论正文，这段 JSON 撑死两三千 token：二十来个点 × (句号 + 10~28 字概括 + 十来字依据)，
        # evidence 只抄原句开头、不整句抄。但给到 8000 是有意的 ——
        # **budget() 的推理额度是按正文额度推导的**（max(4000, 2×正文)），而「逐块扫全材料」
        # 要想多久跟正文写多长根本不成比例。实测把正文压到 4000（推理只剩 8000）时，
        # 同一道 23 句的题只扫出 7 个候选（原来稳定 11~15 个），采分点从 5 个掉到 4 个，
        # 还把「LED 节能」和「5G 智慧灯杆」两个维度并成了一条。给宽不花钱（上限不是花销），
        # 给窄直接掉质量，所以这儿宁可宽。
        max_tokens=8000, what="分块扫描", tier=_SCAN_TIER)
    if err:
        return [], err
    got = []
    for b in (d.get("blocks") or []):
        got.extend(b.get("points") or [])
    return got, None


def _find_fill(name, stem, sents, qtype, blanks, have):
    """定向补点：只把「还没被任何采分点碰过」的句子喂回去，问这里面还有没有独立要点。

    只喂空白区间，模型没有别处可挑，注意力被摁在漏掉的那几句上；
    同时把已有要点列给它，避免补出同义重复。最多一轮，成本可控。"""
    seg = "\n\n".join(_find_numbered(sents, a, b) for a, b in blanks)
    if not seg.strip():
        return []
    d, err = _find_json(
        [{"role": "system", "content": _FIND_SYS},
         {"role": "user", "content":
          "这道申论**%s**的采分点已经标了一批，但下面这几段材料**一个采分点都没落上**，"
          "很可能是漏了。请只针对这几段判断：里面还有没有**独立的、还没被下面已有要点覆盖**的得分点。\n\n"
          "【题干】%s\n\n【已有要点】\n%s\n\n【还没被覆盖的材料】\n%s\n\n"
          "【要求】%s。真有独立要点就补出来；确实全是背景铺垫／无关细节／和已有要点重复的，"
          "就返回空数组 —— **不要为了填满而硬凑**，凑出来的空话点会把练习者带偏。\n"
          "每个点给 sent（句号）、point（%s）、evidence（照抄该句**开头 10~20 字**）。\n\n"
          '只输出 JSON：{"points":[{"sent":0,"point":"","evidence":""}]}'
          % (name, stem, "\n".join("· " + p["point"] for p in have),
             seg[:9000], _FIND_TYPE_FOCUS.get(qtype, ""),
             # 补出来的也得带类别标签，否则同一道题里一半有标签一半没有
             ("以【立意】/【分论点】/【论据】开头 + 10~28 字表述"
              if _is_zw(qtype) else "10~28 字概括"))}],
        # 补点也是提取，同扫描档位；额度同理留够推理（要判断空白段里到底有没有独立要点）
        max_tokens=4000, what="定向补点", tier=_SCAN_TIER)
    return [] if err else (d.get("points") or [])


def _find_merge(name, stem, cands, pts_full, n_lo, n_hi):
    """Pass 2：合并同义、剔干扰、砍到 n_lo~n_hi 个并配平分值。

    Pass 1 是「宁滥勿缺」地铺开，这一步才收口。**只许在候选里挑和合并，不许新增** ——
    新增的点没有经过句号锚定，会变成判不了的幽灵点。

    **合并结果只许回报候选编号，不许回报句号**：候选列表里同时摆着编号和句号，
    模型会把两者搞混 —— 实测一道 58 句的对策题，合并出的 12 个点里有 8 个把「候选序号」
    当成句号填了回来（「借鉴公交电梯模式」被标到句 10，可那段原文在句 35~37），
    采分点整体锚错位。学生勾对了句子反被判找错，比找点不全还糟。
    改成只报编号，句号由服务端从候选里查 —— 模型没有报错句号的机会。"""
    lst = "\n".join("%d) %s ｜ 原文：%s"
                    % (i + 1, c["point"], c["evidence"][:50])
                    for i, c in enumerate(cands))
    d, err = _find_json(
        [{"role": "system", "content": _FIND_SYS},
         {"role": "user", "content":
          "下面是一道申论**%s**从材料里逐块扫出来的**候选要点**（可能有重复、有过细的拆分、"
          "也可能混进了干扰信息）。请像真题阅卷组定评分细则那样，把它收口成最终的采分点。\n\n"
          "【题干】%s\n\n【候选要点】\n%s\n\n"
          "【怎么收口】\n"
          "1. 最终标 **%d~%d 个**采分点，合计正好 %d 分（真题一般每 2~3 分一个点）。\n"
          "2. **同一个治理维度下的几件事要合并成一个点**：比如「发布总体规划」「限制灯光秀新增」"
          "「设三种亮灯模式」同属『规划与分区管控』，应合并为一个采分点，而不是占掉三个名额 —— "
          "名额被一个维度吃光，材料后半段的维度就写不进标准答案了。\n"
          "3. **名额优先给覆盖面**：宁可让每个点粗一档，也要保证材料里**各个不同的方面都有点**，"
          "不要几个点全出自相邻的句子。\n"
          "4. 剔掉：背景铺垫、无关细节、反面例子、和别的点意思重复的。\n"
          "5. **只能从候选里挑和合并，绝对不许凭空新增候选里没有的点。**\n"
          "6. 每个最终点给：\n"
          "   · from：这个点是由**上面哪几条候选**合并来的，填**候选前面的编号**"
          "（合并了几条就列几个编号；没合并就填一个）。**填编号，不是句子序号。**\n"
          "   · point：合并后的要点表述（10~28 字，动宾结构、点到关键词）\n"
          "   · score：分值（所有点相加 = %d 分）\n\n"
          '只输出 JSON：{"points":[{"from":[1,3],"point":"","score":0}]}'
          % (name, stem, lst[:12000], n_lo, n_hi, pts_full, pts_full)}],
        # 同扫描：正文很短（十来条 point + 编号 + 分值，撑死八百 token），但这一步干的是
        # **判断**活 —— 哪些点同属一个维度该合并、有限的名额给谁。推理量同样不由输出长度决定。
        # 实测压到 2500 时，两次里有一次只出 4 个点，还把「居民区柔和灯光」（规划维度）
        # 和「长效管理机制」硬并成一条 —— 两个不相干的维度挤在一个采分点里。
        max_tokens=6000, what="合并定分")
    return (None if err else (d.get("points") or []))


def _find_anchor(sents, sent_no, evidence, point):
    """候选点 → 材料句号。三级降级，**不再静默丢点**。

    老逻辑是 evidence 锚不上就 `continue`，丢了几个点、丢了什么，谁也不知道 ——
    这本身就是「找点不全」的一个来源。现在：先信模型报的句号（拿 evidence 校验它没瞎报），
    对不上再用 evidence 反查，还不行就用 point 文本反查，全败才丢并计数。"""
    n = len(sents)
    ev = re.sub(r"\s", "", evidence or "")
    if isinstance(sent_no, (int, float)) and 0 <= int(sent_no) < n:
        i = int(sent_no)
        t = re.sub(r"\s", "", sents[i]["t"])
        # 校验：报的这一句得跟 evidence 对得上（模型偶尔会把句号报偏一两位）
        if not sents[i].get("head") and t and (
                not ev or _lcs_len(ev, t) >= min(10, len(t) // 3)):
            return [i]
    hit = _find_locate(sents, evidence)
    if hit:
        return hit
    return _find_locate(sents, point)          # 最后一档：拿概括后的表述去找最像的原句


def _find_points(qtype, stem, material, full):
    """材料 + 题干 → 一套采分点。返回 (points, info, err)，**不碰数据库**。

    三步：分块扫描（铺开）→ 合并定分（收口）→ 覆盖校验不过关就定向补点再收口一次。
    比老流程多 1~2 次 AI 调用，但出题是一次性的（一道题练 N 次只标一次），换的是
    「材料后半段不再整段没有采分点」—— 见 audit_find.py 的体检表。

    单独抽出来是为了能被 audit_find.py --rerun 直接调：那儿要在**不写库**的前提下
    拿新旧两套流程各跑一遍做对比。所以这里的 err 一律是普通 dict 而非 jsonify ——
    脱离 Flask 应用上下文调 jsonify 会当场抛 "Working outside of application context"。"""
    name = _PT_TYPES[qtype][0]
    pts_full = full or _PT_TYPES[qtype][1]
    if qtype == "guanche":                          # 贯彻执行：格式另占约 1/4，采分点只分内容那部分
        pts_full = pts_full - max(2, round(pts_full * 0.25))
    if qtype in _PT_N:                              # 大作文这类不按分值折算点数（见 _PT_N）
        n_lo, n_hi = _PT_N[qtype]
    else:
        # 采分点个数按分值定，贴近真题阅卷（约每 2~3 分一个点，按要点/关键词给分）
        n_lo = max(4, round(pts_full / 3.0))
        n_hi = min(10, max(n_lo + 2, round(pts_full / 2.0)))
    sents = _find_sents(material)

    cands, err = _find_scan(name, stem, sents, qtype)
    if err:
        return None, None, err
    cands = _find_norm(sents, cands)
    if len(cands) < 3:
        return None, None, ({"error": "AI 没从材料里扫出足够的要点，请重试"}, 502)

    # 扫完先看铺得开不开：还有整块材料没被碰过就定向补一轮（补点只在空白处问，不会重复）
    n_scan, filled = len(cands), 0
    cov0 = _find_coverage(sents, [{"sents": c["sents"]} for c in cands])
    if _find_needs_more(cov0):
        more = _find_fill(name, stem, sents, qtype, cov0["blanks"], cands)
        add = _find_norm(sents, more, exist=cands)
        cands += add
        filled = len(add)

    points, dropped = _find_finalize(name, stem, sents, cands, pts_full, n_lo, n_hi, qtype)
    if len(points) < 3:
        return None, None, ({"error": "AI 标出的采分点太少或对不上原文，请重试"}, 502)

    cov = _find_coverage(sents, points)
    # 扫描认为「含要点」、但收口时没能独立成点的句子。**它们不是干扰信息** ——
    # 实测扫出的候选有一半以上会被丢掉（贯彻执行 14~17 个候选只留 5~7 个点），
    # 把它们一律当干扰信息，用户勾中了会被判「找错」，而那句其实是对的，
    # 只是这一次标定没让它独立成点。存下来，判定时给第三种结果「沾边」。
    in_pts = {i for p in points for i in p["sents"]}
    near = sorted({i for c in cands for i in c["sents"]} - in_pts)
    info = {"n_sents": len(sents), "n_scan": n_scan, "n_filled": filled,
            "n_cands": len(cands), "dropped": dropped, "cov": cov, "near": near}
    log.info("find 出题 [%s] %d 句 → 扫出 %d（补 %d）→ 采分点 %d（另 %d 句沾边），"
             "coverage %d/%d，max_gap %d%s",
             name, len(sents), n_scan, filled, len(points), len(near),
             cov["cov_blocks"], cov["n_blocks"], cov["max_gap"],
             "，丢弃 %d 个锚不上的候选" % dropped if dropped else "")
    return points, info, None


# 参考答案的骨架：按题型给框架，让串出来的答案长得像该题型的标准答案
_FIND_REF_FRAME = {
    "guina": "分条列点（一、二、三…），每条「小标题 + 具体做法」，只陈述不评价",
    "zonghe": "先亮观点/解释，再分层展开（是什么→为什么→怎么样），最后落回结论",
    "duice": "分条列点，每条「针对的问题 + 具体对策」，对策要具体可执行",
    "guanche": "按指定文种的格式成文（标题、称谓、正文分条、落款），要点写进正文",
}


def _find_reference(qtype, name, stem, points, wmin, wmax, doctype=""):
    """由**采分点拼装**参考答案：AI 只负责串词、书面化、收字数，**不许增删要点**。

    为什么不像真题批改那样让 AI 从头写一篇（mods/find.py 的 _gen_reference 就是那么干的）：
    从头写出来的范文，要点跟这道题的采分点对不上 —— 学生照着范文写，反而被判漏点，
    自相矛盾。小题训练手里有现成的采分点，参考答案就该是「这几个点写成文」的样子，
    一个不多一个不少，学生拿它和自己的作答逐条比才有意义。"""
    lst = "\n".join("%d. %s" % (i + 1, p["point"]) for i, p in enumerate(points))
    frame = _FIND_REF_FRAME.get(qtype, _FIND_REF_FRAME["guina"])
    if doctype:
        spec = GW_MAP.get(doctype, {})
        frame = "按「%s」的格式成文：%s。把下面的要点写进正文。" % (doctype, spec.get("fmt", ""))
    target = wmin + int((wmax - wmin) * 0.45)
    base = ("把下面这道申论**%s**的采分点，串成一份可以拿满分的参考答案。\n\n"
            "【题干】%s\n\n【必须写进去的采分点】（阅卷标准，一个不能少）\n%s\n\n"
            "【要求】\n"
            "1. **只准写这 %d 个要点，不许增加材料里没有的内容、也不许漏掉任何一个**。\n"
            "2. %s\n"
            "3. 书面化、动宾结构、点到关键词；不抄材料原句的口语和引语。\n"
            "4. 字数 %d~%d 字（目标 %d 字），这是硬性要求。\n"
            "只输出答案正文：不要 Markdown 记号，不要解释，不要字数统计。"
            % (name, stem[:800], lst, len(points), frame, wmin, wmax, target))
    msgs = [{"role": "system", "content": "你是资深申论老师，参考答案要点齐全、表述规范、字数精准。"},
            {"role": "user", "content": base}]
    # 档位用 fast，不是 pro：这一步是「把给定要点压成 250 字」的写作压缩，不是推理。
    # 实测同一道题 —— pro 要 2~3 分钟、还屡屡被 max_tokens 截断（推理段吃光额度、正文空串），
    # 写出来 304 字超上限 54；fast 全程 30 秒、零失败，稿子在 187~295 之间。
    # 要点是现成的，模型不需要"想"，只需要"写短"。
    #
    # 收口标准也改了：**上限硬、下限软**。word_min 是我们自己按题型定的，题干里真正的
    # 硬约束是「不超过 N 字」—— 写少了不扣分，写超了才扣。原来把下限当同等硬条件，
    # 返工就来回震荡（187→295→158→265），四稿都"不合格"，最后反而交出最差的那版。
    lo_ok = int(wmin * 0.75)
    best = ""
    for i in range(4):
        rep, err = _ai_call_or_error(msgs, temperature=0.35, max_tokens=max(2000, wmax * 4),
                                     timeout=300, tier="fast")
        if err:
            log.warning("find 参考答案第 %d 稿失败：%s", i + 1, err[0].get("error"))
            break
        ref = re.sub(r"[*#`]+", "", rep or "").strip()
        n = _sl_words(ref)
        if lo_ok <= n <= wmax:
            return ref
        # 挑兜底稿时超上限要重罚：超了是硬伤，短一点只是不够丰满
        pen = (lambda x: _sl_gap(x, wmin, wmax) * (3 if x > wmax else 1))
        if not best or pen(n) < pen(_sl_words(best)):
            best = ref
        # 光说「压缩到 250 字」压不住 —— 模型在「要点一个不能少」和「字数」之间会选前者。
        # 给到每个要点的字数预算，它才知道该怎么砍（砍修饰，不是砍要点）。
        per = max(12, target // max(1, len(points)))
        msgs = msgs[:1] + [
            {"role": "user", "content": base},
            {"role": "assistant", "content": ref},
            {"role": "user", "content": "这一稿 %d 字，不符合要求（要求 %d~%d 字，目标 %d 字）。请%s。\n"
                                        "**%d 个要点一个都不能少**，所以平均每个要点只能写 **%d 字左右** —— "
                                        "%s，不要删要点。只输出答案正文。"
                                        % (n, wmin, wmax, target,
                                           "扩写" if n < wmin else "压缩",
                                           len(points), per,
                                           "把修饰语、举例、铺垫全部砍掉，只留动宾结构的关键词"
                                           if n > wmax else "每点补足具体做法")}]
    return best


def _find_build(db, uid_, qtype, stem, material, full, wmin, wmax, source, requirement=""):
    """出一套采分点并落库，返回 (paper_id, err)。参考答案在这一步一并生成存下来。"""
    name, dfull, dmin, dmax = FIND_TYPES[qtype][0], FIND_TYPES[qtype][1], FIND_TYPES[qtype][2], FIND_TYPES[qtype][3]
    points, info, err = _find_points(qtype, stem, material, full)
    if err:
        return None, err
    lo, hi = wmin or dmin, wmax or dmax
    doctype = ""
    if qtype == "guanche":
        for k in sorted(GW_MAP.keys(), key=len, reverse=True):
            if k in (stem or ""):
                doctype = k
                break
    # 范文生成失败不该让整道题白出（它是独立的一次调用，超时就空着，页面上另有重生成按钮）
    try:
        ref = _find_reference(qtype, name, stem, points, lo, hi, doctype)
    except Exception:
        log.warning("find 参考答案生成失败，题目照常出", exc_info=True)
        ref = ""
    cur = db.execute(
        "INSERT INTO find_papers(user_id,qtype,type_name,stem,requirement,full,word_min,word_max,"
        "material,points,source,reference,near) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid_, qtype, name, stem, requirement, full or dfull, lo, hi,
         material, json.dumps(points, ensure_ascii=False), source, ref,
         json.dumps(info["near"])))
    db.commit()
    return cur.lastrowid, None


def _ev_text(sents, hit):
    """把命中的几句拼成可读的依据原文。**不相邻的句子之间要打省略号。**

    原来是一路 "".join —— 句号连续时没问题，一旦跨句（一个采分点覆盖句 22、28、47、50
    这种很常见）就会把不挨着的半句硬粘在一起，读出来是断的：
    「…工商人员核查经营资质，卫生监督2014年初，县工商局与…」。
    小题训练那边材料是按句渲染高亮的，看不出来；真题批改把 evidence 当一整段引文显示，
    就直接露馅了。所以拼接这件事得有个统一的地方管。
    """
    out, prev = [], None
    for i in hit:
        if prev is not None and i != prev + 1:
            out.append("……")
        out.append(sents[i]["t"])
        prev = i
    return "".join(out)


def _find_norm(sents, raw, exist=()):
    """候选点 → 锚定过的 {sents, point, evidence}，顺手去掉重复占同一句的。"""
    taken = {i for c in exist for i in c["sents"]}
    out = []
    for p in raw:
        pt = (p.get("point") or "").strip()
        ev = (p.get("evidence") or "").strip()
        if not pt:
            continue
        hit = _find_anchor(sents, p.get("sent"), ev, pt)
        if not hit or hit[0] in taken:
            continue
        taken.update(hit)
        out.append({"sents": hit, "sent": hit[0], "point": pt,
                    "evidence": _ev_text(sents, hit) or ev})
    return out


def _find_guard(sents, points, cands, n_hi):
    """合并之后再守一道覆盖 —— 而且这一道**不指望 AI**。

    实测踩出来的：扫描阶段明明在材料后半段找到了要点，合并收口时模型嫌它"不重要"又给砍了，
    结果最终采分点 coverage 2/6、最长空白带 26 句 —— 比不做分块扫描还差。
    校验只放在合并前是拦不住的：那时候看的是候选，铺得挺开。
    所以这儿改成确定性兜底：哪一段空着、候选里正好有现成的点落在那儿，就直接补回去。
    补进来的点分值先留空，最后统一按满分配比。"""
    for _ in range(4):                          # 最多补 4 个，别让点数失控
        cov = _find_coverage(sents, points)
        if not _find_needs_more(cov) or len(points) >= n_hi + 2:
            break
        used = {i for p in points for i in p["sents"]}
        pick = None
        # 先补最长的那段空白 —— 那儿漏得最狠
        for a, b in sorted(cov["blanks"], key=lambda x: -(x[1] - x[0])):
            for c in cands:
                if c["sent"] not in used and a <= c["sent"] <= b:
                    pick = c
                    break
            if pick:
                break
        if not pick:                            # 空白处扫描时本来就没找到东西，认了
            break
        log.info("find 合并后覆盖不足，从候选补回：[句%d] %s", pick["sent"], pick["point"])
        points.append({"point": pick["point"], "evidence": pick["evidence"],
                       "score": 0.0, "sents": pick["sents"]})
    return sorted(points, key=lambda p: p["sents"][0])   # 按材料顺序排，读起来顺


_ZW_CATS = ("【立意】", "【分论点】", "【论据】")


def _zw_select(cands, n_hi):
    """大作文跳过合并后，从候选里挑最终备料。**不能按位置取前 n 条。**

    实测踩过：跳过合并后落到 `cands[:n_hi]` 这个兜底，等于按材料顺序截断 ——
    34 句的材料，12 条备料全挤在句 5~24，而上一轮标到过的句 33
    「处理好不同因素之间的关系是长远发展的关键」（题干引语的出处、立意的根）被截没了。
    这正是当初给小题修好的「集中在前段」，在大作文这条路上又被我引回来一次。

    所以按两条挑：
      1. **每一类先保底**（立意 / 分论点 / 论据各先拿一条）—— 三类缺一不可，
         尤其【立意】只会有一两条，最容易被淹掉，而它恰恰是最要紧的；
      2. 余下名额**按材料位置铺开**（等距取），别让备料全挤在开头。
    """
    def cat(c):
        p = c.get("point") or ""
        for k in _ZW_CATS:
            if p.startswith(k):
                return k
        return ""
    picked, used = [], set()
    for k in _ZW_CATS:                            # 每类保底一条，立意优先
        for c in cands:
            if cat(c) == k and id(c) not in used:
                picked.append(c); used.add(id(c)); break
    rest = [c for c in cands if id(c) not in used]
    room = max(0, n_hi - len(picked))
    if rest and room:
        # 等距取，让剩下的名额铺满整篇材料而不是全挤在前面
        step = max(1, len(rest) / float(room))
        for j in range(room):
            c = rest[min(len(rest) - 1, int(j * step))]
            if id(c) not in used:
                picked.append(c); used.add(id(c))
    return sorted(picked, key=lambda c: c["sents"][0])


def _find_finalize(name, stem, sents, cands, pts_full, n_lo, n_hi, qtype=""):
    """合并定分 + 落成最终采分点。合并这一步失败就退回「直接用候选」，不让一道题白出。

    **大作文不走合并**：那一步的口径是「像阅卷组定评分细则、把同一维度的点并起来、
    合计正好 N 分」，专为采分点设计。大作文要的是三类互不相干的备料
    （立意 / 分论点 / 论据），并起来就毁了 —— 实测第一版没跳过，扫描明明分了类，
    合并完出来的是「认识传统工艺成本高效率低但品牌价值独特」这种综合分析式要点，
    三个类别标签一个都没剩下。备料本来就该各是各的，扫出来是什么就留什么。"""
    zw = _is_zw(qtype)
    merged = (None if zw else
              _find_merge(name, stem, cands, pts_full, n_lo, n_hi) if len(cands) > n_hi else None)
    points, dropped, seen = [], 0, set()
    for m in (merged or []):
        pt = (m.get("point") or "").strip()
        # 句号一律从候选查，不信模型回报的（它会把候选编号当句号填回来，见 _find_merge）
        idx = [int(x) - 1 for x in (m.get("from") or []) if str(x).lstrip("-").isdigit()]
        hit = sorted({i for k in idx if 0 <= k < len(cands) for i in cands[k]["sents"]})
        if not pt or not hit:                     # 编号也对不上 —— 拿 point 文本兜一次底
            hit = _find_locate(sents, pt) if pt else []
            if not hit:
                dropped += 1
                continue
        key = frozenset(hit)
        if key in seen:
            continue
        seen.add(key)
        points.append({"point": pt, "evidence": _ev_text(sents, hit),
                       "score": float(m.get("score") or 0), "sents": hit})
    if not points:                                # 没合并（候选本来就不多）或合并失败 → 直接用候选
        for c in (_zw_select(cands, n_hi) if zw else cands[:n_hi]):
            points.append({"point": c["point"], "evidence": c["evidence"],
                           "score": 0.0, "sents": c["sents"]})
    points = _find_guard(sents, points, cands, n_hi)   # 合并砍掉的覆盖面，在这儿补回来
    if zw:
        # 大作文的「点」是备料不是采分点，摊分值没有意义（35 分摊到 6 条备料上，
        # 页面显示「[5.8 分] 【论据】…」只会误导人以为找到它就能得分）。一律留 0，前端不显示。
        for p in points:
            p["score"] = 0.0
        return points, dropped
    # 分值按满分重新配比，保证一道题所有采分点相加正好 = 满分（AI 给的分常不配平）。
    # 补回来的点 score=0，只按 AI 那份配比会让它们白干活 —— 先按均分兜个底再一起配比。
    avg = (sum(p["score"] for p in points) / sum(1 for p in points if p["score"])) \
        if any(p["score"] for p in points) else 0
    for p in points:
        if not p["score"]:
            p["score"] = avg
    tot = sum(p["score"] for p in points)
    for p in points:
        p["score"] = round(p["score"] / tot * pts_full, 1) if tot else round(pts_full / len(points), 1)
    return points, dropped


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


# 一道小题 = 一则材料（用户要求：真题里一道小题一般只对应「给定资料N」中的某一则，
# 而不是一道题对多则）。所以每次只出**一则**，但这一则要够真题单则体量（字数达标）。
# 字数按 2026 国考真题单则给定资料实测标定（材料字数≈答案上限的 5~7 倍）：
#   归纳概括：城市用光≈1600 字 / 鲁师傅烧饼≈2000 字；综合分析：三家制造业≈2200 / 威山≈1900；
#   提出对策：养老机构≈2200；贯彻执行：星空短评≈2800 / 政务云推荐≈2200 / 三案例汇报≈2000。
# 内部融合背景/做法/成效/问题多个面并掺干扰信息，供从同一则里提取 5~8 个采分点。
# spec = (则数=1, 单则字数区间, [这一则内部要覆盖的面])。
_FIND_MAT_SPEC = {
    "guina": (1, (1400, 1900), [
        "以某地区/某单位为主线，把它在这方面的【具体做法与成效】一整则写透：有主体、有动作、有数据、"
        "有干部或群众原话；做法分几个各有侧重的方面，穿插【无关背景、同义重复、推进中的困难】等干扰信息"]),
    "zonghe": (1, (1600, 2100), [
        "在同一则里把要分析的【现象 / 观点 / 一句话】讲清：它是什么、从哪来、有哪些具体表现（事实、数据、"
        "场景）；不同主体怎么看、为什么会这样、正反两面；以及它的影响、意义与走向（供『是什么→为什么→"
        "怎么样』三层），并掺入干扰信息"]),
    "duice": (1, (1700, 2200), [
        "在同一则里把这个话题当前的【问题 / 困难 / 矛盾 / 短板】铺清楚：具体是什么、卡在哪、谁受影响，"
        "有一线声音和数据，问题分几个侧面（对策要从问题里长出来）；再补相关背景或他山之石，"
        "并掺入【无关细节、同义重复】作干扰"]),
    "guanche": (1, (1900, 2500), [
        "在同一则里写全这件事的【背景与基本情况】（来龙去脉、现状、数据，写公文的由头/依据从这里来）、"
        "各方的【具体做法 / 举措 / 经验】（分主体、有细节、有原话，是正文要点主要来源）、"
        "以及【成效、问题与各方反响】（掺入干扰信息，供辨别取舍）"]),
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
    """按【题型】出对应的给定资料 —— **只出一则**，但这一则要够真题单则体量、字数达标
    （用户要求：一道小题只对应一则材料，别拆成材料一/二/三）。再据材料出题干。
    返回 (material, stem, err)。贯彻执行题另传文种 doctype。"""
    n_pass, per, angles = _FIND_MAT_SPEC.get(qtype, _FIND_MAT_SPEC["guina"])
    lo, hi = per
    sys = ("你是申论命题人。给定资料贴近国考/省考真题：**这一则材料就有真题单则的体量（%d~%d 字）**，"
           "有具体地名、人名、数据、对话，并**掺入干扰信息**（背景铺垫、无关细节、同义重复、反面例子）"
           "供考生练找点。直接输出这一则材料的正文，不要「材料一/材料二」这类标题、不要 Markdown 记号。"
           % (lo, hi))
    if doctype:                                       # 贯彻执行：材料要能支撑该文种的写作
        sys += "这份给定资料将用于让考生写一篇「%s」，材料要提供足够支撑该文种的素材（由头、要点、事例）。" % doctype
    passages = []
    for i in range(n_pass):
        angle = angles[i % len(angles)]
        p = ("请命制一道**%s**的「给定资料」——**只写一则完整材料**，主题：%s。\n"
             "这一则材料要：%s\n"
             "字数 %d~%d 字（对齐真题单则材料体量、字数达标，硬性要求，别写短）。"
             "内容要能从中提取 5~8 个采分点。" %
             (name, topic, angle, lo, hi))
        # 只出一则，可以多返工两次把字数收进区间（真题单则体量偏大，一次常写不够）
        txt = _find_fit_words(p, lo, hi, sys, tries=2)
        if txt:
            passages.append(txt)
    if not passages:
        return None, None, (jsonify({"error": "AI 没出好材料，请重试"}), 502)
    # 一道题一则：直接就是这一则正文，不加「材料N」标题（真题里一道小题只对应某一则）。
    # 兼容将来若某题型改回多则：>1 则时才补标题。
    if len(passages) == 1:
        material = passages[0]
    else:
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
    # done=练过几次、last_done=最近一次练习时间、best=最高分 —— 前端「做过的题」区靠
    # last_done 倒排、显示练习次数与最好成绩（做过的题一键重练，纳入复习规划）。
    rows = get_db().execute(
        "SELECT id,qtype,type_name,stem,full,source,created_at,"
        "(SELECT COUNT(*) FROM find_records r WHERE r.paper_id=find_papers.id) done,"
        "(SELECT MAX(r.created_at) FROM find_records r WHERE r.paper_id=find_papers.id) last_done,"
        "(SELECT MAX(r.score) FROM find_records r WHERE r.paper_id=find_papers.id) best "
        "FROM find_papers WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid(),)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.delete("/api/find/paper/<int:pid>")
def find_paper_del(pid):
    """删一道小题：题目和它的所有做题记录一起删（用户自定义清理不需要/生成质量不高的题）。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM find_papers WHERE id=? AND user_id=?", (pid, uid())).fetchone():
        return jsonify({"error": "题目不存在"}), 404
    db.execute("DELETE FROM find_records WHERE paper_id=? AND user_id=?", (pid, uid()))
    db.execute("DELETE FROM find_papers WHERE id=? AND user_id=?", (pid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/find/papers/delete")
def find_papers_del():
    """批量删小题：只删本人的、id 合法的那些。返回实删数量。"""
    d = request.get_json(silent=True) or {}
    ids = [int(x) for x in (d.get("ids") or []) if str(x).isdigit()]
    if not ids:
        return jsonify({"error": "没选中题目"}), 400
    db = get_db()
    qs = ",".join("?" * len(ids))
    mine = [r[0] for r in db.execute(
        "SELECT id FROM find_papers WHERE user_id=? AND id IN (%s)" % qs, [uid(), *ids])]
    if mine:
        mq = ",".join("?" * len(mine))
        db.execute("DELETE FROM find_records WHERE user_id=? AND paper_id IN (%s)" % mq, [uid(), *mine])
        db.execute("DELETE FROM find_papers WHERE user_id=? AND id IN (%s)" % mq, [uid(), *mine])
        db.commit()
    return jsonify({"ok": True, "deleted": len(mine)})


@bp.delete("/api/find/record/<int:rid>")
def find_record_del(rid):
    """删单条做题记录（做题记录/错题记录页里逐条清理），不动题目本身。"""
    db = get_db()
    db.execute("DELETE FROM find_records WHERE id=? AND user_id=?", (rid, uid()))
    db.commit()
    return jsonify({"ok": True})


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
    done = db.execute("SELECT COUNT(*) c FROM find_records WHERE paper_id=? AND user_id=?",
                      (pid, uid())).fetchone()["c"]    # 本题练过几次，做题页给「查看本题记录」用
    return jsonify({"id": r["id"], "qtype": r["qtype"], "type_name": r["type_name"],
                    "stem": r["stem"], "full": r["full"],
                    "word_min": r["word_min"], "word_max": r["word_max"],
                    "source": r["source"], "n_points": npt, "done": done,
                    "material_words": _sl_words(r["material"]),   # 给定资料总字数（像范文推荐那样显示）
                    "doctype": doctype,
                    "doctype_fmt": (GW_MAP.get(doctype, {}).get("fmt", "") if doctype else ""),
                    "sents": [{"i": i, "p": s["p"], "t": s["t"]} for i, s in enumerate(sents)]})


def _find_split_wrong(row, picked, in_points):
    """勾了但不在采分点里的句子，再分成「沾边」和「真找错」。

    原来是一刀切：不在采分点里 = 找错 = 「这些是干扰信息」。**这个反馈是错的。**
    实测（audit_find.py --baseline）扫描扫出的候选有一半以上会在收口时被丢掉 ——
    贯彻执行 14~17 个候选只留 5~7 个点。被丢掉的那些句子**确实含要点**，只是这一次
    标定没让它独立成点（比如「设施农业」和「星光合作社」都是正当举措，但只有一个入选）。
    用户勾中它，得到「这是干扰信息」的反馈，等于教错了。

    所以第三种结果：**沾边** —— 这句相关，但没能独立成一个采分点。
    near 是出题时存下来的（候选句 − 最终采分点句），老题目没有这列就退回老行为。
    """
    try:
        near_set = set(json.loads(row["near"] or "[]"))
    except Exception:
        near_set = set()
    near, wrong = [], []
    for i in picked:
        if i in in_points:
            continue
        (near if i in near_set else wrong).append(i)
    return near, wrong


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
    all_pt_sents = {i for p in points for i in p["sents"]}
    near, wrong = _find_split_wrong(r, picked, all_pt_sents)
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
        "near": [{"i": i, "t": sents[i]["t"]} for i in near if i < len(sents)],
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
        # 正文额度：逐点评语 + 格式段 + 表述问题 + 一句建议（推理段由 budget() 另加）。
        # 同样按「输出短但要逐点比对」留够推理，别照正文长度抠。
        temperature=0.3, max_tokens=5000, timeout=300, json_mode=True, tier="pro")
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
    # points_snap：把当次这套采分点快照进记录。采分点是会被重标的（audit_find.py --apply），
    # 重标之后旧记录里的勾画就和新采分点对不上，回看会串 —— 回看一律按快照重算。
    db.execute("INSERT INTO find_records(user_id,paper_id,marks,find_result,answer,grade,score,full,"
               "points_snap) VALUES(?,?,?,?,?,?,?,?,?)",
               (uid(), pid, json.dumps(picked), json.dumps(d.get("find_result") or {}, ensure_ascii=False),
                answer, json.dumps(g, ensure_ascii=False), score, r["full"],
                json.dumps(points, ensure_ascii=False)))
    db.commit()
    g["full"] = r["full"]
    g["reference"] = r["reference"] or ""       # 参考答案：出题时就生成好了，这里直接给
    g["ref_words"] = _sl_words(g["reference"])
    return jsonify(g)


@bp.get("/api/find/records")
def find_records_list():
    """找点/写点的历史记录：每次批改留一条，可回看。贯彻执行题带内容/格式分。
    带 ?paper_id=N 只看这道题的记录（题目内部按时间的多次留痕）；不带就是全局做题记录。
    带 ?wrong=1 只看没拿满分的（错题记录）。三者都按时间倒序。"""
    pid = request.args.get("paper_id")
    wrong = request.args.get("wrong") == "1"
    where, args = ["r.user_id=?"], [uid()]
    if pid and str(pid).isdigit():
        where.append("r.paper_id=?"); args.append(int(pid))
    if wrong:
        where.append("r.score < r.full")
    rows = get_db().execute(
        "SELECT r.id, r.paper_id, r.score, r.full, r.grade, r.created_at, "
        "p.qtype, p.type_name, p.stem, p.source "
        "FROM find_records r JOIN find_papers p ON p.id=r.paper_id "
        "WHERE " + " AND ".join(where) + " ORDER BY r.id DESC LIMIT 80", args).fetchall()
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
            # 漏掉的采分点数（错题记录里提示「这次漏了几个点」）
            d["miss_n"] = sum(1 for it in (g.get("items") or []) if it.get("got") == "miss")
        except Exception:
            log.warning("find 记录的 grade JSON 解析失败，这条会少字段", exc_info=True)
        out.append(d)
    return jsonify({"items": out})


@bp.get("/api/find/record/<int:rid>")
def find_record(rid):
    """一条历史记录的详情 —— 要能把当时那一遍**完整重演**出来：
    题干 + 材料（按句切好，带当时的勾画着色）+ 找点判定 + 逐点批改 + 我写的答案 + 参考答案。

    材料/采分点都从记录当时的快照走：采分点会被重标（audit_find.py --apply），
    拿现在的采分点去着色旧勾画，绿的会变黄、判定和当时对不上。"""
    r = get_db().execute(
        "SELECT r.id, r.paper_id, r.score, r.full, r.grade, r.answer, r.marks, r.find_result, "
        "r.points_snap, r.created_at, p.qtype, p.type_name, p.stem, p.word_min, p.word_max, "
        "p.source, p.material, p.points, p.reference "
        "FROM find_records r JOIN find_papers p ON p.id=r.paper_id "
        "WHERE r.id=? AND r.user_id=?", (rid, uid())).fetchone()
    if not r:
        return jsonify({"error": "记录不存在"}), 404

    def _loads(s, default):
        try:
            return json.loads(s or "")
        except Exception:
            return default

    marks = _loads(r["marks"], [])
    # 老记录没有快照，只能退回用现在的采分点（可能已重标）—— 前端据 snap 标志提示一下
    snap = _loads(r["points_snap"], None)
    points = snap if snap is not None else _loads(r["points"], [])
    sents = _find_sents(r["material"] or "")
    picked = set(marks)
    pt_sents = {i for p in points for i in (p.get("sents") or [])}
    ok_s = sorted(picked & pt_sents)              # 找对：勾了且是采分点
    bad_s = sorted(picked - pt_sents)             # 找错：勾了但不是采分点（被干扰信息骗了）
    miss_s = sorted(pt_sents - picked)            # 找漏：是采分点但没勾
    return jsonify({"id": r["id"], "paper_id": r["paper_id"], "score": r["score"], "full": r["full"],
                    "qtype": r["qtype"], "type_name": r["type_name"], "stem": r["stem"],
                    "word_min": r["word_min"], "word_max": r["word_max"], "source": r["source"] or "",
                    "answer": r["answer"] or "", "created_at": r["created_at"],
                    "marks": marks,                            # 我勾画的句子下标
                    "find_result": _loads(r["find_result"], {}),  # 找点判定：找到几/漏几/错几/重几
                    "grade": _loads(r["grade"], {}),
                    "reference": r["reference"] or "",         # 参考答案（出题时生成）
                    "ref_words": _sl_words(r["reference"] or ""),
                    "material_words": _sl_words(r["material"] or ""),
                    "snap": snap is not None,                  # 采分点是不是当时的快照
                    # 材料按句下发 + 当时的着色，前端直接复用做题页那套渲染
                    "sents": [{"i": i, "p": s["p"], "t": s["t"], "head": s["head"]}
                              for i, s in enumerate(sents)],
                    "mark_ok": ok_s, "mark_bad": bad_s, "mark_miss": miss_s,
                    "points": [{"point": p.get("point"), "score": p.get("score"),
                                "sents": p.get("sents") or []} for p in points]})


@bp.post("/api/find/paper/<int:pid>/reference")
def find_ref_regen(pid):
    """单独重生成参考答案：它是出题之外独立的一次 AI 调用，超时/失败就会空着，
       没必要为了一份参考答案把整道题重出一遍（那要重标采分点，历史判定全变）。"""
    db = get_db()
    r = _find_paper(db, pid)
    if not r:
        return jsonify({"error": "题目不存在"}), 404
    points = json.loads(r["points"] or "[]")
    if not points:
        return jsonify({"error": "这道题没有采分点，无法拼装参考答案"}), 400
    ref = _find_reference(r["qtype"], r["type_name"], r["stem"] or "", points,
                          r["word_min"] or 150, r["word_max"] or 300, _find_doctype(r))
    if not ref:
        return jsonify({"error": "AI 还是没给出参考答案，请稍后再试"}), 502
    db.execute("UPDATE find_papers SET reference=? WHERE id=? AND user_id=?", (ref, pid, uid()))
    db.commit()
    return jsonify({"reference": ref, "ref_words": _sl_words(ref)})


# 上传的一份真题里有「给定资料1/2/3…」多则，而一道小题通常只对应其中某一则。
# 所以按编号把合并的给定资料切成多则，每道题只拿它题干里引用的那一则去标采分点
# （对齐真题「一题一则」，采分点更准、不被别则串味）。
_CN_NUM_F = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "十": 10}
# 分则标记：行首「1.」这类阿拉伯编号，或「材料一/给定资料2」这类标题
_MAT_SEG_NUM = re.compile(r"^[ \t]*(\d{1,2})\s*[.．、]\s*(?=\S)", re.M)
_MAT_SEG_CN = re.compile(r"^[ \t]*(?:给定)?材\s*料\s*([一二三四五六七八九十\d]{1,3})\s*[.．、:：]?\s*", re.M)
# 题干里的「给定资料N / 材料N」引用
_Q_MAT_REF = re.compile(r"(?:给定)?[资材]\s*料\s*([一二三四五六七八九十\d]{1,3})")


def _cn2i(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else _CN_NUM_F.get(s, 0)


def _split_materials(material):
    """把一份合并的给定资料按开头编号切成 {序号: 该则正文}。
    只保留从 1 起、连续递增的编号（过滤材料内部误命中的列表项/年份）。切不出多则就返回 {}。"""
    for pat in (_MAT_SEG_NUM, _MAT_SEG_CN):
        marks = [(m.start(), m.end(), _cn2i(m.group(1))) for m in pat.finditer(material)]
        seq, kept = 1, []
        for st, en, num in marks:
            if num == seq:                  # 只接从 1 开始一路连续的编号
                kept.append((st, en))
                seq += 1
        if len(kept) >= 2:
            out = {}
            for i, (st, en) in enumerate(kept):
                end = kept[i + 1][0] if i + 1 < len(kept) else len(material)
                out[i + 1] = material[en:end].strip()   # 去掉编号本身，留正文
            return out
    return {}


def _q_scoped_material(qbody, mats, full_material):
    """一道题该用哪一则材料：读题干里引用的「给定资料N」，只喂那一则。
    引用多则就拼那几则；没写明或对不上就退回整份（如自拟题目的大作文式题干）。"""
    if not mats:
        return full_material
    refs = []
    for m in _Q_MAT_REF.finditer(qbody):
        n = _cn2i(m.group(1))
        if n in mats and n not in refs:
            refs.append(n)
    if not refs:
        return full_material
    if len(refs) == 1:
        return mats[refs[0]]
    return "\n\n".join(mats[n] for n in refs)


@bp.post("/api/find/upload")
def find_upload():
    """上传真题文档 → 拆出材料和小题 → 留归纳概括/综合分析/提出对策/贯彻执行，各标一套采分点（大作文跳过）。
       抽文本、拆题、判题型全部复用真题批改那条管线（_split_paper / _classify_questions）。
       给定资料按编号切成多则，每道题只用它题干引用的那一则标采分点（一题一则）。"""
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
    mats = _split_materials(material)             # 按编号切成 {1:…, 2:…, …}；切不出就 {}

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
        qmat = _q_scoped_material(q["body"], mats, material)   # 一题一则：只用题干引用的那一则
        pid, err = _find_build(db, uid(), key, q["body"][:1200], qmat, full,
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
    # 保持 fast：这是「限字数写作」，不是推理。实测在小题那边的同类任务上（_find_reference），
    # pro 要 2~3 分钟、屡屡被 max_tokens 截断（推理段吃光额度、正文一个字没出），
    # 写出来还超上限；fast 三十秒收工且字数收得住。写范文不需要"想"，需要"写准长度"。
    best, budget = "", max(2000, int(wmax * 4))
    for _ in range(tries + 1):
        rep, err = _ai_call_or_error(msgs, temperature=0.4, max_tokens=budget,
                                     timeout=300, tier="fast")
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


def _q_mat_refs(qbody, mats):
    """题干里引用了「给定资料几」。返回 [3] 这样的编号列表；没写明或切不出多则就 []。"""
    if not mats:
        return []
    out = []
    for m in _Q_MAT_REF.finditer(qbody or ""):
        n = _cn2i(m.group(1))
        if n in mats and n not in out:
            out.append(n)
    return out


def _sl_std_points(db, qrow, qtype, question, material, full):
    """真题某一小题的**预标采分点**：有就取，没有就现标一次并缓存。
    返回 (points, refs)；points 为 [] 表示这题不适用、退回现场提炼。
    refs 是这套采分点标在「给定资料几」上（句号是相对那一则的，标签要靠它才说得准）。

    为什么不在上传时就标：一份卷子四五道题，每道要跑「分块扫描 → 合并定分」两三次 AI 调用，
    上传会从半分钟变成十分钟，用户对着转圈不知道在等什么。改成**第一次批改这道题时**
    惰性标一次并缓存 —— 成本只付一次，而且只给真正练到的题付。

    自由练（没有 qrow）不预标：那是用户临时贴的题干和材料，标了也没地方存、下次还是新的。
    """
    if not qrow or not material or qtype not in _PT_TYPES:
        return [], [], ""
    mats = _split_materials(material)
    refs = _q_mat_refs(question, mats)
    qmat = _q_scoped_material(question, mats, material)
    try:
        cached = json.loads(qrow["points"] or "[]")
    except Exception:
        cached = []
    if cached:
        return cached, refs, qmat
    # **一题一则**：shenlun_papers.material 存的是整份卷子的给定资料（材料一到五全在里面），
    # 而一道小题通常只对应其中某一则。不切就会拿整份去标 —— 实测一道 15 分的归纳概括，
    # 291 句材料标出 6 个点、coverage 10/42、max_gap 211，依据里全是别的题的材料
    # （问的是这一题，摘的是隔壁「鲁师傅烧饼」那则）。
    # 切法直接复用上传小题那条管线：按编号切成多则，只喂题干里引用的那一则。
    points, info, err = _find_points(qtype, question, qmat, full)
    if err:
        # 标不出来不该让整次批改失败 —— 退回「现场提炼」那条老路，照样能批
        log.warning("真题第 %s 题预标采分点失败，本次退回现场提炼：%s",
                    qrow["seq"], err[0].get("error") if isinstance(err, tuple) else err)
        return [], refs, qmat
    db.execute("UPDATE shenlun_questions SET points=?, near=? WHERE id=?",
               (json.dumps(points, ensure_ascii=False),
                json.dumps(info["near"]), qrow["id"]))
    db.commit()
    log.info("真题第 %s 题预标采分点 %d 个（给定资料%s，%d 句），coverage %d/%d，max_gap %d",
             qrow["seq"], len(points), refs or "全部", info["n_sents"],
             info["cov"]["cov_blocks"], info["cov"]["n_blocks"], info["cov"]["max_gap"])
    return points, refs, qmat


def _sl_q(db, qid):
    """真题某一小题（连它所在卷子的材料）。取不到返回 None。"""
    return db.execute(
        "SELECT q.*, p.material, p.id pid FROM shenlun_questions q "
        "JOIN shenlun_papers p ON p.id=q.paper_id WHERE q.id=? AND p.user_id=?",
        (qid, uid())).fetchone()


@bp.get("/api/shenlun/question/<int:qid>/find")
def sl_find_sents(qid):
    """练习模式第一步：把这道题对应的那一则材料**按句**下发，供勾画。

    **点的内容绝不下发**，只给个数 —— 跟小题训练那边一个道理，下发了前端一翻就看见答案。
    首次调用会惰性预标一次（约 2~3 分钟），之后走缓存。
    """
    db = get_db()
    q = _sl_q(db, qid)
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    pts, refs, qmat = _sl_std_points(db, q, q["qtype"], q["stem"] or "", q["material"] or "", q["full"])
    if not pts:
        return jsonify({"error": "这道题还标不出可勾画的要点，先用模考模式作答吧"}), 400
    sents = _find_sents(qmat)
    return jsonify({
        "id": q["id"], "seq": q["seq"], "qtype": q["qtype"], "type_name": q["type_name"],
        "stem": q["stem"], "full": q["full"], "word_min": q["word_min"], "word_max": q["word_max"],
        "n_points": len(pts), "refs": refs, "material_words": _sl_words(qmat),
        "is_essay": q["qtype"] == "zuowen",
        "sents": [{"i": i, "p": s["p"], "t": s["t"], "head": s["head"]}
                  for i, s in enumerate(sents)]})


@bp.post("/api/shenlun/question/<int:qid>/check")
def sl_find_check(qid):
    """练习模式第一步的判定：找对/找漏/找错/找重。判法与小题训练完全一致 ——
    两个模块用同一套采分点、同一套判定，练出来的标准才是一个。"""
    d = request.get_json(silent=True) or {}
    picked = sorted({int(x) for x in (d.get("sents") or [])})
    db = get_db()
    q = _sl_q(db, qid)
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    if not picked:
        return jsonify({"error": "先在材料里勾画你认为的要点句"}), 400
    points, _refs, qmat = _sl_std_points(db, q, q["qtype"], q["stem"] or "",
                                         q["material"] or "", q["full"])
    if not points:
        return jsonify({"error": "这道题没有可判定的要点"}), 400
    # _sl_std_points 若是这道题第一次标，会顺带把 near 写库；q 是调用前取的快照，
    # 这里还没重新查就直接用会拿到 None——沾边全被误判成找错，重新取一遍拿到刚写的值
    q = _sl_q(db, qid)
    sents = _find_sents(qmat)

    hit_by_point = [[i for i in picked if i in set(p["sents"])] for p in points]
    got = [i for i, g in enumerate(hit_by_point) if g]
    missed = [i for i, g in enumerate(hit_by_point) if not g]
    all_pt = {i for p in points for i in p["sents"]}
    near, wrong = _find_split_wrong(q, picked, all_pt)   # 沾边 vs 真找错，同小题一套口径
    dup = [{"point": points[i]["point"], "sents": g}
           for i, g in enumerate(hit_by_point) if len(g) > 1]
    return jsonify({
        "total": len(points), "found": len(got),
        "acc": round(100.0 * len(got) / len(points)) if points else 0,
        "ok": [{"point": points[i]["point"], "score": points[i]["score"],
                "sents": hit_by_point[i]} for i in got],
        "missed": [{"point": points[i]["point"], "score": points[i]["score"],
                    "sents": points[i]["sents"], "evidence": points[i]["evidence"]} for i in missed],
        "wrong": [{"i": i, "t": sents[i]["t"]} for i in wrong if i < len(sents)],
        "near": [{"i": i, "t": sents[i]["t"]} for i in near if i < len(sents)],
        "dup": dup})


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

    # 大作文的批改口径不动（还是立意/结构/论证/语言四维）—— 它的预标「点」是给
    # **练习模式的找点**用的备料，不是采分点，不能拿去当判分标尺。
    is_essay = key == "zuowen"
    std, std_refs = ([], []) if is_essay else _sl_std_points(db, qrow, key, question, material, full)[:2]
    if is_essay:
        dims = "、".join("%s（0-%d 分）" % (n, m) for n, m in _SL_DIMS)
        rubric = ("按固定的四个维度打分，points 里每个维度一条，顺序不变：%s。\n"
                  "（若本题满分不是 35 分，请按比例折算各维度满分。）\n"
                  'name=维度名，max=该维度满分，got=实际得分，yours=引用考生原文中最能体现该维度的一句，\n'
                  'hits=做得好的地方，misses=扣分点，material=（留空字符串）。' % dims)
    elif std:
        # 采分点是**预先标好**的（第一次批改这道题时生成并缓存），不再每次现场提炼。
        # 现场提炼的三个毛病一起解决：同一份答案两次批改分数不再飘（标尺固定了）、
        # 能说出漏的点在材料第几句（有原文锚点）、和小题训练用的是同一套标准。
        lst = "\n".join("%d. %s（%g 分）依据原文：%s" % (i + 1, p["point"], p["score"], p["evidence"][:70])
                        for i, p in enumerate(std))
        rubric = ("下面是这道题的**标准答案采分点**（阅卷组已定，考生看不到）。"
                  "**必须逐条照抄这几个点来评分，不许自己另立采分点、不许增删条数**：\n%s\n\n"
                  "points 里一条对一个采分点、**顺序不变**：\n"
                  'name=采分点原话（照抄上面的），max=上面给的分值，got=实际得分，\n'
                  'yours=考生答案里对应这一点的原文（没写到就填空字符串），\n'
                  'hits=已写到的要点，misses=未写到的要点，partial=部分写到的要点，\n'
                  'material=（留空，服务端会填上锚定好的原文）。' % lst)
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
        # 正文额度：points（每条含 yours/hits/misses/material 摘录）+ advice。
        # 这一步要现场提炼采分点再逐条比对，推理最重，额度留宽。
        rep, err = _ai_call_or_error(msgs, temperature=0.2, max_tokens=6000,
                                     timeout=300, json_mode=True, tier="pro")
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
    if std:
        # 用预标采分点批的：material 由服务端按**锚定好的原句**回填，别信模型转述。
        # 顺带把句号带上 —— 这是现场提炼那条路给不出来的东西，「漏的点在材料第几句」
        # 全靠它。分值也一律以标准答案为准，不让模型改 max。
        for i, p in enumerate(pts[:len(std)]):
            s = std[i]
            p["material"] = s["evidence"][:120]
            p["sents"] = s["sents"]
            p["max"] = s["score"]
        res["std_points"] = True          # 前端据此显示「按预标采分点评分（可复现）」
        # 句号是相对**那一则**给定资料的，不带上是哪一则，「第 8 句」就对不上页面里的整份材料
        res["std_refs"] = std_refs
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
