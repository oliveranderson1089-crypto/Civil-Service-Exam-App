"""议论文成文的「提纲 ↔ 正文」对齐：让提纲上的每一条论点，在正文里都真的找得到。

为什么非得有这一步：
  · 提纲和正文是 AI 一次输出的两个字段。写正文时它顺着衔接表达和素材走，段首常被引言顶掉
    （「善除害者察其本，善理疾者绝其源。」），提纲那条分论点就落空了；
  · 更要命的是 _write_gen 的「补素材」循环**只回写 content、不回写 outline**，
    补一轮正文就和提纲差一轮，补两轮差两轮。
提纲是拿来学结构的：分论点句该长什么样、该摆在哪。对不上，这页就白看了。

**怎么对齐，是量出来的，不是拍的。** 全库 38 篇扫了一遍：26 篇字面对不上，但拆开看，
绝大多数段首其实已经是分论点句了，只是换了个更文气的说法（提纲写「实干是成就事业的基石」，
正文写「执一而御万，实干的底层逻辑归根到底在于坚持实事求是、群众路线」）。
真正「段首只有引言、论点没亮」的只有少数几处。所以规则是**双向**的：

  · 段首已经是论点句（只是措辞不同）→ **两边都不动**。两种写法都值得学，
    只把正文里对应的那一句记下来，提纲页并排显示，好对照。
  · 段首只有引言/衔接、论点真没亮 → 把提纲那条**织进段首**（AI 织、服务端核对、机械兜底）。
  · 提纲那条压根跟这一段说的不是一回事（偏题）→ 不能硬塞，让 AI **照着这一段实际写的**
    重拟一条论点句，提纲和正文一起更新。

「段首是不是论点句」这件事字面相似度判不了（同一个意思能写得毫无重字），只能问 AI；
但 AI 说「已经有了」时**必须指出正文里逐字存在的那一句**，指不出来就不采信 ——
和这个项目里其它 AI 产出一个规矩：能自己核对的，绝不信它一面之词。

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
            it.update(para=j + 1, qpara=j + 1, quote=quote,
                      score=round(best, 3), exact=best >= TH_EXACT)
        out.append(it)
    return out


def _end(s):
    """补进正文的论点句要能收住 —— 提纲条目常常不带句号。"""
    s = (s or "").strip()
    return s if s and s[-1] in "。！？；!?;" else s + "。"


_SYS = "你是申论阅卷组的范文作者。只判断和调整论点句，绝不删改素材、事例、数据。严格输出 JSON。"


def _head_sents(ps, it):
    """这条论点该落在哪几句里 —— 判定和核对都只认这个范围。

    分论点只看对应段的**前两句**：论点句要么是第一句，要么被一句衔接顶到第二句；
    第三句往后就算撞上了，那也不叫「段首亮论点」，学的人照样一眼找不到。
    段末的回扣句尤其不能算 —— 实测 AI 最爱拿它来交差（「唯有…方能…」那种），
    可它恰恰证明了段首没亮论点。总论点则认开头段全段 + 结尾段（回扣是它的正常写法）。"""
    if it["kind"] == "thesis":
        return sents(ps[0]) + sents(ps[-1])
    return sents(ps[it["para"]])[:2]


def _ask(content, items):
    """问 AI：这几条论点，正文对应段落的段首到底亮出来没有？没亮的顺手织进去。

    一次调用把「判断」和「改写」一起做完 —— 分两次调是白花一次钱，中间还多一层错位风险。
    返回 {下标: {...}}，key 是 items 里的位置。失败返回 {}。"""
    ps = paras(content)
    ask = []
    for k, it in enumerate(items):
        if it["exact"] or it["para"] is None:
            continue
        # 「该看的位置」要和 _head_sents 划的范围**一字不差**：分论点是对应段的前两句，
        # 总论点是整个开头段 + 整个结尾段。标签写错范围，它就会去别处摘句子来交差。
        where = ("开头段和结尾段" if it["kind"] == "thesis"
                 else "第 %d 段的前两句" % (it["para"] + 1))
        ask.append("【%d】%s\n  提纲写的：%s\n  该看的位置——%s：%s"
                   % (k, "总论点" if it["kind"] == "thesis" else "分论点%d" % (it["i"] + 1),
                      it["text"], where, "".join(_head_sents(ps, it))))
    if not ask:
        return {}
    prompt = (
        "下面是一篇申论大作文的正文，和它的提纲。有几条论点，字面上在正文里找不到，"
        "要你逐条判断到底是**换了说法**还是**真的没写**。\n\n"
        "【正文】（按自然段编号）\n"
        + "\n".join("第 %d 段：%s" % (i + 1, p) for i, p in enumerate(ps))
        + "\n\n【要判断的条目】\n" + "\n\n".join(ask) + "\n\n"
        "【逐条给出 verdict】\n"
        "· has —— **上面给的那几句里**已经把这个论点亮出来了，只是换了说法。\n"
        "    这时必须填 quote：从**上面给的那几句里**逐字复制承担这个论点的那一句"
        "（一字不差，含标点）。⚠️ 不许从段落中间或段末的回扣句去找 —— 段末写「唯有…方能…」"
        "恰恰说明段首没亮论点，那种情况要判 none。复制不出原句就不能填 has。\n"
        "· none —— 段首只是引言、名句、衔接或直接进事例，**论点句没亮**，但这一段讲的内容"
        "确实就是提纲那条说的事。\n"
        "· offtopic —— 提纲那条和这一段实际写的**根本不是一回事**（跑题了）。\n\n"
        "verdict 是 none 或 offtopic 的，还要给：\n"
        "· point：要放在段首的论点句（none 就用提纲原话；offtopic 则**照着这一段实际写的内容**"
        "重拟一句，15~35 字，要和全文总论点一脉相承）\n"
        "· para：这一整段改写后的样子 —— **point 原样放在段首当第一句**，原来占着段首的引言、"
        "名句**不要删**，顺势挪到 point 后面接着说；这一段其余的内容、事例、数据**一字不动**。\n"
        "  （总论点这一条改的是**开头段**，请给开头段改写后的全文；总论点句按惯例收在开头段末尾。）\n\n"
        '只输出 JSON：{"items":[{"k":条目编号,"verdict":"has|none|offtopic",'
        '"quote":"","point":"","para":""}]}')
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=4000, timeout=300, json_mode=True)
    if err:
        return {}
    try:
        got = json.loads(rep).get("items") or []
    except Exception:
        return {}
    return {x["k"]: x for x in got if isinstance(x, dict) and isinstance(x.get("k"), int)}


def quick_report(content, outline):
    """不调 AI 的对照表 —— 人工编辑完正文用这个刷新。

    「这一段落在哪」「段首最像的是哪句」都算得出来，唯独「算不算已经亮了论点」算不出来
    （同一个意思能写得毫无重字），所以标 unsure，等点「对齐提纲」再让 AI 判。"""
    return [{"kind": x["kind"], "i": x["i"], "oi": x["oi"], "point": x["text"],
             "quote": x["quote"], "para": x["para"], "qpara": x["qpara"],
             "state": "exact" if x["exact"] else ("nopara" if x["para"] is None else "unsure")}
            for x in survey(content, outline)]


def align(content, outline, use_ai=True):
    """对齐一篇。返回 (新正文, 新提纲, 报告)。

    报告 = {"changed": bool, "log": [...], "items": [每条论点最终怎么落地的]}
    items 里每条：{kind,i,point,quote,para,state}
      exact     段首就是提纲那句，没动
      same      措辞不同但段首确实是论点句 —— 两边都没动，quote 是正文里对应那句（前端并排显示）
      woven     段首没亮论点，把提纲那句织进去了
      rewritten 提纲那条偏题，按正文实际内容重拟了一句，提纲和正文一起更新
      nopara    正文段数少于提纲条数，找不到对应段，只能报出来
    """
    items = survey(content, outline)
    # 没提纲、正文不足三段、或 outline 根本不是数组 —— 原样奉还，一个字都不动。
    # 注意返回的是 outline 本身而不是 list(outline)：后者会把字符串拆成逐字列表。
    if not items:
        return content, outline, {"changed": False, "log": [], "items": []}
    ps = paras(content)
    thesis, subs = split_outline(outline)
    ans = _ask(content, items) if use_ai and any(
        not x["exact"] and x["para"] is not None for x in items) else {}

    log, rep, new_subs, new_thesis = [], [], list(subs), thesis
    for k, it in enumerate(items):
        r = {"kind": it["kind"], "i": it["i"], "oi": it["oi"], "point": it["text"],
             "quote": it["quote"], "para": it["para"], "qpara": it["qpara"], "state": "exact"}
        if it["exact"]:
            rep.append(r)
            continue
        if it["para"] is None:
            r["state"] = "nopara"
            rep.append(r)
            continue
        a = ans.get(k) or {}
        v = a.get("verdict")
        quote = (a.get("quote") or "").strip()
        # AI 说「已经有了」，就得把那句原样指出来，而且必须落在**该看的那几句**里。
        # 实测它会拿段末回扣句来交差（正文里确实有这句，但不在段首）—— 只查「正文里有没有」
        # 是拦不住的，必须连位置一起核。指不出来就当它没说过。
        if v == "has":
            if quote and _flat(quote) in _flat("".join(_head_sents(ps, it))):
                r.update(state="same", quote=quote)     # 段首确实是论点句，换了说法而已 → 两边都不动
            else:
                # 说有、却指不出段首里的原句。不采信这个 has —— 可也不敢照 none 处理硬插一句，
                # 万一真是换了说法，插进去就成了同义重复。标 unsure 摆到前端去，人一眼能判、
                # 也能用编辑功能手改。宁可少改，不能改坏（和 _used_hit「宁可少列不能列错」同一条）。
                r["state"] = "unsure"
            rep.append(r)
            continue
        if v not in ("none", "offtopic"):
            r["state"] = "unsure"        # AI 没给准话（没答这条 / verdict 乱填）：谁都不动
            rep.append(r)
            continue

        point = strip_label((a.get("point") or "").strip()) or it["text"]
        newp = (a.get("para") or "").strip()
        # AI 改写的这一段必须：① 论点句真在该在的位置 ② 原有内容基本还在（它爱顺手重写整段）。
        # 位置**分论点看段首、总论点看段末**——开头段的规矩是「引材料 → 末尾亮总论点」，
        # 拿段首去卡总论点，AI 写对了也会被判失败、白白退回机械兜底。
        flatp, key = _flat(newp), _flat(point)[:10]
        ok = (newp and len(flatp) >= len(_flat(ps[it["para"]])) * 0.9
              and (flatp.endswith(_flat(point)[-10:]) if it["kind"] == "thesis"
                   else flatp.startswith(key)))
        if ok:
            ps[it["para"]] = newp
        elif it["kind"] == "thesis":
            ps[0] = ps[0].rstrip() + _end(point)         # 开头段的规矩：引材料 → 末尾亮总论点
        else:
            ps[it["para"]] = _end(point) + ps[it["para"]]
        r.update(state="rewritten" if v == "offtopic" else "woven", point=point,
                 quote="", qpara=it["para"])       # 补进去之后，这句就在归属段的段首了
        if it["kind"] == "thesis":
            new_thesis = point
        else:
            new_subs[it["i"]] = point
        log.append("%s：%s（%s）" % (
            "总论点" if it["kind"] == "thesis" else "分论点%d" % (it["i"] + 1),
            "提纲那条跑题了，照正文重拟一句" if v == "offtopic" else "论点句补进段首",
            "AI 织入" if ok else "机械插入兜底"))
        rep.append(r)

    changed = bool(log)
    new_outline = list(outline or [])
    if changed:
        new_outline = ([("总论点：" + new_thesis)] if thesis else []) + \
                      ["分论点%d：%s" % (i + 1, s) for i, s in enumerate(new_subs)]
    return ("\n".join(ps) if changed else content), new_outline, \
           {"changed": changed, "log": log, "items": rep}
