"""应用文：成文（写作） + 上位词（公文规范提法）。

GW_MAP / GW_DOCTYPES 定义在这儿，小题训练也要用——那边 import 过去，
链路仍单向：app.py → mods/find → mods/gongwen → core。
"""
import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from core import DB, bg_new, bg_set, get_db, log, uid
from mods.ai import _ai_call_or_error
from mods.align import align, quick_report
from mods.sucai import _sucai_import
from mods.write import _e_row, _used_hit, _write_gen

bp = Blueprint("gongwen", __name__)


# ---- 应用文成文 ----
# 应用文和大作文**根本不是一回事**：大作文考「怎么论证」，应用文考「格式 + 要点 + 语言得体」。
# 所以不能照搬那套「给一堆素材让它写」——必须先定三件事：
#   ① 文种（通知？倡议书？讲话稿？）—— 决定格式骨架和语气
#   ② 发文场景（就什么事发文）    —— 决定要点从哪来
#   ③ 我是谁 / 写给谁            —— 决定称谓、语气、能不能用「请遵照执行」这种话
# 产出也不一样：正文之外**必须给逐段批注**（这段是哪个部件、为什么这么写），
# 不然就又是一篇「看完不知道怎么学」的范文。
# 文种按「考什么」分四大类。每种都带一个**示范情景**（demo）——
# 第一次一键铺开时就用它，目的是先把「这个文种长什么样、格式怎么摆」看明白；
# 之后再针对同一文种换话题积累。
GW_DOCTYPES = [
    # ---- 宣传演讲类：面向人，讲究感染力和现场感 ----
    dict(k="讲话稿", cat="宣传演讲类", d="领导在某场合讲，有听众、有现场感",
         fmt="标题 / 称谓（同志们）/ 正文（开场→分条讲→结尾鼓劲）/ 无落款", min=500, max=800,
         demo=dict(scene="全区基层治理推进会", role="区政府分管副区长", audience="各街道、各部门负责同志")),
    dict(k="宣传稿", cat="宣传演讲类", d="贴在社区、发在公众号，给群众看的",
         fmt="标题 / 正文（引出→讲清楚→号召）/ 落款", min=400, max=600,
         demo=dict(scene="垃圾分类进社区", role="社区居委会工作人员", audience="全体社区居民")),
    dict(k="公开信", cat="宣传演讲类", d="以组织名义写给公众，语气恳切、有来有往",
         fmt="标题 / 称谓 / 正文（缘由→说明→呼吁）/ 落款（署名+日期）", min=400, max=600,
         demo=dict(scene="致全市市民的文明养犬公开信", role="市城市管理局", audience="全体市民")),
    dict(k="新闻稿", cat="宣传演讲类", d="报道一件事，客观、有导语、有数据和引语",
         fmt="标题（实题）/ 导语（何时·何地·何事·何果）/ 主体（展开+数据+引语）/ 结语", min=400, max=600,
         demo=dict(scene="我区数字政务服务大厅正式启用", role="区融媒体中心记者", audience="社会公众")),
    dict(k="倡议书", cat="宣传演讲类", d="面向公众发出号召，靠感染力不靠命令",
         fmt="标题 / 称谓 / 正文（缘由→倡议内容分条→号召）/ 落款", min=400, max=600,
         demo=dict(scene="节约用水", role="市水务局", audience="全体市民")),
    # ---- 总结说明类：面向上级/同行，讲究条理和成效 ----
    dict(k="汇报", cat="总结说明类", d="把一段工作向上级说清楚：做了什么、效果如何、下一步",
         fmt="标题 / 称谓 / 正文（概述→做法分条→成效→下一步）/ 落款", min=500, max=800,
         demo=dict(scene="老旧小区改造工作", role="区住建局", audience="市住建局")),
    dict(k="调研报告", cat="总结说明类", d="调查了什么、发现什么问题、建议怎么办",
         fmt="标题 / 正文（背景→现状→问题→建议）/ 落款", min=500, max=800,
         demo=dict(scene="农村电商发展现状调研", role="县商务局调研组", audience="县政府")),
    dict(k="简报", cat="总结说明类", d="短平快，一件事一页纸，给上级看",
         fmt="标题 / 正文（概述→做法分条→成效）/ 落款", min=400, max=600,
         demo=dict(scene="防汛应急演练", role="县应急管理局", audience="县委县政府")),
    dict(k="案例介绍", cat="总结说明类", d="讲一个能被别人学走的做法：背景→做法→成效→启示",
         fmt="标题 / 正文（背景→做法→成效→启示）", min=400, max=600,
         demo=dict(scene="某镇「一网通办」便民服务经验", role="镇政府办公室", audience="全县各乡镇")),
    dict(k="编者按", cat="总结说明类", d="放在文章前面的一小段，点题+评价+引导读下去",
         fmt="短标题或无标题 / 正文（点明主题→评价意义→引导阅读）", min=200, max=400,
         demo=dict(scene="为一组基层减负报道写编者按", role="报社编辑", audience="读者")),
    # ---- 方案建议类：面向执行，讲究可落地 ----
    dict(k="方案", cat="方案建议类", d="怎么干的通盘安排：目标、措施、分工、保障",
         fmt="标题 / 正文（指导思想→工作目标→主要措施→组织保障）/ 落款", min=500, max=800,
         demo=dict(scene="社区养老服务提升行动", role="街道办事处", audience="辖区各社区")),
    dict(k="建议书", cat="方案建议类", d="向某单位提意见，要有理有据、可执行",
         fmt="标题 / 称谓 / 正文（问题→建议分条→结语）/ 落款", min=400, max=600,
         demo=dict(scene="改善校园周边交通秩序", role="学校家长委员会", audience="区交警大队")),
    dict(k="通知", cat="方案建议类", d="上级发给下级，告知事项并要求落实",
         fmt="标题（发文机关+事由+文种）/ 主送机关 / 正文（缘由→事项→要求）/ 落款", min=400, max=600,
         demo=dict(scene="开展安全生产大检查", role="市安全生产委员会办公室", audience="各县区、各成员单位")),
    # ---- 观点主张类：面向读者，讲究观点鲜明 ----
    dict(k="短评", cat="观点主张类", d="就一件事表态：观点鲜明、篇幅短、有回味",
         fmt="标题 / 正文（亮观点→析原因→提办法）", min=300, max=500,
         demo=dict(scene="如何看待「指尖上的形式主义」", role="评论员", audience="读者")),
]
GW_CATS = ["宣传演讲类", "总结说明类", "方案建议类", "观点主张类"]
GW_MAP = {d["k"]: d for d in GW_DOCTYPES}

# ---- 应用文成文的字数：上限统一 ≤500 字，下限按「文种 + 题位」灵活定 ----
# 真题里同一题材，放在第二题和第四题，要求字数差很多——用「题位档」建模这件事：
#   越靠后的题（分值越大）字数要求越大。三档对应小题位/中题位/大题位。
MAX_YY_WORDS = 500
POS_BANDS = {
    "small": (200, 320),    # 靠前的小题位（如第一、二题）
    "medium": (280, 420),   # 中间题位（如第三题）
    "large": (360, 500),    # 靠后的大题位（如第四题·贯彻执行主力题）
}
POS_LABEL = {"small": "小题位（如第一二题）", "medium": "中题位（如第三题）", "large": "大题位（如第四题）"}
# 有的文种天生就短，放在大题位也不该硬撑到 500 —— 给它们各自的自然上限
GW_CAP = {"短评": 380, "编者按": 380, "简报": 420, "新闻稿": 450, "案例介绍": 450,
          "宣传稿": 460, "公开信": 470, "倡议书": 470, "建议书": 480}


def _word_band(doctype, pos):
    """按题位档取字数区间，再用文种自然上限和 500 硬顶收一下。返回 (下限, 上限)。"""
    lo, hi = POS_BANDS.get(pos, POS_BANDS["medium"])
    hi = min(hi, GW_CAP.get(doctype, MAX_YY_WORDS), MAX_YY_WORDS)
    lo = max(150, min(lo, hi - 60))     # 保证下限 < 上限、且留出至少 60 字区间
    return lo, hi


@bp.get("/api/write/gwspec")
def write_gwspec():
    """文种清单 + 推荐的发文场景（从最近的概括句话题和时政标题里来，不用自己想）。"""
    db = get_db()
    scenes = [r[0] for r in db.execute(
        "SELECT DISTINCT topic FROM gaikuo_items WHERE topic!='' ORDER BY date DESC LIMIT 10")]
    for r in db.execute("SELECT title FROM news_items ORDER BY id DESC LIMIT 6"):
        t = (r[0] or "").split("｜")[-1].strip()
        if t and len(t) <= 22 and t not in scenes:
            scenes.append(t)
    return jsonify({"doctypes": GW_DOCTYPES, "cats": GW_CATS, "scenes": scenes[:12]})


def _gen_yingyong(db, spec, mode="yingyong", date=None):
    """form='full' 出完整范文；form='outline' 出**提纲纲要**。

    mode/date：默认 'yingyong'（文种大全/自选成文，按时间戳存、可多篇）；
    传 'yingyong-daily' + 某天 → 每日成文（一天一篇、按日期存，可覆盖重写）。

    提纲纲要**本身不是文种**，是一种呈现方式（框架式、要点式），任何文种都能套。
    所以它和范文共用一套「文种 + 场景 + 身份」，只是产出从「成篇的文章」换成「骨架 + 要点」。
    先看提纲再看范文，才知道一篇文章是怎么长出来的。"""
    doctype = spec.get("doctype") or "通知"
    if doctype not in GW_MAP:
        return None, (jsonify({"error": "不认识这个文种"}), 400)
    form = "outline" if spec.get("form") == "outline" else "full"
    g = GW_MAP[doctype]
    demo = g["demo"]
    scene = (spec.get("scene") or "").strip() or demo["scene"]
    role = (spec.get("role") or "").strip() or demo["role"]
    audience = (spec.get("audience") or "").strip() or demo["audience"]
    desc, fmt = g["d"], g["fmt"]
    pos = spec.get("pos") if spec.get("pos") in POS_BANDS else "medium"   # 自选/文种大全默认中题位；每日成文会按天传档
    wmin, wmax = _word_band(doctype, pos)

    # 公文规范表述按「结构部件」归好类了（开头·缘由 / 主体·举措 / 结尾·号召…），正好是骨架
    gw = [dict(r) for r in db.execute(
        "SELECT scene, phrases, doctype FROM gongwen_items ORDER BY id")]
    pool = "\n".join("· 【%s】%s" % (x["scene"], x["phrases"]) for x in gw)
    # 场景相关的素材（有就用，没有不强求）
    kw = "%" + scene[:6] + "%"
    facts = [dict(r) for r in db.execute(
        "SELECT sentence FROM gaikuo_items WHERE topic LIKE ? OR sentence LIKE ? LIMIT 5", (kw, kw))]
    quotes = [dict(r) for r in db.execute(
        "SELECT quote FROM xiyu_items WHERE quote LIKE ? LIMIT 3", (kw,))]

    head = ("写一篇申论**应用文**范文。\n\n" if form == "full" else
            "给这个文种写一份**提纲纲要**。\n"
            "⚠️ 提纲**不是**缩写版的文章：它是**框架式、要点式**的呈现——把骨架摆出来，"
            "每个部件下面用短句列要点（这一块放什么、写到什么程度、用哪种表述），"
            "**不要写成成篇的段落**。目的是让人一眼看清「这个文种由哪几块组成、每块该放什么」。\n\n")

    setting = (
        "【题目设定】\n"
        "· 文种：%s（%s）\n"
        "· 就什么事发文：%s\n"
        "· 我的身份：%s\n"
        "· 写给谁看：%s\n"
        "· 格式骨架：%s\n"
        "· %s\n\n"
        "【可用的规范表述】（公文的「零件」，按结构部件归好类了，请对号入座地用）\n%s\n\n"
        "%s%s"
        % (doctype, desc, scene, role, audience, fmt,
           ("字数：%d~%d 字（正文，不含标题落款）" % (wmin, wmax)) if form == "full"
           else "提纲总字数控制在 300 字以内，要点短、密度高",
           pool,
           ("【这个话题的规范表述】\n" + "\n".join("· " + f["sentence"] for f in facts) + "\n\n") if facts else "",
           ("【可用金句】\n" + "\n".join("· " + q["quote"] for q in quotes) + "\n\n") if quotes else ""))

    if form == "full":
        req = (
            "【硬要求】\n"
            "1. **格式必须对**：该有标题就有标题、该有称谓就有称谓、该有落款就有落款。"
            "落款单位用「××」代替（不要编真单位名）。"
            "**落款和日期各自单独成行、放在全文最后**（倒数第二行是署名机关、最后一行是日期，"
            "形如「××市××局」换行「2025年4月1日」），不要和正文混在一起。\n"
            "2. **语气必须对身份**：上级发下级可以「请遵照执行」；面向群众的倡议书、公开信"
            "**不能用命令口气**，要靠感染力；讲话稿要有现场感（同志们、大家）；"
            "新闻稿要客观，不许抒情。\n"
            "3. **正文结构照历年真题的答法来**：能分条的文种（通知 / 方案 / 汇报 / 调研报告 / "
            "建议书 / 简报 / 案例介绍等）主体用「一、二、三、」或「（一）（二）（三）」这类"
            "**规范序号**分条，每条先亮做法再讲怎么落地，**不要拿「首先 / 其次 / 最后」这类连接词"
            "当骨架**；面向群众、重感染力的文种（倡议书 / 公开信 / 讲话稿 / 宣传稿 / 短评）可用"
            "连贯的行文段落，但也要**分层分段**。\n"
            "4. **分段合理**：正文按层次分段，一段讲清一层意思（一般 2~5 句），"
            "**严禁一句话一个自然段**；分条项内部若有展开，也放在同一段里。\n"
            "5. **字数**：正文控制在 %d~%d 字（不含标题和落款日期），**绝不超过 %d 字**——"
            "宁可精炼也别注水。\n"
            "6. 上面的规范表述要**用进去**，别自己造大白话。\n\n"
            % (wmin, wmax, MAX_YY_WORDS)) + (
            "【最重要的一条】除了正文，还要给**逐段批注**：把全文拆成若干段，每段说清楚\n"
            "· part：这一段是哪个部件（标题 / 称谓 / 开头·缘由 / 主体·举措 / 主体·成效 / "
            "结尾·号召 / 结尾·要求 / 落款 …）\n"
            "· text：这一段的原文（**从正文里逐字复制**，一字不差）\n"
            "· why：为什么这么写、阅卷看的是什么（一句话，讲考点，别复述原文）\n"
            "—— 没有批注的范文，看完还是不知道怎么学。\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"全文（含标题、称谓、落款，用 \\n 分行）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这个文种最容易丢分的地方"}')
    else:
        req = (
            "【硬要求】\n"
            "1. **按格式骨架逐块列**，一块都不能少（该有称谓就写「称谓：…」，该有落款就写「落款：…」）。\n"
            "2. 每块下面用「· 」列 2~4 条要点，每条是**短句**（10~25 字），说清这一块放什么、"
            "怎么起头。**不要写成完整段落，不要展开论述**。\n"
            "3. 主体部分要标出**分条的条数和每条讲什么**（一是…／二是…／三是…）。\n"
            "4. 该用规范表述的地方，直接把表述写进要点里（如「开头用『为深入贯彻…、结合…实际』」）。\n\n"
            "还要给**逐块说明**：\n"
            "· part：这一块是哪个部件\n"
            "· text：提纲里这一块的原文（**逐字复制**，一字不差）\n"
            "· why：这一块阅卷看什么、最容易丢分在哪（一句话）\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"提纲全文（用 \\n 分行，块名顶格、要点用「· 」缩进）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这个文种的提纲最关键的是哪一块"}')

    prompt = head + setting + req

    # 范文超 500 字就自动重写一次（提示词管不死，加道硬兜底）。用整份 d 重来，批注不会错位。
    d, content = None, ""
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + (
            "\n\n⚠️ 上一版超了字数，这一版**务必把正文压到 %d 字以内**，删次要修饰、保住要点和格式。" % MAX_YY_WORDS)
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的应用文范文作者。格式是第一位的，"
                                           "语气要合身份。严格输出 JSON。"},
             {"role": "user", "content": p}],
            temperature=0.5, max_tokens=3500, timeout=300, json_mode=True)
        if err:
            return None, err
        try:
            d = json.loads(rep)
        except Exception:
            return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)
        content = (d.get("content") or "").strip()
        if not content:
            return None, (jsonify({"error": "AI 没写出正文，请重试"}), 502)
        if form != "full" or len(re.sub(r"\s", "", content)) <= MAX_YY_WORDS:
            break     # 提纲不卡字数；范文达标就收工，否则再压一次

    # 批注的 text 必须真的来自正文，否则点了跳不过去、也说明它在瞎编
    flat = re.sub(r"\s", "", content)
    segs = []
    for s in (d.get("segs") or []):
        t = (s.get("text") or "").strip()
        if not t or re.sub(r"\s", "", t) not in flat:
            continue
        segs.append({"part": (s.get("part") or "").strip()[:12],
                     "text": t, "why": (s.get("why") or "").strip()[:140]})
    # 用了哪些规范表述：直接回正文里扫（别问 AI，它虚报也漏报）
    used = []
    for x in gw:
        hit = [p for p in re.split(r"[、,，]", x["phrases"])
               if len(p.replace("…", "").strip()) >= 2
               and all(y in content for y in p.split("…") if len(y.strip()) >= 2)]
        if hit:
            used.append({"sec": x["scene"], "text": "、".join(hit[:4])})

    words = len(re.sub(r"\s", "", content))
    date_val = date or time.strftime("%Y-%m-%d %H:%M:%S")
    if date:                       # 每日成文按日期存：先删掉这天旧的（重写就覆盖）
        db.execute("DELETE FROM daily_essays WHERE mode=? AND date=?", (mode, date_val))
    db.execute("INSERT INTO daily_essays(mode,date,topic,title,outline,content,words,used,note,spec) "
               "VALUES(?,?,?,?,?,?,?,?,?,?)",
               (mode, date_val, doctype, (d.get("title") or "").strip(),
                json.dumps(segs, ensure_ascii=False), content, words,
                json.dumps(used, ensure_ascii=False), (d.get("note") or "").strip(),
                json.dumps({"doctype": doctype, "scene": scene, "role": role,
                            "audience": audience, "form": form, "cat": g["cat"],
                            "pos": pos, "wmin": wmin, "wmax": wmax}, ensure_ascii=False)))
    db.commit()
    eid = db.execute("SELECT id FROM daily_essays WHERE mode=? AND date=? ORDER BY id DESC LIMIT 1",
                     (mode, date_val)).fetchone()[0]
    return eid, None


def _pick_daily_yy(db, date):
    """每日成文：按日期轮一个文种（循环覆盖全部文种），场景优先取近期时政标题，
    保证每天不同、贴近热点；没有时政就退回该文种的示范情景。"""
    try:
        ordinal = datetime.strptime(date[:10], "%Y-%m-%d").toordinal()
    except Exception:
        ordinal = 0
    g = GW_DOCTYPES[ordinal % len(GW_DOCTYPES)]
    scenes = []
    for r in db.execute("SELECT title FROM news_items ORDER BY id DESC LIMIT 40"):
        t = (r[0] or "").split("｜")[-1].strip()
        if t and len(t) <= 22 and t not in scenes:
            scenes.append(t)
    scene = scenes[ordinal % len(scenes)] if scenes else g["demo"]["scene"]
    # 题位也按天轮换：让你练到同一类文种在「小题位 / 中题位 / 大题位」下不同的字数要求
    pos = ["small", "medium", "large"][ordinal % 3]
    return {"doctype": g["k"], "scene": scene, "form": "full", "pos": pos}


def _gen_yy_compose(db, date):
    """综合应用能力大题：AI 出一段给定材料 + 作答要求，再写出参考范文（带逐段批注）。
    存 mode='yingyong-compose'，一天一篇、可重写覆盖。材料/要求放进 spec，正文只存范文。"""
    seeds = []
    for r in db.execute("SELECT title FROM news_items ORDER BY id DESC LIMIT 12"):
        t = (r[0] or "").split("｜")[-1].strip()
        if t and len(t) <= 24:
            seeds.append(t)
    for r in db.execute("SELECT DISTINCT topic FROM gaikuo_items WHERE topic!='' ORDER BY date DESC LIMIT 8"):
        if r[0]:
            seeds.append(r[0])
    seed_txt = ("【可选背景（挑一个改编成情景，别照抄标题）】\n"
                + "\n".join("· " + s for s in seeds[:12]) + "\n\n") if seeds else ""
    doctypes = "、".join(g["k"] for g in GW_DOCTYPES)
    prompt = (
        "出一道申论 / 事业单位**综合应用能力**大题，并写出参考范文。要像真考题：\n"
        "① 先给一段【给定材料】（250~400 字，含背景、几条要点或数据、可有一句引语），"
        "材料要具体、有情境，不要空泛口号；\n"
        "② 再给【作答要求】：写明要写的文种（从这些里选一个：%s）、以谁的身份、写给谁、"
        "**字数要求**（综合应用是大题位，设在 360~500 字之间，且**绝不超过 500 字**）；\n"
        "③ 然后按要求写出【参考范文】，格式要照历年真题答案来：\n"
        "   · 该有标题 / 称谓 / 落款就有，单位用「××」代替；**落款和日期各自单独成行、放在最后**"
        "（倒数第二行署名机关、最后一行日期，如「××市××局」换行「2025年4月1日」），别和正文混在一起；\n"
        "   · 能分条的文种（通知 / 方案 / 汇报 / 调研报告 / 建议书 / 简报等）主体用「一、二、三、」"
        "或「（一）（二）（三）」**规范序号**分条，别用「首先 / 其次 / 最后」当骨架；面向群众的"
        "（倡议书 / 公开信 / 讲话稿 / 短评）可用连贯段落但要分层；\n"
        "   · **分段合理**：一段讲清一层意思（2~5 句），**严禁一句话一个自然段**；语气合身份、用词规范；\n"
        "④ 给范文的**逐段批注** segs：把范文拆段，每段说清 part（部件名）、text（从范文逐字复制）、"
        "why（这段阅卷看什么、为什么这么写，一句话）。\n\n"
        "%s"
        "只输出 JSON：\n"
        '{"doctype":"选定的文种","material":"给定材料全文（用 \\n 分行）",'
        '"task":"作答要求全文（用 \\n 分行）","title":"范文标题",'
        '"content":"范文全文（含标题、称谓、落款，用 \\n 分行）",'
        '"segs":[{"part":"","text":"","why":""}],'
        '"note":"一句话说明这类综合应用最容易丢分的地方"}'
        % (doctypes, seed_txt))
    # 范文超 500 字就自动重出一次（硬兜底）
    d, content, material, task = None, "", "", ""
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + (
            "\n\n⚠️ 上一版范文超了字数，这一版**务必把范文压到 %d 字以内**，删次要修饰、保住要点和格式。" % MAX_YY_WORDS)
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的应用文范文作者，也擅长命制综合应用能力大题。"
                                           "格式是第一位的，语气要合身份。严格输出 JSON。"},
             {"role": "user", "content": p}],
            temperature=0.6, max_tokens=4000, timeout=300, json_mode=True)
        if err:
            return None, err
        try:
            d = json.loads(rep)
        except Exception:
            return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)
        content = (d.get("content") or "").strip()
        material = (d.get("material") or "").strip()
        task = (d.get("task") or "").strip()
        if not content or not material:
            return None, (jsonify({"error": "AI 没出全题，请重试"}), 502)
        if len(re.sub(r"\s", "", content)) <= MAX_YY_WORDS:
            break
    doctype = (d.get("doctype") or "").strip()
    flat = re.sub(r"\s", "", content)
    segs = []
    for s in (d.get("segs") or []):
        t = (s.get("text") or "").strip()
        if not t or re.sub(r"\s", "", t) not in flat:
            continue
        segs.append({"part": (s.get("part") or "").strip()[:12],
                     "text": t, "why": (s.get("why") or "").strip()[:140]})
    gw = [dict(r) for r in db.execute("SELECT scene, phrases FROM gongwen_items ORDER BY id")]
    used = []
    for x in gw:
        hit = [p for p in re.split(r"[、,，]", x["phrases"])
               if len(p.replace("…", "").strip()) >= 2
               and all(y in content for y in p.split("…") if len(y.strip()) >= 2)]
        if hit:
            used.append({"sec": x["scene"], "text": "、".join(hit[:4])})
    words = len(re.sub(r"\s", "", content))
    wmin, wmax = _word_band(doctype, "large")          # 综合应用是大题位
    mode = "yingyong-compose"
    db.execute("DELETE FROM daily_essays WHERE mode=? AND date=?", (mode, date))
    db.execute("INSERT INTO daily_essays(mode,date,topic,title,outline,content,words,used,note,spec) "
               "VALUES(?,?,?,?,?,?,?,?,?,?)",
               (mode, date, doctype or "综合应用", (d.get("title") or "").strip(),
                json.dumps(segs, ensure_ascii=False), content, words,
                json.dumps(used, ensure_ascii=False), (d.get("note") or "").strip(),
                json.dumps({"kind": "compose", "doctype": doctype,
                            "material": material, "task": task, "form": "full",
                            "pos": "large", "wmin": wmin, "wmax": wmax},
                           ensure_ascii=False)))
    db.commit()
    eid = db.execute("SELECT id FROM daily_essays WHERE mode=? AND date=? ORDER BY id DESC LIMIT 1",
                     (mode, date)).fetchone()[0]
    return eid, None


@bp.get("/api/write/yylist")
def write_yylist():
    """按「类别 → 文种」把已有的范文和提纲摆出来 —— 哪个文种还没见过，一眼看见。"""
    rows = [_e_row(r) for r in get_db().execute(
        "SELECT * FROM daily_essays WHERE mode='yingyong' ORDER BY id DESC")]
    by = {}
    for r in rows:
        k = (r["spec"] or {}).get("doctype") or r["topic"]
        by.setdefault(k, {"full": [], "outline": []})
        f = (r["spec"] or {}).get("form") or "full"
        by[k][f].append({"id": r["id"], "title": r["title"],
                         "scene": (r["spec"] or {}).get("scene") or "", "words": r["words"]})
    cats = []
    for c in GW_CATS:
        ds = []
        for g in GW_DOCTYPES:
            if g["cat"] != c:
                continue
            got = by.get(g["k"]) or {"full": [], "outline": []}
            ds.append({"k": g["k"], "d": g["d"], "fmt": g["fmt"],
                       "full": got["full"], "outline": got["outline"]})
        cats.append({"cat": c, "doctypes": ds})
    n_full = sum(1 for g in GW_DOCTYPES if (by.get(g["k"]) or {}).get("full"))
    n_out = sum(1 for g in GW_DOCTYPES if (by.get(g["k"]) or {}).get("outline"))
    return jsonify({"cats": cats, "total": len(GW_DOCTYPES),
                    "have_full": n_full, "have_outline": n_out})


@bp.post("/api/write/yingyong/batch")
def write_yy_batch():
    """第一次用：把**每个文种**各铺一篇（范文 + 提纲），先把格式和结构看明白。
       之后就是针对同一文种换话题积累了，不用再跑这个。"""
    db = get_db()
    have = set()
    for r in db.execute("SELECT spec FROM daily_essays WHERE mode='yingyong'"):
        try:
            sp = json.loads(r[0] or "{}")
            have.add((sp.get("doctype"), sp.get("form") or "full"))
        except Exception:
            log.debug("daily_essays.spec 不是合法 JSON，已跳过", exc_info=True)
    todo = [(g["k"], f) for g in GW_DOCTYPES for f in ("outline", "full")
            if (g["k"], f) not in have]                   # 先出提纲再出范文：先看骨架，再看成品
    if not todo:
        return jsonify({"error": "所有文种的提纲和范文都齐了"}), 400
    tid = bg_new(db, "yingyong", "铺开应用文 %d 篇" % len(todo), len(todo))

    flask_app = current_app._get_current_object()   # 线程里没有请求上下文，先在这儿取住真 app

    def run():
        con = sqlite3.connect(DB, timeout=60)
        con.row_factory = sqlite3.Row
        ok = 0
        try:
            for i, (dt, form) in enumerate(todo):
                bg_set(con, tid, status="running", progress=i,
                        message="正在写 %s·%s（%d/%d）"
                                % (dt, "提纲" if form == "outline" else "范文", i + 1, len(todo)))
                try:
                    with flask_app.app_context():
                        _, err = _gen_yingyong(con, {"doctype": dt, "form": form})
                    if not err:
                        ok += 1
                except Exception:             # 单篇失败不拖垮整批，再点一次会补上没写的
                    log.warning("批量生成应用文：%s/%s 这篇失败", dt, form, exc_info=True)
            bad = len(todo) - ok
            bg_set(con, tid, status="done", progress=len(todo),
                    message="写好 %d 篇%s" % (ok, "（%d 篇失败，可再点一次补）" % bad if bad else ""))
        except Exception as ex:
            bg_set(con, tid, status="error", message=str(ex)[:200])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid, "total": len(todo)}), 202


@bp.post("/api/write/yingyong")
def write_yingyong():
    db = get_db()
    eid, err = _gen_yingyong(db, request.get_json(silent=True) or {})
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()))


# ---- 应用文 · 每日成文（AI 每天出一道应用文题，一天一篇，可补齐往期）----
@bp.get("/api/write/yingyong/days")
def write_yy_days():
    """列最近 14 天，每天计划一个文种、写了没有。"""
    db = get_db()
    today = datetime.now().date()
    have = {r["date"]: r for r in db.execute(
        "SELECT date,id,title,topic,words FROM daily_essays WHERE mode='yingyong-daily'")}
    out = []
    for i in range(14):
        dt = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        plan = _pick_daily_yy(db, dt)
        r = have.get(dt)
        lo, hi = _word_band(plan["doctype"], plan["pos"])
        out.append({"date": dt, "doctype": plan["doctype"], "scene": plan["scene"],
                    "pos": plan["pos"], "pos_label": POS_LABEL.get(plan["pos"], ""),
                    "wmin": lo, "wmax": hi,
                    "eid": r["id"] if r else None,
                    "title": r["title"] if r else "", "topic": r["topic"] if r else "",
                    "words": r["words"] if r else 0})
    return jsonify({"days": out})


@bp.post("/api/write/yingyong/daily")
def write_yy_daily():
    d = request.get_json(silent=True) or {}
    date = (d.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify({"error": "日期不对"}), 400
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='yingyong-daily' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    eid, err = _gen_yingyong(db, _pick_daily_yy(db, date), mode="yingyong-daily", date=date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()))


@bp.post("/api/write/yingyong/compose")
def write_yy_compose():
    """综合应用能力大题：AI 出材料 + 要求 + 范文，每天一篇。"""
    d = request.get_json(silent=True) or {}
    date = time.strftime("%Y-%m-%d")
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='yingyong-compose' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    eid, err = _gen_yy_compose(db, date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()))


@bp.post("/api/write/yingyong/backfill")
def write_yy_backfill():
    """把最近 14 天里还没写的每日应用文补齐（后台慢慢跑）。"""
    db = get_db()
    today = datetime.now().date()
    done = {r[0] for r in db.execute("SELECT date FROM daily_essays WHERE mode='yingyong-daily'")}
    todo = [dt for dt in ((today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(14))
            if dt not in done]
    if not todo:
        return jsonify({"error": "最近 14 天都写好了"}), 400
    tid = bg_new(db, "yingyong-daily", "补齐每日应用文 %d 天" % len(todo), len(todo))
    flask_app = current_app._get_current_object()

    def run():
        con = sqlite3.connect(DB, timeout=60)
        con.row_factory = sqlite3.Row
        ok = 0
        try:
            for i, dt in enumerate(todo):
                bg_set(con, tid, status="running", progress=i,
                        message="正在写 %s（第 %d/%d 篇）" % (dt, i + 1, len(todo)))
                try:
                    with flask_app.app_context():
                        _, err = _gen_yingyong(con, _pick_daily_yy(con, dt), mode="yingyong-daily", date=dt)
                    if not err:
                        ok += 1
                except Exception:
                    log.warning("批量生成每日应用文：%s 这天失败", dt, exc_info=True)
            bad = len(todo) - ok
            bg_set(con, tid, status="done", progress=len(todo),
                    message="写好 %d 篇%s" % (ok, "（%d 天失败，可再点一次补）" % bad if bad else ""))
        except Exception as ex:
            bg_set(con, tid, status="error", message=str(ex)[:200])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid, "total": len(todo)}), 202


@bp.get("/api/write/days")
def write_days():
    """每日成文：列出有素材的日期 + 每天写了没有。"""
    db = get_db()
    _sucai_import(db)
    rows = db.execute(
        "SELECT s.date, COUNT(*) n, "
        "SUM(CASE WHEN s.kind='衔接表达' THEN 1 ELSE 0 END) nl, "
        "e.id eid, e.title, e.topic, e.words "
        "FROM sucai_items s LEFT JOIN daily_essays e ON e.mode='daily' AND e.date=s.date "
        "GROUP BY s.date ORDER BY s.date DESC").fetchall()
    return jsonify({"days": [dict(r) for r in rows]})


@bp.post("/api/write/daily")
def write_daily():
    d = request.get_json(silent=True) or {}
    date = (d.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify({"error": "日期不对"}), 400
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='daily' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    e, err = _write_gen(db, "daily", date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (e["id"],)).fetchone()))


@bp.post("/api/write/backfill")
def write_backfill():
    """把过去攒下的素材一天一篇全部补齐（22 天 × 一次 AI，得在后台慢慢跑）。"""
    db = get_db()
    _sucai_import(db)
    todo = [r[0] for r in db.execute(
        "SELECT DISTINCT s.date FROM sucai_items s "
        "WHERE NOT EXISTS(SELECT 1 FROM daily_essays e WHERE e.mode='daily' AND e.date=s.date) "
        "ORDER BY s.date")]
    if not todo:
        return jsonify({"error": "已经全部写完了"}), 400
    tid = bg_new(db, "write", "补齐每日成文 %d 天" % len(todo), len(todo))

    flask_app = current_app._get_current_object()   # 线程里没有请求上下文，先在这儿取住真 app

    def run():
        con = sqlite3.connect(DB, timeout=60)
        con.row_factory = sqlite3.Row
        ok = 0
        try:
            for i, dt in enumerate(todo):
                bg_set(con, tid, status="running", progress=i,
                        message="正在写 %s（第 %d/%d 篇）" % (dt, i + 1, len(todo)))
                try:
                    with flask_app.app_context():
                        e, err = _write_gen(con, "daily", dt)
                    if not err:
                        ok += 1
                except Exception:             # 单天失败不拖垮整批，下次再点一次补
                    log.warning("批量生成每日范文：%s 这天失败", dt, exc_info=True)
            bad = len(todo) - ok
            bg_set(con, tid, status="done", progress=len(todo),
                    message="写好 %d 篇%s" % (ok, "（%d 天失败，可再点一次补）" % bad if bad else ""))
        except Exception as ex:
            bg_set(con, tid, status="error", message=str(ex)[:200])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid, "total": len(todo)}), 202


@bp.get("/api/write/task/<int:tid>")
def write_task(tid):
    r = get_db().execute("SELECT * FROM bg_tasks WHERE id=? AND user_id=?", (tid, uid())).fetchone()
    if not r:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(dict(r))


@bp.post("/api/write/compose")
def write_compose():
    """综合应用：AI 自己选题，跨全部素材库挑最合适的，每天一篇。"""
    d = request.get_json(silent=True) or {}
    date = time.strftime("%Y-%m-%d")
    db = get_db()
    if not d.get("force"):
        r = db.execute("SELECT * FROM daily_essays WHERE mode='compose' AND date=?", (date,)).fetchone()
        if r:
            return jsonify(_e_row(r))
    e, err = _write_gen(db, "compose", date)
    if err:
        return err
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (e["id"],)).fetchone()))


@bp.get("/api/write/list")
def write_list():
    mode = (request.args.get("mode") or "compose").strip()
    rows = get_db().execute(
        "SELECT id,mode,date,topic,title,words,created_at FROM daily_essays "
        "WHERE mode=? ORDER BY date DESC LIMIT 200", (mode,)).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.get("/api/write/<int:eid>")
def write_get(eid):
    r = get_db().execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()
    if not r:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(_e_row(r))


@bp.delete("/api/write/<int:eid>")
def write_del(eid):
    db = get_db()
    db.execute("DELETE FROM daily_essays WHERE id=?", (eid,))
    db.commit()
    return jsonify({"ok": True})


def _recheck(r, content):
    """正文换了以后，那些**指向正文的东西**得跟着重新核一遍，不然就是过期的假信息：
       · used —— 「用到的素材」清单，被删掉的素材不能还挂在那儿；
       · segs —— 应用文的逐段批注，text 对不上正文就点不过去了（和生成时同一把尺子）。
       返回 (used_json, outline_json 或 None)。"""
    e = _e_row(r)
    used = [u for u in e["used"]
            if isinstance(u, dict) and _used_hit(u.get("text") or "", content)]
    segs = None
    if (r["mode"] or "").startswith("yingyong"):
        flat = re.sub(r"\s", "", content)
        segs = [s for s in e["outline"]
                if isinstance(s, dict) and re.sub(r"\s", "", s.get("text") or "") in flat]
    return (json.dumps(used, ensure_ascii=False),
            json.dumps(segs, ensure_ascii=False) if segs is not None else None)


@bp.put("/api/write/<int:eid>")
def write_edit(eid):
    """手改这篇。AI 写的东西总有改不到位的地方，自己动手比重生成一篇快得多。

    议论文能改标题 / 话题 / 正文 / 提纲 / 说明；应用文的 outline 是逐段批注（结构化的），
    不在这儿改，但正文一改就会重新核对批注，对不上的自动摘掉 —— 留着指不到正文的批注更糟。"""
    db = get_db()
    r = db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()
    if not r:
        return jsonify({"error": "文章不存在"}), 404
    d = request.get_json(silent=True) or {}
    gw = (r["mode"] or "").startswith("yingyong")
    content = (d.get("content") or "").strip()
    if not content:
        return jsonify({"error": "正文不能为空"}), 400

    # **只改传了的字段**：漏传和「显式改成空」得分开，否则一个只想改正文的调用
    # （PUT {"content": ...}）会把标题、话题、说明一起抹成空串 —— 应用文的 topic 存的
    # 是文种名，抹掉连文种大全的分组都会掉一档。
    sets = {"content": content, "words": len(re.sub(r"\s", "", content))}
    for k, cap in (("title", 80), ("topic", 40), ("note", 200)):
        if k in d:
            sets[k] = (d.get(k) or "").strip()[:cap]
    used_json, segs_json = _recheck(r, content)
    sets["used"] = used_json
    if gw:
        if segs_json is not None:
            sets["outline"] = segs_json
    else:
        # 议论文：提纲按行收（前端就是个 textarea），空行忽略
        ol = d.get("outline")
        if isinstance(ol, str):
            ol = [x.strip() for x in ol.split("\n") if x.strip()]
        if isinstance(ol, list):
            ol = [str(x).strip() for x in ol if str(x).strip()][:8]
            sets["outline"] = json.dumps(ol, ensure_ascii=False)
        else:
            ol = _e_row(r)["outline"]        # 没传提纲就沿用库里的
        # 对照里存的是**段号**，正文一改段号就可能挪位，所以不管提纲传没传都要重算，
        # 否则提纲页会指着「正文第 3 段」，而那句其实已经跑到第 4 段去了。
        # 只按字面算，不调 AI（改一次正文就调一次太贵）；判不准的标 unsure，要准的再点「对齐提纲」。
        sets["align"] = json.dumps(quick_report(content, ol), ensure_ascii=False)

    db.execute("UPDATE daily_essays SET %s WHERE id=?" % ",".join(k + "=?" for k in sets),
               list(sets.values()) + [eid])
    db.commit()
    return jsonify(_e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()))


def _align_one(db, eid):
    """对齐一篇议论文：提纲的每条论点，在正文段首落没落地。返回 (报告, 错误) 。"""
    r = db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone()
    if not r:
        return None, (jsonify({"error": "文章不存在"}), 404)
    if (r["mode"] or "").startswith("yingyong"):
        return None, (jsonify({"error": "应用文没有分论点，不用对齐"}), 400)
    e = _e_row(r)
    content, outline, rep = align(e["content"], e["outline"])
    db.execute("UPDATE daily_essays SET content=?,outline=?,words=?,used=?,align=? WHERE id=?",
               (content, json.dumps(outline, ensure_ascii=False),
                len(re.sub(r"\s", "", content)), _recheck(r, content)[0],
                json.dumps(rep.get("items") or [], ensure_ascii=False), eid))
    db.commit()
    return rep, None


@bp.post("/api/write/<int:eid>/align")
def write_align(eid):
    db = get_db()
    rep, err = _align_one(db, eid)
    if err:
        return err
    out = _e_row(db.execute("SELECT * FROM daily_essays WHERE id=?", (eid,)).fetchone())
    out["align_log"] = rep.get("log") or []
    return jsonify(out)


# 存量文章要整批对一遍时走命令行 `gen_write.py --align-all`：那是一次性的补齐，
# 生成时已经自带对齐、平时不会再攒出偏差，为它单挂一条后台任务链路不值当。


# ---- 应用文上位词 ----
@bp.get("/api/gongwen")
def gongwen_list():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    if q:
        like = "%" + q + "%"
        rows = db.execute("SELECT * FROM gongwen_items WHERE scene LIKE ? OR phrases LIKE ? OR doctype LIKE ? "
                          "ORDER BY id LIMIT 200", (like, like, like)).fetchall()
    else:
        rows = db.execute("SELECT * FROM gongwen_items ORDER BY id LIMIT 200").fetchall()
    return jsonify({"items": [dict(r) for r in rows],
                    "total": db.execute("SELECT COUNT(*) FROM gongwen_items").fetchone()[0]})


@bp.get("/api/gongwen/daily")
def gongwen_daily():
    """每日推荐 3 组：按日期确定性轮换，全站一致。"""
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM gongwen_items ORDER BY id")]
    if not ids:
        return jsonify({"items": []})
    start = (datetime.now().toordinal() * 3) % len(ids)
    pick = [ids[(start + i) % len(ids)] for i in range(min(3, len(ids)))]
    rows = db.execute("SELECT * FROM gongwen_items WHERE id IN (%s)" %
                      ",".join("?" * len(pick)), pick).fetchall()
    order = {v: i for i, v in enumerate(pick)}
    return jsonify({"items": sorted([dict(r) for r in rows], key=lambda x: order.get(x["id"], 0))})


@bp.post("/api/gongwen/ai")
def gongwen_ai():
    """输入口语句/场景 → AI 给出公文规范上位表述，并收录。"""
    text = ((request.get_json(silent=True) or {}).get("input") or "").strip()
    if not text:
        return jsonify({"error": "请输入一句口语表述，或一个应用文场景"}), 400
    db = get_db()
    prompt = ("公考申论应用文（公文）写作要求用词规范、书面化。考生给你一句口语化表述或一个写作场景，"
              "请把它归纳成公文里的「规范上位表述」，帮助考生答题时替换掉大白话。\n\n"
              "输入：%s\n\n请输出 JSON：\n"
              '{"scene":"这属于应用文的哪个场景（如「主体·工作举措」「结尾·号召」，10字内）",'
              '"phrases":"该场景常用的规范上位表述，用顿号分隔，6~10个，都要是书面公文用语",'
              '"doctype":"最常出现在哪些文种（如 通知/意见/倡议书，3个内）",'
              '"note":"一句话点明用法或易错点（40字内）",'
              '"example":"一个用上这些规范表述的完整示范句（30~60字）"}\n只输出 JSON。' % text[:200])
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论应用文（公文写作）阅卷老师，熟悉各文种的规范用语。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=500, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常"}), 502
    scene = (d.get("scene") or text[:10]).strip()
    # 场景重名就并入（避免 UNIQUE 冲突覆盖种子），改标一个带序号的场景名
    if db.execute("SELECT 1 FROM gongwen_items WHERE scene=?", (scene,)).fetchone():
        scene = scene + "·" + datetime.now().strftime("%m%d%H%M")
    db.execute("INSERT INTO gongwen_items(scene,phrases,doctype,note,example,source) VALUES(?,?,?,?,?,'ai')",
               (scene, (d.get("phrases") or "").strip(), (d.get("doctype") or "").strip(),
                (d.get("note") or "").strip(), (d.get("example") or "").strip()))
    db.commit()
    r = db.execute("SELECT * FROM gongwen_items WHERE scene=?", (scene,)).fetchone()
    return jsonify(dict(r))


@bp.delete("/api/gongwen/<int:gid>")
def gongwen_del(gid):
    db = get_db()
    db.execute("DELETE FROM gongwen_items WHERE id=? AND source='ai'", (gid,))  # 种子词库不许删
    db.commit()
    return jsonify({"ok": True})

