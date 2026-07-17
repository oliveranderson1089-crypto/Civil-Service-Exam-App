"""通用「划重点」：在任意长文本上划考点。

划重点：**按模块给不同的考点类型**。
一套「提法/数据/政策/金句」套到常识、理论、范文、错题上就是驴唇不对马嘴 ——
常识要划的是「定义、数字、易混、之最」，错题要划的是「陷阱、正解、知识点」，根本不是一回事。
key = 前端的视图名（scope）；name=模块叫什么；kinds=[(类型, 什么算这一类)]；focus=这个模块特有的看点。
"""
import hashlib
import json

from flask import Blueprint, jsonify, request

from core import get_db
from mods.ai import _ai_call_or_error

bp = Blueprint("marks", __name__)


MK_PROFILES = {
    "newsd": ("每日时政", [
        ("提法", "新表述/新概念，常识判断爱考"),
        ("数据", "具体数字/时间，最容易做成选项"),
        ("政策", "文件名/举措/目标"),
        ("金句", "能直接写进申论的表述"),
    ], "时政题考的是「谁在什么时候提出了什么」，所以新提法、时间数字、文件名优先。"),
    "policydocd": ("时政要文库", [
        ("提法", "首次出现的新表述、新概念"),
        ("目标", "到某年要达成什么（数字目标优先）"),
        ("举措", "具体怎么干的部署"),
        ("金句", "可直接写进申论的权威表述"),
    ], "这是中央文件原文，考点集中在「新提法」和「量化目标」。"),
    "csboard": ("常识积累", [
        ("定义", "概念本身、判断标准（选项就照这个改一个字）"),
        ("数字", "年份、数量、排名、之最"),
        ("易混", "容易和别的搞混的点，成对出现的"),
        ("常考", "真题反复考过的那一句"),
    ], "常识判断是**细节题**：选项往往只改一个字（把「最早」改成「唯一」）。"
       "所以要划的是**能被改动的那个词**，不是整段结论。"),
    "thboard": ("理论基础", [
        ("论断", "经典结论、核心命题（原话）"),
        ("时间", "会议/著作/提出的年份"),
        ("首提", "谁在哪首次提出（最爱考的就是这个）"),
        ("关系", "A 是 B 的什么（基础/前提/核心/根本）—— 位置关系一换就是错项"),
    ], "马原毛概中特习思想，考的是**归属和位置**：哪句话是谁说的、哪个是核心哪个是基础。"
       "「××是××的核心」这类句子必划。"),
    "workd": ("经典著作", [
        ("观点", "作者的核心主张"),
        ("背景", "什么时候、针对什么问题写的"),
        ("金句", "可以直接引用进申论的原话"),
        ("常考", "真题里出现过的段落"),
    ], "经典著作既考常识（哪篇哪年讲了什么），也是申论的引用来源。"),
    "partydict": ("创新理论词典", [
        ("定义", "这个术语到底指什么"),
        ("提法", "完整的官方表述（一个字都不能改）"),
        ("出处", "哪次会议/哪份文件提出的"),
    ], "术语题就考「完整表述」和「出处」，短语要连着划，别割裂。"),
    "essayd": ("范文", [
        ("分论点", "每段的论点句 —— 学的就是这个句式"),
        ("论证", "怎么把素材和论点扣上的那句话"),
        ("素材", "可以搬走复用的事例/数据"),
        ("表达", "亮点句式、衔接、结尾升华"),
    ], "看范文不是看内容，是**看它怎么写的**。要划的是可以搬走复用的「结构件」。"),
    "writed": ("成文", [
        ("分论点", "每段的论点句"),
        ("论证", "素材和论点怎么扣上的"),
        ("素材", "用进去的事例/理论/金句"),
        ("衔接", "段与段之间的过渡表达"),
    ], "这是用你自己的素材写的文章，要看清**素材是怎么被用进去的**。"),
    "wqdetail": ("错题", [
        ("陷阱", "题目在哪里下的套（你就是在这栽的）"),
        ("正解", "正确的思路是什么"),
        ("知识点", "这题背后要记住的那条"),
    ], "错题复盘只有一个目的：**下次别再错**。所以先划陷阱，再划正解。"),
    "slresult": ("批改结果", [
        ("扣分", "被扣分的地方，具体在哪一句"),
        ("亮点", "写得好、下次继续保持的"),
        ("改法", "应该怎么改"),
    ], "批改结果要划的是**可执行的动作**，不是分数。"),
    "sltype": ("题型讲义", [
        ("方法", "答题步骤、固定套路"),
        ("格式", "这个题型的作答格式要求"),
        ("易错", "阅卷最常扣分的地方"),
    ], "讲义要划的是**照着能做题的东西**。"),
    "boardkb": ("基础知识点", [
        ("概念", "定义、判断标准"),
        ("公式", "公式、口诀、速算技巧"),
        ("方法", "解题步骤"),
        ("易错", "最容易踩的坑"),
    ], "基础知识点要划的是**能直接拿去做题的**。"),
    "docqad": ("题目解析", [
        ("考点", "这题考的是什么"),
        ("陷阱", "干扰项是怎么设计的"),
        ("方法", "最快的解法"),
    ], "解析要划的是**方法**，不是答案。"),
    "cdetail": ("古诗文", [
        ("名句", "最常考、可引用的句子"),
        ("典故", "背后的故事/出处"),
        ("考点", "常识判断怎么考它（作者/朝代/体裁/主旨）"),
    ], "古诗文两头考：常识判断考作者朝代，申论要引用名句。"),
    "ckboard": ("常考", [
        ("释义", "到底什么意思"),
        ("易错", "最容易用错的地方（褒贬/对象/程度）"),
        ("辨析", "和近义词的区别"),
    ], "成语实词就考**用得对不对**，所以易错点和辨析最重要。"),
    "viewer": ("资料阅读", [
        ("结论", "可以直接背下来的结论"),
        ("方法", "怎么做的步骤"),
        ("数据", "数字、时间"),
        ("易错", "提醒注意的地方"),
    ], ""),
}
_MK_FALLBACK = ("备考材料", [
    ("提法", "新表述/新概念、关键定义"),
    ("数据", "具体数字/时间"),
    ("结论", "该记住的结论"),
    ("金句", "可以引用的表述"),
], "")


def mk_profile(scope):
    return MK_PROFILES.get(scope, _MK_FALLBACK)


def _mark_text(content, scope=""):
    """让 AI 在给定文字里**逐字挑出**要害句，标出考点类型。
       逐字是硬要求——挑出来的句子要能在原文里原样找到，否则前端标不上去；
       服务端逐条核对，对不上的直接丢弃（宁可少标，不能标错位置）。

       考点类型**按模块走**（见 MK_PROFILES）：常识划「定义/数字/易混」，
       错题划「陷阱/正解」，范文划「分论点/论证/表达」…… 一套模板套所有模块是没用的。"""
    content = (content or "").strip()
    if len(content) < 60:
        return [], "这页文字太少，不用划重点"
    name, kinds, focus = mk_profile(scope)
    names = [k for k, _ in kinds]
    prompt = (
        "下面是「%s」模块里的一段备考材料。考生没时间通读，请**划重点**：\n"
        "挑出 4~8 处最该记的地方，每处**必须从原文里逐字复制**（一字不差，含标点），"
        "否则没法在原文上标出来。\n\n"
        "%s\n"
        "每处给：\n"
        "· quote：从原文逐字复制的句子或短语（10~60 字，别整段抄）\n"
        "· kind：只能填 %s 之一\n%s"
        "· why：为什么要记它（一句话，讲清考点在哪，别复述原文）\n\n"
        '只输出 JSON：{"marks":[{"quote":"","kind":"","why":""}]}\n\n【原文】\n'
        % (name,
           ("【这个模块该看什么】%s\n" % focus) if focus else "",
           " / ".join(names),
           "".join("  · %s = %s\n" % (k, d) for k, d in kinds))
    ) + content[:5000]
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考老师，只从原文里逐字摘句，绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return None, err
    try:
        got = json.loads(rep).get("marks") or []
    except Exception:
        return None, "AI 返回格式异常，请重试"
    marks, seen = [], set()
    for m in got:
        q = (m.get("quote") or "").strip()
        if not q or q in seen or q not in content:      # 对不上原文的直接丢
            continue
        seen.add(q)
        marks.append({"quote": q,
                      "kind": m.get("kind") if m.get("kind") in names else names[0],
                      "why": (m.get("why") or "").strip()[:120]})
    return marks, ("" if marks else "AI 挑出的句子和原文对不上，请重试")


@bp.get("/api/marks/profile")
def marks_profile():
    """前端要知道当前模块划哪几类（好渲染颜色和说明），别在两边各写一份。"""
    name, kinds, focus = mk_profile((request.args.get("scope") or "")[:30])
    return jsonify({"name": name, "focus": focus,
                    "kinds": [{"k": k, "d": d} for k, d in kinds]})


@bp.post("/api/marks")
def marks_any():
    """通用划重点：任何模块的正文都能划。按内容哈希缓存，同一段内容全局只算一次。"""
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    scope = (d.get("scope") or "")[:30]
    if not text:
        return jsonify({"error": "没有可划的正文"}), 400
    # 缓存 key 要带 scope：同一段文字在不同模块划法不一样（常识划定义、错题划陷阱），
    # 只按文字哈希会串味
    ref = hashlib.md5((scope + "\x00" + text).encode("utf-8")).hexdigest()
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT data_json FROM marks_cache WHERE ref=?", (ref,)).fetchone()
        if r:
            return jsonify({"marks": json.loads(r["data_json"]), "cached": True})
    marks, err = _mark_text(text, scope)
    if marks is None:
        return err if isinstance(err, tuple) else (jsonify({"error": err}), 502)
    if not marks:
        return jsonify({"error": err or "没能划出重点"}), 502
    db.execute("INSERT OR REPLACE INTO marks_cache(ref,scope,data_json) VALUES(?,?,?)",
               (ref, scope, json.dumps(marks, ensure_ascii=False)))
    db.commit()
    return jsonify({"marks": marks})
