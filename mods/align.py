"""议论文成文的「提纲 ↔ 正文」对照：提纲与全文各自独立呈现，**只展示、不改写正文**。

从前这里会把提纲句硬织进段首、或按正文回头重拟提纲，把两者强行对齐 —— 那既容易改坏
已经写好的段落，又会一路把字数撑超（成文动辄破上限）。现在改成**提纲归提纲、全文归全文**：

  · 同义表述（正文这一段讲的就是这条分论点，只是换了说法）→ 正文**一字不动**，
    把正文里对应的那一句摘出来，当「另一种写作思路」并排显示（state=same，带 quote）。
    两种写法都值得学，并排看才对得上，而不是二选一、更不是回头改正文去凑提纲。
  · 补充缺失分论点（某条分论点在正文里**根本没有对应段落**，即正文段数少于提纲条数）→
    参考提纲补写**一段**，插在结尾段之前（state=added）；补写后全文仍须 ≤ wmax 字，
    塞不下就只报出来（state=nopara），绝不为补一段把字数写超。
  · 段首字面就是这条的 → state=exact，什么都不做。

关键约束：**正文里已有的段落，任何情况下都不改**。唯一会动正文的只有「补写一段全新的、
正文原本缺失的分论点段落」，且受字数上限约束。判定用字面相似度（sim）就够，不必调 AI ——
只有真要补写缺失段落时才调一次 AI 去写那一段。

「段首是不是论点句」字面相似度到 TH_EXACT 就算 exact；到不了但落在对应段里，就当同义表述。

只管议论文（mode = daily / compose）。应用文的 outline 存的是逐段批注 segs，不走这里。
"""
import json
import re
from collections import Counter

from mods.ai import _ai_call_or_error

# 字面相似度到这个分，就认定「段首就是提纲那句」，连 AI 都不用问，直接算对上。
# 0.45 是照全库实测定的：真·同一句（只多了个补充从句）普遍在 0.6 以上，换了说法的普遍在 0.45 以下。
TH_EXACT = 0.45

# 标签后面的分隔符是**必需的**：写成可选的话，「论点鲜明才立得住」这种正常句子会被
# 当成带标签的条目，剥成「鲜明才立得住」再插进正文，读者看到一句缺主语的残句。
_LABEL = re.compile(r"^\s*(总论点|中心论点|分论点|论点)\s*[0-9一二三四五六]*\s*[:：、.．]\s*")
_SENT = re.compile(r"[^。！？；!?;]+[。！？；!?;]?")


def strip_label(s):
    """去掉提纲条目自带的「总论点：」「分论点1：」前缀 —— 那是提纲的排版，不能跟着进正文。"""
    return _LABEL.sub("", (s or "").strip()).strip()


def _flat(s):
    return re.sub(r"\s", "", s or "")


def _norm(s):
    """比相似度前抹平差异：去标签、去标点空白，只留汉字数字字母。"""
    return re.sub(r"[^一-龥a-zA-Z0-9]", "", strip_label(s))


def sim(a, b):
    """字符二元组的 Dice 系数（0~1）。

    中文短句上比编辑距离稳：「创新是引领发展的第一动力」对「创新是引领发展的第一动力，
    需以制度创新突破瓶颈」能给到 0.69，换了说法的「良法是善治之前提……」只有 0.04，
    两档拉得开，中间没有模棱两可的一片。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    ga = [a[i:i + 2] for i in range(len(a) - 1)]
    gb = Counter(b[i:i + 2] for i in range(len(b) - 1))
    hit = 0
    for g in ga:
        if gb.get(g):
            gb[g] -= 1
            hit += 1
    return 2.0 * hit / (len(ga) + (len(b) - 1))


def paras(content):
    return [p.strip() for p in (content or "").split("\n") if p.strip()]


def sents(p):
    return [s.strip() for s in _SENT.findall(p or "") if s.strip()]


def split_outline(outline):
    """提纲条目 → (总论点, [分论点...])。

    提示词要的是 ["总论点","分论点1","分论点2","分论点3"]，但 AI 时灵时不灵：标签可能不写、
    条数可能是 3 也可能是 5。所以认标签优先，认不出来再按「4 条 = 1 总 + 3 分」的常规猜。

    ⚠️ 非列表一律当没有提纲。AI 偶尔会把 outline 写成一个字符串（json_mode 只保证是合法
    JSON，不保证字段类型），而字符串是可迭代的 —— 不挡住的话「总论点：发展」会被逐字拆成
    六条提纲条目，再原样写回库里。"""
    if not isinstance(outline, (list, tuple)):
        return "", []
    items = [x for x in outline if isinstance(x, str) and x.strip()]
    if not items:
        return "", []
    head = items[0].strip()
    is_thesis = bool(re.match(r"^\s*(总论点|中心论点)", head)) or (
        len(items) >= 4 and not re.match(r"^\s*分论点", head))
    if is_thesis:
        return strip_label(head), [strip_label(x) for x in items[1:]]
    return "", [strip_label(x) for x in items]


def _map_paras(subs, body):
    """分论点 → 中间段 的对应关系。返回 [段下标 或 None]，和 subs 等长。

    条数一样就一一对应（绝大多数情况）；对不齐时贪心：按**整段**相似度给每个分论点挑一段，
    挑过的段不再让。用整段而不是首句，正是因为段首那句可能就是被顶掉的 ——
    这一段讲的还是这个论点，主题匹配比句子匹配可靠。"""
    if len(subs) == len(body):
        return list(range(len(subs)))
    taken, out = set(), []
    for s in subs:
        best, bs = None, 0.0
        for j, p in enumerate(body):
            v = sim(s, p) if j not in taken else 0.0
            if v > bs:
                best, bs = j, v
        if best is not None:
            taken.add(best)
        out.append(best)
    return out


def survey(content, outline):
    """摸底：提纲每一条，字面上落没落在正文对应段落的段首。不改任何东西、不调 AI。

    返回 [{kind, i, oi, text, para, qpara, quote, score, exact}]：
      kind  thesis / sub
      oi    这条在 outline 数组里的下标 —— 前端照它对号入座。**别让前端自己推**：
            「第一条一定是总论点」在提纲只有分论点时就不成立，一推就整体错一格。
      para  这条论点**归属**哪一段（总论点归开头段 0），要补也是补在这儿
      qpara quote 实际取自哪一段。总论点常在结尾段回扣，和 para 不是一回事，
            分开存才不会出现「说第 1 段、引的却是最后一段」
      quote 该看的位置里和提纲最像的那一句（拿去给 AI 当判断的落点）
      exact 字面就已经对上了 → 这条到此为止，不用再问 AI
    """
    ps = paras(content)
    thesis, subs = split_outline(outline)
    if len(ps) < 3 or (not thesis and not subs):
        return []
    out = []
    if thesis:
        # 总论点按惯例亮在开头段（结尾段也常回扣一次）。两处都认，取最像的那句当落点。
        best, quote, qp = 0.0, "", 0
        for p_i in (0, len(ps) - 1):
            for s in sents(ps[p_i]):
                v = sim(thesis, s)
                if v > best:
                    best, quote, qp = v, s, p_i
        out.append({"kind": "thesis", "i": 0, "oi": 0, "text": thesis, "para": 0, "qpara": qp,
                    "quote": quote, "score": round(best, 3), "exact": best >= TH_EXACT})
    base = 1 if thesis else 0        # 分论点在 outline 里的起始下标
    body = ps[1:-1]          # 中间段 = 分论点段；首段是开头、末段是结尾
    for i, j in enumerate(_map_paras(subs, body)):
        it = {"kind": "sub", "i": i, "oi": base + i, "text": subs[i], "para": None,
              "qpara": None, "quote": "", "score": 0.0, "exact": False}
        if j is not None:
            # 只看这一段的前两句：论点句要么就是第一句，要么被一句衔接顶到了第二句。
            # 第三句往后即使撞上，那也不叫「段首亮论点」。
            best, quote = 0.0, ""
            for s in sents(body[j])[:2]:
                v = sim(subs[i], s)
                if v > best:
                    best, quote = v, s
            # 换了说法、字面一个重字都不共用时 best=0、quote 会空 —— 这条正要拿去当「另一种
            # 写作思路」并排显示，不能空。退回段首第一句：提示词要求每段开头先亮分论点，
            # 段首就是正文对这条的写法（哪怕是句引言，也正是这篇的实际开法，值得对照着学）。
            if not quote:
                ss = sents(body[j])
                quote = ss[0] if ss else ""
            it.update(para=j + 1, qpara=j + 1, quote=quote,
                      score=round(best, 3), exact=best >= TH_EXACT)
        out.append(it)
    return out


_SYS = "你是申论阅卷组的范文作者。只补写正文里缺失的那一段分论点，绝不删改已有的段落、素材、事例。严格输出 JSON。"


def _supplement(content, missing, wmax):
    """给正文里**没有对应段落**的分论点补写段落，插在结尾段之前。

    只在这一种情形下会动正文（新增段落，不碰已有段落），且边插边数字：补一段就把全文长度
    重算一遍，超了 wmax 的就不插了 —— 绝不为补一段把字数写超。
    返回 (新正文, 补了哪几条分论点的下标集合, log)。补不成就原样奉还、集合为空。"""
    ps = paras(content)
    if len(ps) < 2:
        return content, set(), []
    ask = "\n".join("【%d】%s" % (m["i"] + 1, m["text"]) for m in missing)
    prompt = (
        "下面这篇申论大作文缺了几个分论点段落（正文里没有讲到它们的段落）。"
        "请为每个分论点各补写**一段**正文：\n"
        "· 以该分论点句原样作为这一段的**第一句**；\n"
        "· 随后用 1~2 句展开（举个例子或讲清道理即可），每段 100~160 字；\n"
        "· 语气与全文一致，能独立成段。**不要改动、也不要重复已有的段落**。\n\n"
        "【现有正文】（按自然段编号）\n"
        + "\n".join("第 %d 段：%s" % (i + 1, p) for i, p in enumerate(ps))
        + "\n\n【要补写的分论点】\n" + ask + "\n\n"
        '只输出 JSON：{"items":[{"i":分论点编号,"para":"补写的这一整段"}]}')
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=300, json_mode=True)
    if err:
        return content, set(), []
    try:
        got = {int(x["i"]) - 1: (x.get("para") or "").strip()
               for x in json.loads(rep).get("items") or []
               if isinstance(x, dict) and x.get("para")}
    except Exception:
        return content, set(), []

    body, tail = ps[:-1], ps[-1:]          # 结尾段单独留出，补写段插在它前面
    added, log = set(), []
    cur = len(_flat(content))
    for m in missing:
        para = got.get(m["i"])
        if not para:
            continue
        # 论点句必须真在补写段的段首，否则不算补成功（宁可不补，不补错）
        head = _flat(strip_label(m["text"]))[:8]
        if head and not _flat(para).startswith(head):
            continue
        w = len(_flat(para))
        if cur + w > wmax:               # 补上就超字数了 —— 这条只报不补
            continue
        body.append(para)
        cur += w
        added.add(m["i"])
        log.append("分论点%d：正文原缺，已参考提纲补写一段" % (m["i"] + 1))
    if not added:
        return content, set(), []
    return "\n".join(body + tail), added, log


def quick_report(content, outline):
    """不调 AI 的对照表 —— 人工编辑完正文用这个刷新，和生成时同一把尺子。

    段首字面就是这条 → exact；正文里有对应段落但换了说法 → same（另一种写作思路）；
    正文里根本没有对应段落 → nopara。都是字面算得出的，不必调 AI。"""
    return [{"kind": x["kind"], "i": x["i"], "oi": x["oi"], "point": x["text"],
             "quote": x["quote"], "para": x["para"], "qpara": x["qpara"],
             "state": "exact" if x["exact"] else ("nopara" if x["para"] is None else "same")}
            for x in survey(content, outline)]


def align(content, outline, use_ai=True, wmax=1100):
    """对照一篇（只展示、不改写已有正文）。返回 (正文, 提纲, 报告)。

    提纲和正文各自独立，绝不为了「对齐」去改写已经写好的段落，也不回头重拟提纲。唯一会动
    正文的是「补写一段**正文原本缺失**的分论点段落」（受 wmax 字数上限约束）。

    报告 = {"changed": bool, "log": [...], "items": [每条论点在正文里怎么落地的]}
    items 里每条：{kind,i,oi,point,quote,para,qpara,state}
      exact   段首字面就是这条
      same    换了说法 —— 正文一字没动，quote 是正文对应段里最像的那句（前端当「另一种写作思路」并排显示）
      added   正文原本缺这条对应的段落，已参考提纲补写了一段
      nopara  正文缺这条对应的段落，且没能补（use_ai 关着，或补上会超字数）
    """
    items = survey(content, outline)
    # 没提纲、正文不足三段、或 outline 根本不是数组 —— 原样奉还，一个字都不动。
    # 注意返回的是 outline 本身而不是 list(outline)：后者会把字符串拆成逐字列表。
    if not items:
        return content, outline, {"changed": False, "log": [], "items": []}

    # 「正文里根本没有对应段落」的分论点（para is None）才补写。这是唯一会动正文的分支。
    missing = [it for it in items if it["kind"] == "sub" and it["para"] is None]
    added_i, log = set(), []
    if use_ai and missing:
        content, added_i, log = _supplement(content, missing, wmax)

    # 补写会新增段落、段号跟着挪，报告以补写后的正文重新摸一遍底。
    rep = []
    for it in survey(content, outline):
        if it["kind"] == "sub" and it["i"] in added_i:
            state = "added"
        elif it["exact"]:
            state = "exact"
        elif it["para"] is None:
            state = "nopara"
        else:
            state = "same"
        rep.append({"kind": it["kind"], "i": it["i"], "oi": it["oi"], "point": it["text"],
                    "quote": it["quote"], "para": it["para"], "qpara": it["qpara"], "state": state})
    return content, outline, {"changed": bool(log), "log": log, "items": rep}
