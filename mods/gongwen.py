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
from mods.write import WRITE_MAX, _e_row, _used_hit, _write_gen

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

# ---- 结构部件：两级 ----
# 这套词表**不是拍脑袋列的**，是把 63 篇自产应用文的逐段批注全聚合出来定的
# （docs/data/yy_parts_agg.py，可重跑）。实测数据推翻了原先"一张扁平清单"的想法：
# 408 条批注里出现了 **119 种**部件名，其中 79 种只出现 1 次。稳定核心只有 8 个
# （落款45 称谓44 主体·举措39 标题37 开头·缘由34 结尾·号召15 结尾·收束14 主体·成效13），
# 剩下全是同一块的不同叫法。所以拆成两级：一级槽位是闭集，二级角色是受控词表。
GW_SLOTS = ["标题", "主送机关", "称谓", "开头", "主体", "结尾", "落款"]
GW_ROLES = {
    "开头": ["缘由", "目的", "点题", "概述", "导语"],
    "主体": ["举措", "成效", "问题", "建议", "背景", "启示", "目标", "保障",
             "内容介绍", "析原因", "提办法", "评价意义",
             # 这两个是回测 63 篇时补的，各有 2 条实据：
             # 「引出事项」是公文标准件（gongwen_items 种子里就有「过渡·引出事项」），
             # 「下一步」是汇报的标准收尾块（"下一步打算"）
             "引出事项", "下一步"],
    "结尾": ["号召", "要求", "收束", "引导阅读", "展望"],
}
# 两张别名表，分工不同——混成一张会写出一堆判不准的分支（第一版就是那么写的）：
#   · GW_PART_ALIAS：**整个名字**的别名，右边是规范名（有测试盯着必须已规范）
#   · _ROLE_ALIAS：**二级角色词**的别名，只在「槽位·角色」的角色位上替换
# 「导语」挂在开头下是因为新闻稿 3/3 篇都标了它——它是文种专属部件，不是通用槽位。
GW_PART_ALIAS = {
    "正文": "主体", "正文开头": "开头", "正文主体": "主体", "正文结尾": "结尾",
    "正文结语": "结尾·收束", "结语": "结尾·收束", "结束语": "结尾·收束",
    "开场": "开头", "开场白": "开头", "导语": "开头·导语", "过渡": "主体",
    "落款与日期": "落款", "落款单位": "落款", "落款日期": "落款",
    "做法": "主体·举措", "成效": "主体·成效", "概述": "开头·概述",
    "背景": "主体·背景", "启示": "主体·启示", "建议": "主体·建议",
    "指导思想": "主体·目标", "工作目标": "主体·目标", "主要措施": "主体·举措",
    "组织保障": "主体·保障", "倡议内容": "主体·举措", "具体倡议": "主体·举措",
    "意义阐述": "主体·评价意义", "问题剖析": "主体·问题", "改进举措": "主体·举措",
    "成效介绍": "主体·成效",
}
_ROLE_ALIAS = {
    "做法": "举措", "做法分条": "举措", "主要措施": "举措", "工作举措": "举措",
    "具体举措": "举措", "改进举措": "举措", "倡议内容": "举措", "对策": "举措",
    "对策建议": "建议", "具体建议": "建议", "存在问题": "问题", "问题剖析": "问题",
    "工作目标": "目标", "指导思想": "目标", "组织保障": "保障", "工作要求": "要求",
    "报道内容": "内容介绍", "内容": "内容介绍", "意义": "评价意义",
    "意义阐述": "评价意义", "评价": "评价意义",
    "敬语": "收束", "敬礼": "收束", "结语": "收束", "总结": "收束",
    "号召阅读": "引导阅读", "引导": "引导阅读", "缘由与目的": "缘由", "点明主题": "点题",
    "现状": "成效", "现状与成效": "成效",
    "亮观点": "点题", "原因": "析原因",     # 回测 63 篇时补的
}
# 合成名的连接词：「主体·举措及成效」是两块糊在一起，要拆开
_COMPOSITE = re.compile(r"(?:与|及|\+|和)")
# 尾部序号：「主体·举措一」「主体·举措2」「建议三」都是同一块加了个号
_TAIL_NUM = re.compile(r"[一二三四五六七八九十1-9]$")
# 「主体段落二」这种裸写法，直接落到槽位
_BARE = {"主体段落": "主体", "开头段落": "开头", "结尾段落": "结尾", "主体部分": "主体"}


def _clean(p):
    p = re.sub(r"\s+", "", p or "")
    p = re.sub(r"[（(].*?[)）]", "", p)               # 「落款（署名+日期）」→「落款」
    return p.replace("・", "·").replace("/", "·").replace("-", "·").strip("·")


def _norm_one(p, _depth=0):
    """把一个部件名收成规范形式。认不出的角色**退到槽位级**，不丢——
    丢了等于这条批注白标（实测 119 种名字里 79 种是一次性的，全丢就没数据了）。"""
    p = _clean(p)
    if not p or _depth > 2:
        return p if _depth else ""
    if p in GW_PART_ALIAS:                            # 整名别名优先
        return GW_PART_ALIAS[p]
    if p.startswith("正文·"):                         # 另一套命名法：剥掉前缀让里面自己定槽位
        got = _norm_one(p[3:], _depth + 1)
        return got if got else "主体"
    for bare, slot in _BARE.items():
        if p.startswith(bare):
            return slot
    if "·" not in p:
        base = _TAIL_NUM.sub("", p) or p
        if base in GW_PART_ALIAS:
            return GW_PART_ALIAS[base]
        if base in GW_SLOTS:
            return base
        # 「结尾号召」：分隔符丢了，但前缀是个槽位名——补上「·」再走两级那条路
        for slot in GW_SLOTS:
            if base.startswith(slot) and len(base) > len(slot):
                return _norm_one(slot + "·" + base[len(slot):], _depth + 1)
        role = _ROLE_ALIAS.get(base, base)            # 裸角色：挂到它所属的槽位上
        for slot, roles in GW_ROLES.items():
            if role in roles:
                return slot + "·" + role
        return base
    slot, role = p.split("·", 1)
    slot = GW_PART_ALIAS.get(slot, slot)
    if "·" in slot:                                   # 别名指到了两级名（如「导语」→「开头·导语」）
        return slot
    if slot not in GW_SLOTS:
        return _norm_one(slot, _depth + 1)
    role = _ROLE_ALIAS.get(role, _TAIL_NUM.sub("", role) or role)
    role = _ROLE_ALIAS.get(role, role)                # 砍完序号可能才认出别名
    if role in GW_ROLES.get(slot, []):
        return slot + "·" + role
    return slot                                       # 认不出的角色退到槽位级


def norm_part(p, split=False):
    """部件名归一化。split=True 时把合成名拆成多条（返回 list），否则返回第一条。

    三条规则都是 63 篇实测出来的：尾部序号 13 种/22 条、`正文·` 前缀 23 种/26 条、
    合成名 18 种/23 条，加起来 54 种名字 71 条能机械收掉。
    """
    raw = re.sub(r"\s+", "", p or "")
    raw = re.sub(r"[（(].*?[)）]", "", raw)
    if not raw:
        return [] if split else ""
    parts, seen = [], set()
    head = ""
    for i, piece in enumerate(_COMPOSITE.split(raw)):
        if not piece:
            continue
        # 「主体·举措及成效」拆开后第二段是裸的「成效」，要继承前一段的槽位
        if i and "·" not in piece and head:
            piece = head + "·" + piece
        got = _norm_one(piece)
        if not got:
            continue
        if "·" in got:
            head = got.split("·")[0]
        elif got in GW_SLOTS:
            head = got
        if got not in seen:
            seen.add(got)
            parts.append(got)
    if split:
        return parts
    return parts[0] if parts else ""


def parts_of(doctype):
    """取某文种的部件清单 [(部件, 是否必需)]。文种不认识就给一份通用骨架。"""
    g = GW_MAP.get(doctype)
    if g and g.get("parts"):
        return g["parts"]
    return [("标题", 1), ("开头·缘由", 1), ("主体·举措", 1), ("结尾·收束", 1)]


GW_DOCTYPES = [
    # ---- 宣传演讲类：面向人，讲究感染力和现场感 ----
    dict(k="讲话稿", parts_src="real", parts_n=9, fam="交流材料", freq=1, freq_all=7, cat="宣传演讲类", d="领导在某场合讲，有听众、有现场感",
         fmt="标题 / 称谓（同志们）/ 开头（开场点题）→ 主体（分条讲）→ 结尾（鼓劲号召）/ 无落款",
         parts=[("标题", 1), ("称谓", 1), ("开头·点题", 1), ("主体·举措", 1),
                ("结尾·号召", 1)],
         min=500, max=800,
         demo=dict(scene="全区基层治理推进会", role="区政府分管副区长", audience="各街道、各部门负责同志")),
    dict(k="宣传稿", parts_src="real", parts_n=4, fam="宣传", freq=4, freq_all=5, cat="宣传演讲类", d="贴在社区、发在公众号，给群众看的",
         fmt="标题 / 开头（引出）→ 主体（讲清楚）→ 结尾（号召）/ 落款", min=400, max=600,
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·举措", 1), ("主体·成效", 0),
                ("结尾·号召", 1), ("落款", 1)],
         demo=dict(scene="垃圾分类进社区", role="社区居委会工作人员", audience="全体社区居民")),
    dict(k="公开信", fam="公开信", freq=2, freq_all=3, cat="宣传演讲类", d="以组织名义写给公众，语气恳切、有来有往",
         fmt="标题 / 称谓 / 开头（缘由）→ 主体（说明）→ 结尾（呼吁号召）/ 落款（署名+日期）",
         parts=[("标题", 1), ("称谓", 1), ("开头·缘由", 1), ("主体·成效", 0),
                ("主体·问题", 0), ("主体·举措", 1), ("结尾·号召", 1), ("落款", 1)],
         min=400, max=600,
         demo=dict(scene="致全市市民的文明养犬公开信", role="市城市管理局", audience="全体市民")),
    dict(k="新闻稿", fam="", freq=0, freq_all=0, cat="宣传演讲类", d="报道一件事，客观、有导语、有数据和引语",
         fmt="标题（实题）/ 开头·导语（何时·何地·何事·何果）/ 主体（展开+数据+引语）/ 结尾（结语）",
         parts=[("标题", 1), ("开头·导语", 1), ("主体·内容介绍", 1), ("主体·成效", 0),
                ("结尾·展望", 0)],
         min=400, max=600,
         demo=dict(scene="我区数字政务服务大厅正式启用", role="区融媒体中心记者", audience="社会公众")),
    dict(k="倡议书", fam="倡议", freq=0, freq_all=2, cat="宣传演讲类", d="面向公众发出号召，靠感染力不靠命令",
         fmt="标题 / 称谓 / 开头（缘由）→ 主体（倡议内容分条）→ 结尾（号召）/ 落款",
         parts=[("标题", 1), ("称谓", 1), ("开头·缘由", 1), ("主体·举措", 1),
                ("结尾·号召", 1), ("落款", 0)],
         min=400, max=600,
         demo=dict(scene="节约用水", role="市水务局", audience="全体市民")),
    # ---- 总结说明类：面向上级/同行，讲究条理和成效 ----
    # ---- P1b：「落款」按真题参考答案从必需降为可选 ----
    # ⚠️ 只在**极值**上改判（0% 或 100%），卡在 80% 阈值附近的一律等样本够了再说。
    # 这条纪律是被自己打脸打出来的：先按 汇报 标题 67%(2/3) 降成可选，
    # 补完 OCR 数据后样本变 5，标题变 **80%(4/5)** —— 判定直接翻转。
    # 3 个样本里多一条就是 ±33 个百分点，够不着 80% 这种边界判定。
    # 所以「标题」那几处降级全部撤回了；下面的「落款」保留，因为它是 0%（0/9、0/5、0/3）
    # 且有全样本 17% 兜底，极值判定不受一两条样本影响。
    # 36 份真题参考答案实测：落款·署名整体只占 **17%**，只看成篇（full）也只 26%（6/23）。
    # 而 P0b 里我是照 63 篇**自产**范文标的必需——自产范文 92% 都写落款，
    # 那是模型在过度套用公文习惯，不是考试要求。
    # 按文种族看（**只动 n≥3 的**，样本不足的一律不碰）：
    #     交流材料 0/9 · 推荐/参评 0/4 · 简报 0/3 · 汇报 0/3   ← 都没写
    #     公开信 2/2 · 宣传 2/4 · 介绍 1/3                     ← 写了
    # 这不是噪声，是一条讲得通的规律：**面向内部/上级的文种不写落款，面向公众的才写**。
    # 所以只降 汇报 / 简报；公开信保持必需；
    # 调研报告 / 方案 / 建议书 / 通知 的样本 ≤1，**不动**（见设计文档 3.8）。
    # 汇报的「称谓」同理：3/3 份都没写，一并降为可选。
    dict(k="汇报", parts_src="real", parts_n=3, fam="汇报", freq=5, freq_all=5, cat="总结说明类", d="把一段工作向上级说清楚：做了什么、效果如何、下一步",
         fmt="标题 / 称谓 / 开头（概述）→ 主体（做法分条→成效）→ 结尾（下一步收束）/ 落款",
         parts=[("标题", 1), ("称谓", 0), ("开头·概述", 1), ("主体·举措", 1),
                ("主体·成效", 1), ("主体·问题", 0), ("结尾·收束", 1), ("落款", 0)],
         min=500, max=800,
         demo=dict(scene="老旧小区改造工作", role="区住建局", audience="市住建局")),
    dict(k="调研报告", fam="调研报告", freq=4, freq_all=4, cat="总结说明类", d="调查了什么、发现什么问题、建议怎么办",
         fmt="标题 / 开头（背景缘由）→ 主体（现状成效→问题→建议）→ 结尾（收束）/ 落款",
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·背景", 0), ("主体·成效", 1),
                ("主体·问题", 1), ("主体·建议", 1), ("结尾·收束", 1), ("落款", 1)],
         min=500, max=800,
         demo=dict(scene="农村电商发展现状调研", role="县商务局调研组", audience="县政府")),
    dict(k="简报", parts_src="real", parts_n=3, fam="简报", freq=4, freq_all=4, cat="总结说明类", d="短平快，一件事一页纸，给上级看",
         fmt="标题 / 开头（概述）→ 主体（做法分条→成效）→ 结尾（收束）/ 落款", min=400, max=600,
         parts=[("标题", 1), ("开头·概述", 1), ("主体·举措", 1), ("主体·成效", 1),
                ("结尾·收束", 0), ("落款", 0)],
         demo=dict(scene="防汛应急演练", role="县应急管理局", audience="县委县政府")),
    dict(k="案例介绍", parts_src="real", parts_n=4, fam="推荐/参评", freq=5, freq_all=4, cat="总结说明类", d="讲一个能被别人学走的做法：背景→做法→成效→启示",
         fmt="标题 / 开头（背景）→ 主体（做法→成效→启示）", min=400, max=600,
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·背景", 0), ("主体·举措", 1),
                ("主体·成效", 1), ("主体·启示", 1)],
         demo=dict(scene="某镇「一网通办」便民服务经验", role="镇政府办公室", audience="全县各乡镇")),
    dict(k="编者按", fam="编者按", freq=2, freq_all=2, cat="总结说明类", d="放在文章前面的一小段，点题+评价+引导读下去",
         fmt="短标题或无标题 / 开头（点明主题）→ 主体（评价意义）→ 结尾（引导阅读）",
         parts=[("标题", 0), ("开头·点题", 1), ("主体·评价意义", 1),
                ("结尾·引导阅读", 1)],
         min=200, max=400,
         demo=dict(scene="为一组基层减负报道写编者按", role="报社编辑", audience="读者")),
    # ---- 方案建议类：面向执行，讲究可落地 ----
    dict(k="方案", fam="方案", freq=2, freq_all=2, cat="方案建议类", d="怎么干的通盘安排：目标、措施、分工、保障",
         fmt="标题 / 开头（指导思想·缘由）→ 主体（工作目标→主要措施→组织保障）→ 结尾（工作要求）/ 落款",
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·目标", 1), ("主体·举措", 1),
                ("主体·保障", 1), ("结尾·要求", 1), ("落款", 1)],
         min=500, max=800,
         demo=dict(scene="社区养老服务提升行动", role="街道办事处", audience="辖区各社区")),
    dict(k="建议书", fam="建议", freq=2, freq_all=2, cat="方案建议类", d="向某单位提意见，要有理有据、可执行",
         fmt="标题 / 称谓 / 开头（缘由问题）→ 主体（建议分条）→ 结尾（收束）/ 落款（署名+日期）",
         parts=[("标题", 1), ("称谓", 1), ("开头·缘由", 1), ("主体·问题", 0),
                ("主体·建议", 1), ("结尾·收束", 1), ("落款", 1)],
         min=400, max=600,
         demo=dict(scene="改善校园周边交通秩序", role="学校家长委员会", audience="区交警大队")),
    dict(k="通知", fam="通知", freq=0, freq_all=1, cat="方案建议类", d="上级发给下级，告知事项并要求落实",
         fmt="标题（发文机关+事由+文种）/ 主送机关 / 开头（缘由依据）→ 主体（事项分条）→ 结尾（要求）/ 落款",
         parts=[("标题", 1), ("主送机关", 1), ("开头·缘由", 1), ("主体·举措", 1),
                ("结尾·要求", 1), ("落款", 1)],
         min=400, max=600,
         demo=dict(scene="开展安全生产大检查", role="市安全生产委员会办公室", audience="各县区、各成员单位")),
    # ---- P1 新增：真题考过、但原清单里没有的文种 ----
    # 加不删是刻意的：删掉会让已经写好的 63 篇范文在「文种大全」里变成孤儿。
    # 零频的老文种（通知/倡议书/新闻稿）留着但 freq=0，界面按 freq 排序自然靠后。
    dict(k="经验交流材料", parts_src="real", parts_n=9, fam="交流材料", freq=8, freq_all=13, cat="总结说明类",
         d="把本单位的做法写成能被别人学走的材料，在会上交流——**真题最高频的文种**",
         fmt="标题 / 开头（缘由概述）→ 主体（做法分条+成效）→ 结尾（收束）",
         parts=[("标题", 1), ("开头·概述", 1), ("主体·举措", 1), ("主体·成效", 1),
                ("结尾·收束", 0)],
         min=400, max=800,
         demo=dict(scene="打通基层法律服务「最后一公里」座谈会", role="花湖区政府办工作人员",
                   audience="参会各单位")),
    dict(k="推荐材料", parts_src="real", parts_n=4, fam="推荐/参评", freq=5, freq_all=4, cat="总结说明类",
         d="为评选推荐一个集体/做法：亮成绩、给依据，比案例介绍更紧",
         fmt="标题 / 开头（推荐缘由）→ 主体（做法+成效+亮点）→ 结尾（收束）",
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·举措", 1), ("主体·成效", 1),
                ("主体·启示", 0)],
         min=300, max=500,
         demo=dict(scene="全省政务服务先进集体评选", role="B市政务服务局",
                   audience="A省评选办")),
    dict(k="情况介绍", parts_src="real", parts_n=3, fam="介绍", freq=2, freq_all=6, cat="总结说明类",
         d="把一件事/一个模式说清楚给外人听：是什么、怎么运行、效果如何",
         fmt="标题 / 开头（点题）→ 主体（内容介绍+成效）→ 结尾（收束）",
         parts=[("标题", 1), ("开头·点题", 1), ("主体·内容介绍", 1), ("主体·成效", 0),
                ("结尾·收束", 0)],
         min=400, max=500,
         demo=dict(scene="「工业上楼」模式", role="B省工信厅工作人员", audience="来访考察团")),
    dict(k="提案", fam="提案", freq=1, freq_all=1, cat="方案建议类",
         d="政协委员提交的提案：案由 + 具体建议，两块分明",
         fmt="标题 / 开头（案由：问题与依据）→ 主体（建议分条）/ 落款",
         parts=[("标题", 1), ("开头·缘由", 1), ("主体·问题", 1), ("主体·建议", 1),
                ("落款", 0)],
         min=400, max=500,
         demo=dict(scene="助推「元科普」，促进科普与科研共发展", role="S市政协委员",
                   audience="市政协")),
    dict(k="工作指南", fam="指南", freq=1, freq_all=1, cat="方案建议类",
         d="给一线用的操作手册：分工作事项，每项写清具体做什么",
         fmt="标题 / 主体（工作事项分条，每项含具体工作内容）",
         parts=[("标题", 1), ("主体·举措", 1)],
         min=400, max=500,
         demo=dict(scene="平安夜市安全巡查工作指南", role="B市大帆夜市综合服务办公室",
                   audience="夜市巡查工作人员")),
    dict(k="谈话提纲", fam="谈话", freq=1, freq_all=1, cat="方案建议类",
         d="当面反馈用的提纲：成效、问题、改进建议，说给对方听",
         fmt="标题 / 主体（成效→问题→改进建议）",
         parts=[("标题", 0), ("主体·成效", 1), ("主体·问题", 1), ("主体·建议", 1)],
         min=400, max=450,
         demo=dict(scene="现场指导后向企业负责人反馈", role="指导组", audience="西瑞药业负责人")),
    # ---- 观点主张类：面向读者，讲究观点鲜明 ----
    dict(k="短评", fam="短评", freq=3, freq_all=3, cat="观点主张类", d="就一件事表态：观点鲜明、篇幅短、有回味",
         fmt="标题 / 开头（亮观点点题）→ 主体（析原因→提办法）→ 结尾（收束号召）", min=300, max=500,
         parts=[("标题", 1), ("开头·点题", 1), ("主体·析原因", 1), ("主体·提办法", 1),
                ("结尾·号召", 1)],
         demo=dict(scene="如何看待「指尖上的形式主义」", role="评论员", audience="读者")),
]
GW_CATS = ["宣传演讲类", "总结说明类", "方案建议类", "观点主张类"]
GW_MAP = {d["k"]: d for d in GW_DOCTYPES}

# ---- 应用文成文的字数：上限统一 ≤500 字，下限按「文种 + 题位」灵活定 ----
# 真题里同一题材，放在第二题和第四题，要求字数差很多——用「题位档」建模这件事：
#   越靠后的题（分值越大）字数要求越大。三档对应小题位/中题位/大题位。
MAX_YY_WORDS = 500          # 保留给老调用点；新逻辑用 YY_HARD_CAP，见下
# ---- P1：字数模型换成真题实测 ----
# 原来的 MAX_YY_WORDS=500 是**错的硬顶**：30 套近五年真题里，应用文字数最小 250、
# 中位 450、**最大 1000**（2022 国考行执第 5 题公开信，要求 800-1000 字），
# 600 字以上占 11%。硬顶 500 会把这类题在训练中彻底屏蔽掉。
YY_HARD_CAP = 1000
# 按**分值**建档，不按"题位"——题位是猜的，分值是题面上写着的。
# 数字来自 docs/data/yy-真题标注.tsv 和 slreal_questions 的实测中位数（n=28~38）。
# 沿用 P2 那条经验：**给模型区间没用、要给具体数字**，所以每档除了区间还带一个 target。
SCORE_BANDS = {
    15: (250, 350, 300),
    20: (400, 500, 450),
    25: (400, 550, 500),
    30: (450, 1000, 600),
}
# 参考答案实际写到字数上限的多少：30 份实测比例中位 **0.94**，最小 0.78 最大 1.58。
# 也就是说标准答案**不顶着上限写**，而是写到 90~95%。提示词里给这个目标比给上限有用。
ANS_FILL = 0.94
POS_BANDS = {
    "small": (200, 320),    # 靠前的小题位（如第一、二题）
    "medium": (280, 420),   # 中间题位（如第三题）
    "large": (360, 500),    # 靠后的大题位（如第四题·贯彻执行主力题）
}
POS_LABEL = {"small": "小题位（如第一二题）", "medium": "中题位（如第三题）", "large": "大题位（如第四题）"}
# 文种各自的自然上限。**P1 按真题实测重标过**——原来这几个数是估的，而且估低了：
# 短评估 380，真题实考 400/450/500；公开信估 470，真题实考 500~1000。
# 现在的数字取「该文种族真题字数最大值」，样本不足的（n<2）留空走通用上限。
# 实测（去重后 n=同族题数）：交流材料 250~800、公开信 500~1000、方案 600、
# 编者按 300~400、推荐参评 300~500、其余多在 400~500。
GW_CAP = {"编者按": 400, "短评": 500, "简报": 500, "案例介绍": 500, "推荐材料": 500,
          "宣传稿": 500, "倡议书": 500, "建议书": 500, "调研报告": 500, "汇报": 500,
          "情况介绍": 500, "谈话提纲": 450, "提案": 500, "工作指南": 500,
          "通知": 500, "方案": 600, "经验交流材料": 800, "讲话稿": 800,
          "公开信": 1000, "新闻稿": 500}


# 「一是…二是…」是口头汇报的分条法，写进应用文正文就是扣分项——公文分条要用「一、二、」。
# 提示词说了不算数：这套说法在模型的公文语料里太根深蒂固，实测还是会往外冒。所以出稿之后
# 再过一道硬替换，让规则**落到字面上**而不是停在提示词里。
#
# **但口语文种要豁免。** P1 拿 30 份真题参考答案回测：用「一是…二是…」的只有 1 场考试，
# 而它正好是**讲话稿**（2015 国考，「各位领导、同志们：大家好！」）。这印证了上面那句
# 「一是是口头汇报的说法」——反过来说，真的是"口头讲"的文种，这么写就是对的，
# 不该被改掉。改了反而把现场感抹平。
GW_SPOKEN = {"讲话稿"}
_XSHI = re.compile(r"(^|[\n。；;：:，,、])([一二三四五六七八九十])是(?=[^，。；\s])")
# 「，一、加强领导」这种标点在公文里不存在：分条项之间是断句的，前面的逗号/顿号/分号
# 一并升成句号。冒号和换行保留（「现提出如下意见：一、…」本来就对）。
_SEP_UP = "，,、；;"


def fix_fentiao(s, doctype=None):
    """把成串的「一是…二是…」改写成「一、…二、…」。

    只在**确实成串**时才动手，判据是「一是」和「二是」都真的落在分条位置上（句首或标点后）。
    单看字面含不含「二是」不够——「任务一是重点、二是难点」里的「一是」是正常汉语的
    「一 + 是」，只改后半句会得到一个不伦不类的「任务一是重点。二、难点」。

    doctype 属于 GW_SPOKEN（口语文种）时原样返回——真题参考答案里讲话稿就是这么写的。
    不传 doctype 时照旧全改，老调用点行为不变。
    """
    if not s or "一是" not in s or "二是" not in s:
        return s
    if doctype in GW_SPOKEN:
        return s
    hits = list(_XSHI.finditer(s))
    if not {"一", "二"} <= {m.group(2) for m in hits}:
        return s

    out, last = [], 0
    for m in hits:
        sep = m.group(1)
        out.append(s[last:m.start()])
        # sep 为空是「串就从头开始」，前面没东西可升级 —— 别写成 `sep in _SEP_UP`，
        # 空串是任何字符串的子串，那样会在正文最前面凭空多一个句号。
        out.append(("。" if sep and sep in _SEP_UP else sep) + m.group(2) + "、")
        last = m.end()
    out.append(s[last:])
    return "".join(out)


def _word_band(doctype, pos, score=None):
    """字数区间。给了 score 就按**分值档**（真题实测），否则按老的题位档。
    返回 (下限, 上限)。硬顶从 500 抬到 YY_HARD_CAP=1000（真题最大值）。"""
    if score and score in SCORE_BANDS:
        lo, hi, _t = SCORE_BANDS[score]
    elif score:                          # 分值不在档上，取最近的一档
        near = min(SCORE_BANDS, key=lambda k: abs(k - score))
        lo, hi, _t = SCORE_BANDS[near]
    else:
        lo, hi = POS_BANDS.get(pos, POS_BANDS["medium"])
    hi = min(hi, GW_CAP.get(doctype, YY_HARD_CAP), YY_HARD_CAP)
    lo = max(150, min(lo, hi - 60))     # 保证下限 < 上限、且留出至少 60 字区间
    return lo, hi


def _phrase_pool(db, doctype, limit=40):
    """按 (文种, 部件) 取规范表述，取不到退回全表。

    两个来源都查：新库 `yy_items`（kind='表述'，按 part 挂）和老表 `gongwen_items`
    （scene 字段本身就是部件名，如「开头·缘由（依据）」）。老表保持原样不动——
    它被成文链路、/api/gongwen、search.py、agent_tools 四处消费，改结构风险大。
    """
    want = {p for p, _req in parts_of(doctype)}
    want |= {p.split("·")[0] for p in want}          # 槽位级也算命中（「落款」对「落款·日期」）
    out, seen = [], set()
    try:
        # freq 是**真题实证强度**（这条提法在多少份真题参考答案里出现过），
        # 降序取 = 优先喂有实证的。实测 89 条种子提法里只有 30 条在真题里出现过，
        # 剩下 59 条是公文教材式套话（「为深入贯彻…」「压实…责任」），真题答案不这么写。
        # 同一个部件下按 freq 排、每个部件只取最强的一条，别把套话喂进去。
        for r in db.execute(
                "SELECT part scene, text phrases, freq FROM yy_items "
                "WHERE kind='表述' AND (doctype=? OR doctype='') "
                "ORDER BY freq DESC, id", (doctype,)):
            if r["scene"] in want and r["scene"] not in seen:
                seen.add(r["scene"])
                out.append(dict(r))
    except Exception:
        log.debug("yy_items 还没数据或列不齐，跳过", exc_info=True)
    for r in db.execute("SELECT scene, phrases, doctype FROM gongwen_items ORDER BY id"):
        p = norm_part(r["scene"])
        if p in want or (r["doctype"] and doctype in r["doctype"]):
            key = r["scene"]
            if key not in seen:
                seen.add(key)
                out.append(dict(r))
    if len(out) >= 4:
        return out[:limit]
    # 命中太少就退回全表：库里只有 16 条种子，宁可多喂也别让提示词里没零件可用
    return [dict(r) for r in db.execute(
        "SELECT scene, phrases, doctype FROM gongwen_items ORDER BY id LIMIT ?", (limit,))]


# 真题里 part 形态最常被单独考的几块，按文种给个默认。
# 没预设的文种就取它 parts 里的主体部分——真题考的都是"肉"，不会单独考标题落款。
PART_PRESETS = {
    "调研报告": ["主体·问题", "主体·建议"],          # 2022 川县乡 Q2 原题
    "提案": ["开头·缘由", "主体·建议"],              # 2025 国考地市 Q4（案由 + 具体建议）
    "工作指南": ["主体·举措"],                       # 2025 国考行执 Q3（工作事项及内容）
    "谈话提纲": ["主体·成效", "主体·问题", "主体·建议"],
    "汇报": ["主体·举措", "主体·成效"],
}


def _only_parts(doctype, want=None):
    """part 形态要写哪几块。传了就按传的（过滤掉这个文种没有的），否则用预设。"""
    have = {p for p, _r in parts_of(doctype)}
    if want:
        got = [norm_part(x) for x in want if x]
        return [p for p in got if p in have]
    preset = [p for p in PART_PRESETS.get(doctype, []) if p in have]
    if preset:
        return preset
    # 没预设：取主体那几块（真题的 part 题考的都是正文的"肉"，不考标题落款）
    return [p for p, _r in parts_of(doctype) if p.startswith("主体")] or \
           [p for p, r in parts_of(doctype) if r]


def _harvest_errors(db, content, doctype):
    """出稿后跑格式检查器，命中的存成错例（成对：错句 + 改正 + 扣分理由）。

    去重靠 yy_items 的 UNIQUE(kind,doctype,part,title)：同一条错句反复出现只留一条，
    但 freq 累加 —— 「这个错犯了多少次」本身就是有用的信息，复习时该优先出高频错。
    检查器**只报有真题实证的东西**（见 mods/yycheck 里的两道前置闸），
    否则等于把猜测当标准答案教给用户。
    """
    import hashlib

    from mods.yycheck import check_all
    pairs = check_all(content, doctype)
    if not pairs:
        return 0
    n = 0
    for p in pairs:
        brief = re.sub(r"\s", "", p["bad"])[:14]
        h = hashlib.sha1(((doctype or "") + p["bad"]).encode("utf-8")).hexdigest()[:6]
        title = "%s·%s·%s" % (p["check"], brief, h)
        cur = db.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src) "
            "VALUES('错例',?,?,?,?,?,'ai')",
            (doctype or "", p["part"], title,
             json.dumps({"bad": p["bad"], "good": p["good"]}, ensure_ascii=False),
             p["why"]))
        if cur.rowcount:
            n += 1
        else:
            db.execute("UPDATE yy_items SET freq=freq+1 WHERE kind='错例' AND "
                       "doctype=? AND part=? AND title=?", (doctype or "", p["part"], title))
    if pairs:
        log.info("应用文 %s 格式检查命中 %d 条（新入库 %d）", doctype, len(pairs), n)
    return n


def _word_target(lo, hi):
    """给模型的**具体目标字数**。真题参考答案写到上限的 94%，不顶着上限写。
    P2 的经验：给区间模型会往下限以下写，给具体数字才落在区间里。"""
    return max(lo + 20, int(hi * ANS_FILL))


def real_scenes(db, doctype="", limit=8):
    """真题原题的发文情景（身份 + 事由 + 对象），从 yy_items 的「情景」类取。

    原来这里是从新闻标题截 22 个字当发文场景、身份和对象直接退回 demo 默认值——
    那是**编的题面**。真题题干里这三样是现成的：
    「假如你是花湖区政府办工作人员，A 市要召开打通基层法律服务『最后一公里』座谈会」。

    受文对象大多抽不到（真题题干本来就不写，由文种隐含：简报→领导、倡议书→公众），
    所以缺的那一项**退回该文种 demo 里的 audience**，不硬编。
    """
    out = []
    try:
        rows = db.execute(
            "SELECT doctype, text, src_ref FROM yy_items WHERE kind='情景' "
            + ("AND doctype=? " if doctype else "")
            + "ORDER BY freq DESC, id DESC LIMIT ?",
            ([doctype, limit] if doctype else [limit])).fetchall()
    except sqlite3.Error:
        return []
    for r in rows:
        try:
            d = json.loads(r["text"] or "{}")
        except Exception:
            continue
        dt = r["doctype"] or doctype
        if not d.get("audience"):
            d["audience"] = (GW_MAP.get(dt, {}).get("demo") or {}).get("audience", "")
        d["src"] = r["src_ref"]
        d["doctype"] = dt
        if d.get("scene") or d.get("role"):
            out.append(d)
    return out


@bp.get("/api/write/realscene")
def write_realscene():
    """某个文种的真题情景，供「自选成文」一键套用。"""
    dt = (request.args.get("doctype") or "").strip()
    return jsonify({"items": real_scenes(get_db(), dt, 12)})


@bp.get("/api/write/gwspec")
def write_gwspec():
    """文种清单 + 推荐的发文场景。

    场景**先给真题原题的**（身份/事由都是真的），不够再用时政标题补——
    后者只是个话题词，配不出完整题面。
    """
    db = get_db()
    real = real_scenes(db, "", 8)
    scenes = [x["scene"] for x in real if x.get("scene")]
    for r in db.execute(
            "SELECT DISTINCT topic FROM gaikuo_items WHERE topic!='' ORDER BY date DESC LIMIT 10"):
        if r[0] and r[0] not in scenes:
            scenes.append(r[0])
    for r in db.execute("SELECT title FROM news_items ORDER BY id DESC LIMIT 6"):
        t = (r[0] or "").split("｜")[-1].strip()
        if t and len(t) <= 22 and t not in scenes:
            scenes.append(t)
    return jsonify({"doctypes": GW_DOCTYPES, "cats": GW_CATS,
                    "scenes": scenes[:12], "real_scenes": real})


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
    # form 有三种，第三种是真题实测出来的：
    #   full    成篇（28/38 道）
    #   outline 提纲（7/38，真题明确要「提纲」）
    #   part    **只写指定的几块**（3/38）—— 真题原题：
    #           「拟写调研报告的『问题』和『建议』部分」（2022 川县乡 Q2）
    #           「拟写『提案案由』和『具体建议』」（2025 国考地市 Q4）
    #           「草拟该指南中的工作事项及其相应工作内容」（2025 国考行执 Q3）
    #   这类题不写标题、不写称谓落款，写了就是没读题。
    form = spec.get("form") if spec.get("form") in ("outline", "part") else "full"
    only = _only_parts(doctype, spec.get("only")) if form == "part" else []
    if form == "part" and not only:
        return None, (jsonify({"error": "part 形态要指定写哪几块"}), 400)
    g = GW_MAP[doctype]
    demo = g["demo"]
    scene = (spec.get("scene") or "").strip() or demo["scene"]
    role = (spec.get("role") or "").strip() or demo["role"]
    audience = (spec.get("audience") or "").strip() or demo["audience"]
    desc, fmt = g["d"], g["fmt"]
    pos = spec.get("pos") if spec.get("pos") in POS_BANDS else "medium"   # 自选/文种大全默认中题位；每日成文会按天传档
    score = spec.get("score")
    wmin, wmax = _word_band(doctype, pos, score)
    wtarget = _word_target(wmin, wmax)

    # 规范表述按「结构部件」取——**不再全表一把梭**。
    # 原来这里是 `SELECT ... FROM gongwen_items ORDER BY id` 整表塞进提示词：
    # 写通知和写倡议书喂的是同一份 16 条池子，文种再多也没差别；库一扩就爆上下文。
    # 现在按这个文种的 parts 精准取，取不到再退回全表（库还小，退回是有意义的兜底）。
    gw = _phrase_pool(db, doctype)
    pool = "\n".join("· 【%s】%s" % (x["scene"], x["phrases"]) for x in gw)
    # 场景相关的要点素材（正文的「肉」）。**按治理领域匹配**是这一类的命门：
    # 写垃圾分类的简报时，一条科技创新的举措句毫无用处。
    # 先查 yy_items 的「要点」类（已按 (部件, domain) 归好），取不到再退回原来的概括句表。
    kw = "%" + scene[:6] + "%"
    want_parts = [p for p, _r in parts_of(doctype)] or ["主体·举措"]
    facts = [dict(r) for r in db.execute(
        "SELECT text sentence FROM yy_items WHERE kind='要点' "
        "AND part IN (%s) AND (domain LIKE ? OR text LIKE ?) "
        "ORDER BY (domain LIKE ?) DESC, id LIMIT 6" % ",".join("?" * len(want_parts)),
        want_parts + [kw, kw, kw])]
    if not facts:
        facts = [dict(r) for r in db.execute(
            "SELECT sentence FROM gaikuo_items WHERE topic LIKE ? OR sentence LIKE ? LIMIT 5",
            (kw, kw))]
    quotes = [dict(r) for r in db.execute(
        "SELECT quote FROM xiyu_items WHERE quote LIKE ? LIMIT 3", (kw,))]

    if form == "full":
        head = "写一篇申论**应用文**范文。\n\n"
    elif form == "outline":
        head = ("给这个文种写一份**提纲纲要**。\n"
                "⚠️ 提纲**不是**缩写版的文章：它是**框架式、要点式**的呈现——把骨架摆出来，"
                "每个部件下面用短句列要点（这一块放什么、写到什么程度、用哪种表述），"
                "**不要写成成篇的段落**。目的是让人一眼看清「这个文种由哪几块组成、每块该放什么」。\n\n")
    else:                                   # part：只写指定的几块
        head = ("**只写这几块**，别写整篇：%s。\n"
                "⚠️ 真题里这类题的原话是「拟写调研报告的『问题』和『建议』部分」"
                "「拟写『提案案由』和『具体建议』」——**没让你写标题、称谓、落款**，"
                "写了就是没读题、白花字数。\n"
                "每一块用它的名字起头（如「问题：」「建议：」），块内该分条的照样用"
                "「一、二、三、」规范序号。\n\n" % "、".join(only))

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
           ("字数：**写到 %d 字左右**（正文，不含标题落款；区间 %d~%d，"
            "真题参考答案通常写到上限的 94%%，不要顶着上限、也不要偷懒写到下限）"
            % (wtarget, wmin, wmax)) if form == "full"
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
            "3.1 **分条一律用序号，禁止「一是…二是…三是…」**（也不许用「其一…其二…」）——"
            "「一是」是口头汇报的说法，写进公文正文就是扣分项。序号后直接跟动宾短语，"
            "如「一、健全联防联控机制。」；哪怕在一段之内分层，也写成「一、…。二、…。」。\n"
            "4. **分段合理**：正文按层次分段，一段讲清一层意思（一般 2~5 句），"
            "**严禁一句话一个自然段**；分条项内部若有展开，也放在同一段里。\n"
            "5. **字数**：正文**写到 %d 字左右**（不含标题和落款日期），区间 %d~%d，"
            "**绝不超过 %d 字**——真题参考答案通常写到上限的九成多，"
            "既不要顶着上限注水，也不要写到下限就收。\n"
            "6. 上面的规范表述要**用进去**，别自己造大白话。\n\n"
            % (wtarget, wmin, wmax, wmax)) + (
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
            "3. 主体部分要标出**分条的条数和每条讲什么**，用「一、」「二、」「三、」这类规范序号"
            "（提纲里也不要用「一是…二是…」，免得照着提纲写正文时把口语说法带进去）。\n"
            "4. 该用规范表述的地方，直接把表述写进要点里（如「开头用『为深入贯彻…、结合…实际』」）。\n\n"
            "还要给**逐块说明**：\n"
            "· part：这一块是哪个部件\n"
            "· text：提纲里这一块的原文（**逐字复制**，一字不差）\n"
            "· why：这一块阅卷看什么、最容易丢分在哪（一句话）\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"提纲全文（用 \\n 分行，块名顶格、要点用「· 」缩进）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这个文种的提纲最关键的是哪一块"}')

    if form == "part":                      # part 形态换掉上面那份 req
        req = (
            "【硬要求】\n"
            "1. **只写这几块：%s**。标题、称谓、落款一个都不要写——题目没让写。\n"
            "2. 每块用它的名字起头（「问题：」「建议：」这样），块内分条用"
            "「一、二、三、」规范序号，**不许用「一是…二是…」**。\n"
            "3. 内容要具体、能落地，别写空泛口号；该用规范表述的地方用上面那些零件。\n"
            "4. **字数**：全部内容合起来**写到 %d 字左右**，区间 %d~%d，绝不超过 %d 字。\n\n"
            "还要给**逐块批注** segs：part（块名）、text（该块原文，逐字复制）、"
            "why（这一块阅卷看什么，一句话）。\n\n"
            "只输出 JSON：\n"
            '{"title":"","content":"全部内容（用 \\n 分行，块名顶格）",'
            '"segs":[{"part":"","text":"","why":""}],'
            '"note":"一句话说明这类只写部分内容的题最容易丢分在哪"}'
            % ("、".join(only), wtarget, wmin, wmax, wmax))

    prompt = head + setting + req

    # 范文超字数就自动压一轮（提示词管不死，加道硬兜底）。每轮都收整份 d（含 segs），
    # 批注跟着正文一起换，不会错位。
    #
    # P1 实测：**只给目标字数不够**。三个文种各跑一遍，全部超限 25~43%
    # （经验交流材料 640/550、公开信 1024/1000、简报 716/500），而原来只重试 1 次、
    # 反馈还只是「务必压到 N 字以内」这种笼统话。改成：
    #   · 最多试 3 轮
    #   · 每轮把**当前字数和要删掉多少字**明确告诉它（「现在 716 字，删掉 246 字」）
    # 和 P2 那条经验同理——给具体数字，而不是给要求。
    # 收**最接近目标的那一版**，不是最后一版。
    #
    # 后来（ai_calls 的账查出来的）又发现一件事：**重写压根不是在压缩**。原来第 2、3 轮
    # 发的是「原 prompt + 上一版超了多少字」——上一版正文根本没进消息体，模型是拿着
    # 原题从零再写一篇短的。所以上面那串 665 → 598 → 734 不收敛是必然的：三版之间
    # 除了题目没有任何关系，谈不上「删」。
    # 改成把**上一版正文整篇喂回去、只准删**之后：
    #   · 结果单调（删只会变短），best 那道兜底也就成了纯保险而不是主力；
    #   · 这一步不再产出新内容，于是可以走 fast——立意、选材、格式的钱在第 1 轮
    #     已经花过 pro 了，第 2、3 轮只是拿着 pro 写好的稿子做减法。
    # 首轮仍然是 pro：那才是真正在「写」的一轮。
    d, content, over = None, "", 0
    best = None                       # (超出字数, d, content)
    for attempt in range(3):
        if attempt == 0:
            p, tier = prompt, "pro"
        else:
            p, tier = (
                "下面这版应用文正文 **%d 字，超了 %d 字**。请把它**删到 %d 字左右**"
                "（绝不超过 %d 字）：删次要修饰、合并同类表述、砍掉可省的铺垫。\n"
                "**只做减法**：要点条数、格式部件、称谓落款、分条序号一个都不能少，"
                "不许新增内容、不许改写立意、不许调整段落顺序。\n\n"
                "【上一版正文】\n%s\n\n"
                "批注 segs 要跟着重出，text 必须从**删减后的正文**里逐字复制。\n"
                "只输出 JSON：\n"
                '{"title":"","content":"删减后的全文（用 \\n 分行）",'
                '"segs":[{"part":"","text":"","why":""}],'
                '"note":"一句话说明这个文种最容易丢分的地方"}'
                % (len(re.sub(r"\s", "", content)), over, wtarget, wmax, content)), "fast"
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的应用文范文作者。格式是第一位的，"
                                           "语气要合身份。严格输出 JSON。"},
             {"role": "user", "content": p}],
            temperature=0.5, max_tokens=3500, timeout=300, json_mode=True, tier=tier)
        if err:
            return None, err
        try:
            d = json.loads(rep)
        except Exception:
            return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)
        content = (d.get("content") or "").strip()
        if not content:
            return None, (jsonify({"error": "AI 没写出正文，请重试"}), 502)
        n_now = len(re.sub(r"\s", "", content))
        over = n_now - wmax
        if best is None or over < best[0]:
            best = (over, d, content)
        if form == "outline" or over <= 0:
            break     # 提纲不卡字数；范文和 part 形态达标就收工，否则带着「超了多少」再压一轮
        log.info("应用文 %s 第 %d 版 %d 字，超上限 %d 字，重写", doctype, attempt + 1, n_now, over)
    if best and best[0] < over:        # 三轮都超限时，取超得最少的那一版
        log.info("应用文 %s 三轮都超限，收最接近的一版（超 %d 字，末版超 %d 字）",
                 doctype, best[0], over)
        _, d, content = best

    # 分条改成规范序号。**必须赶在批注核对之前**：批注的 text 是从正文逐字复制的，
    # 正文改了而批注没改，下面那道「必须出现在正文里」的闸会把整篇的批注全丢掉。
    content = fix_fentiao(content, doctype)

    # 格式检查器过一遍。按设计文档那条纪律：**闸门和错例产线是同一件事**——
    # 检查失败不光是提醒，它本身就是一条可入库的错例（错句 + 改正 + 扣分理由）。
    # fix_fentiao 已经把分条改掉了，所以这里剩下的是它管不到的那几类
    # （标签前缀、落款没成行、语气不合身份、缺必需部件）。
    # 整段包在 try 里：错例是副产品，出错不能影响出稿。
    try:
        _harvest_errors(db, content, doctype)
    except Exception:
        log.debug("错例入库失败（不影响出稿）", exc_info=True)

    # 批注的 text 必须真的来自正文，否则点了跳不过去、也说明它在瞎编
    flat = re.sub(r"\s", "", content)
    segs = []
    for s in (d.get("segs") or []):
        t = fix_fentiao((s.get("text") or "").strip(), doctype)
        if not t or re.sub(r"\s", "", t) not in flat:
            continue
        # part 过一遍归一化：模型爱造新名字（实测 408 条批注里 119 种叫法），
        # 不收敛的话「按部件检索」就无从下手
        segs.append({"part": norm_part(s.get("part"))[:12] or (s.get("part") or "").strip()[:12],
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
                            "audience": audience, "form": form, "only": only, "cat": g["cat"],
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
        "或「（一）（二）（三）」**规范序号**分条，别用「首先 / 其次 / 最后」当骨架，"
        "更**不许用「一是…二是…三是…」**（那是口头汇报的说法，写进公文正文要扣分）；面向群众的"
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
    # 范文超 500 字就自动压一轮（硬兜底）。
    #
    # 第 2 轮只压**范文**，给定材料和作答要求原样留着——原来那轮发的是「原 prompt +
    # 压到 N 字」，等于重出一整道题：材料、要求、范文全换新的，只因为范文长了几十字。
    # 那既浪费（材料是这次输出里最长的一块），又让第 1 轮命好的题白出一次。
    # 只压范文之后这一轮不再产出新内容，所以走 fast；命题那轮仍是 pro。
    d, content, material, task = None, "", "", ""
    for attempt in range(2):
        if attempt == 0:
            p, tier = prompt, "pro"
        else:
            p, tier = (
                "下面这篇应用文范文超了字数，请把它**压到 %d 字以内**。\n"
                "**只做减法**：删次要修饰、合并同类表述，要点、格式部件、称谓落款、"
                "分条序号一个都不能少，不许新增内容、不许改写立意。\n\n"
                "【范文】\n%s\n\n"
                "批注 segs 要跟着重出，text 必须从**删减后的范文**里逐字复制。\n"
                "只输出 JSON：\n"
                '{"title":"范文标题","content":"删减后的范文全文（用 \\n 分行）",'
                '"segs":[{"part":"","text":"","why":""}],'
                '"note":"一句话说明这类综合应用最容易丢分的地方"}'
                % (MAX_YY_WORDS, content)), "fast"
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的应用文范文作者，也擅长命制综合应用能力大题。"
                                           "格式是第一位的，语气要合身份。严格输出 JSON。"},
             {"role": "user", "content": p}],
            temperature=0.6, max_tokens=4000, timeout=300, json_mode=True, tier=tier)
        if err:
            return None, err
        try:
            nd = json.loads(rep)
        except Exception:
            return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)
        if attempt == 0:
            d = nd
        else:
            # 压缩轮不出 doctype/material/task，把它压出来的正文和批注贴回第 1 轮那份题上。
            # 万一它把正文压没了，就守着第 1 轮的稿子收工——宁可长几十字，也不能出残篇。
            if not (nd.get("content") or "").strip():
                break
            d = dict(d, **{k: nd[k] for k in ("title", "content", "segs", "note") if k in nd})
        content = (d.get("content") or "").strip()
        material = (d.get("material") or "").strip()
        task = (d.get("task") or "").strip()
        if not content or not material:
            return None, (jsonify({"error": "AI 没出全题，请重试"}), 502)
        if len(re.sub(r"\s", "", content)) <= MAX_YY_WORDS:
            break
    doctype = (d.get("doctype") or "").strip()
    content = fix_fentiao(content)     # 只改范文；给定材料该怎么说话就怎么说话，不动它
    flat = re.sub(r"\s", "", content)
    segs = []
    for s in (d.get("segs") or []):
        t = fix_fentiao((s.get("text") or "").strip())
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
    db = get_db()
    rows = [_e_row(r) for r in db.execute(
        "SELECT * FROM daily_essays WHERE mode='yingyong' ORDER BY id DESC")]
    # 真题参考答案按文种归好，和自产范文摆在一起。
    # **这一步是范文入库的意义所在**：自产的和真题答案能并排比，才知道差在哪；
    # 只灌进库不接界面，等于白灌。
    real_fan = {}
    try:
        for r in db.execute("SELECT id, doctype, title, example, note, freq FROM yy_items "
                            "WHERE kind='范文' ORDER BY freq DESC, id DESC"):
            real_fan.setdefault(r["doctype"] or "", []).append(
                {"id": r["id"], "title": r["example"] or r["title"],
                 "src": r["title"], "note": r["note"] or ""})
    except sqlite3.Error:
        real_fan = {}                     # 表还没建就当没有，不影响这个页面
    # 按 form 分桶，**桶按需建**。原来写的是 by[k][f]，而 by[k] 只预置了 full/outline
    # 两个键——库里 form 的取值不止这两种（还有「只写部分内容」的 part），
    # 一条 part 记录就是一个 KeyError，整个应用文列表页 500 打不开。
    # 实测线上就一条 part，把这个页面崩了 17 次。分桶按实际取值来，别按假设来。
    by = {}
    for r in rows:
        k = (r["spec"] or {}).get("doctype") or r["topic"]
        f = (r["spec"] or {}).get("form") or "full"
        by.setdefault(k, {}).setdefault(f, []).append(
            {"id": r["id"], "title": r["title"], "form": f,
             "scene": (r["spec"] or {}).get("scene") or "", "words": r["words"]})
    cats = []
    for c in GW_CATS:
        ds = []
        for g in GW_DOCTYPES:
            if g["cat"] != c:
                continue
            got = by.get(g["k"]) or {}
            # 除提纲外的形态（full、part、以及以后可能新增的）都当范文摆出来：
            # 宁可多摆一个片段，也不能因为不认识这个 form 就把整条记录悄悄吞掉。
            ds.append({"k": g["k"], "d": g["d"], "fmt": g["fmt"],
                       "freq": g.get("freq", 0), "freq_all": g.get("freq_all", 0),
                       "full": [x for fm in sorted(got) if fm != "outline" for x in got[fm]],
                       "outline": got.get("outline") or [],
                       "real": real_fan.get(g["k"], [])})
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


@bp.get("/api/write/yingyong/mine")
def write_yy_mine():
    """自选成文写过的，按时间倒序摆出来。

    这些一直存在库里（mode='yingyong'），但自选成文那个面板只有一张空表单：
    写完当场看完，一返回就回到表单，那篇再也找不着——得去「文种大全」里按文种翻。
    一篇要跑一次 AI，找不回来等于白写，所以入口就放在写它的那一页。
    一键铺开的也在这个 mode 里，一并摆出来（自选的最新，永远在最上面）。"""
    db = get_db()
    items = []
    for r in db.execute("SELECT id,date,topic,title,words,spec FROM daily_essays "
                        "WHERE mode='yingyong' ORDER BY id DESC LIMIT 60"):
        try:
            sp = json.loads(r["spec"] or "{}")
        except Exception:                 # spec 坏了不能连累整个列表，当没有就是
            log.debug("daily_essays.spec 不是合法 JSON，按空处理", exc_info=True)
            sp = {}
        items.append({"id": r["id"], "date": r["date"] or "", "words": r["words"],
                      "title": r["title"] or "",
                      "doctype": sp.get("doctype") or r["topic"] or "",
                      "scene": sp.get("scene") or "",
                      "form": sp.get("form") or "full"})
    return jsonify({"items": items})


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
    """每日成文：列出有素材的日期 + 每天写了没有；素材断供的日子也要列出来。

    这个列表原来只 SELECT 有素材的日期——素材一断，那几天干脆不出现在列表里，
    界面看上去「最新的一天就是 7-24」，补齐按钮还理直气壮地写着「往期都写齐了」
    （它数的是「有素材但没写」的天数，断供当然是 0）。2026-07-25 素材真断了 4 天，
    从界面上完全看不出坏了。所以这里补上最近 14 天的空档：n=0 的日子照样返回，
    前端把它显示成「素材没更新」，坏了要能一眼看见。
    """
    db = get_db()
    _sucai_import(db)
    rows = db.execute(
        "SELECT s.date, COUNT(*) n, "
        "SUM(CASE WHEN s.kind='衔接表达' THEN 1 ELSE 0 END) nl, "
        "e.id eid, e.title, e.topic, e.words "
        "FROM sucai_items s LEFT JOIN daily_essays e ON e.mode='daily' AND e.date=s.date "
        "GROUP BY s.date ORDER BY s.date DESC").fetchall()
    days = [dict(r) for r in rows]

    # 空档只从「素材开始有的那天」算起，别把用不上这个功能之前的日子也标成坏了
    have = {d["date"] for d in days}
    first = min(have) if have else None
    today = datetime.now().date()
    for i in range(14):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in have or (first and d < first):
            continue
        days.append({"date": d, "n": 0, "nl": 0, "eid": None,
                     "title": None, "topic": None, "words": None, "nosucai": 1})
    days.sort(key=lambda x: x["date"], reverse=True)
    return jsonify({"days": days})


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
    content, outline, rep = align(e["content"], e["outline"], wmax=WRITE_MAX)
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
    """输入口语句/场景 → AI 给出公文规范上位表述，并收录。

    档位 fast：一句口语 → 一组现成的规范说法，属于「查词典」而不是「写文章」——
    这些表述是公文里的固定用语，不需要旗舰去现想。正文额度也只有 500。"""
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
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=500, json_mode=True, tier="fast")
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


@bp.get("/api/write/realfan/<int:iid>")
def write_realfan(iid):
    """看一份真题参考答案：正文 + 出处 + 原题题干和要求。

    题干要一起给——**范文脱离题目没法学**。看到「这道题要求 500 字、
    要内容全面条理清晰」，才看得懂答案为什么这么写。
    """
    db = get_db()
    r = db.execute("SELECT * FROM yy_items WHERE id=? AND kind='范文'", (iid,)).fetchone()
    if not r:
        return jsonify({"error": "范文不存在"}), 404
    out = {"id": r["id"], "doctype": r["doctype"], "title": r["example"] or r["title"],
           "src": r["title"], "content": r["text"], "note": r["note"] or "",
           "src_ref": r["src_ref"] or ""}
    # 按 src_ref（形如「2025国考 Q3」）把原题捞回来
    m = re.match(r"^(\d{4})(\S+?)\s*Q(\d+)$", (r["src_ref"] or "").strip())
    if m:
        # **必须带上文种一起匹配**。src_ref 形如「2020国考 Q5」没有卷种，
        # 而 2020 国考有省级/地市两份卷子、都有第 5 题——只按 (年份,考试,题号) 取，
        # LIMIT 1 会随便挑一份，实测把讲话稿的范文配上了推荐材料的题干。
        q = db.execute(
            "SELECT q.stem, q.require, q.score, q.words, p.name FROM slreal_questions q "
            "JOIN slreal_papers p ON p.id=q.paper_id "
            "WHERE p.year=? AND p.exam=? AND q.seq=? AND q.qkind='贯彻执行' "
            "AND q.doctype=? AND q.answer!='' LIMIT 1",
            (int(m.group(1)), m.group(2), int(m.group(3)), r["doctype"] or "")).fetchone()
        if q:
            out["stem"] = q["stem"]
            out["require"] = q["require"]
            out["score"], out["limit"] = q["score"], q["words"]
            out["paper"] = q["name"]
    return jsonify(out)


@bp.get("/api/gongwen/yylib")
def gongwen_yylib():
    """应用文素材库：按「文种 → 部件」两级下钻。

    文种**按真题频次排序**，并把「考过几次」显示出来——这是这个页面最要紧的一点：
    让「该练什么」有依据，而不是按录入顺序排。零频的老文种（通知/倡议书/新闻稿）
    照样列出来但排在后面，标「近五年未考」。

    不传 doctype 时给目录（文种 + 每个文种下各部件的条数）；
    传了就给那一格的条目。空的格子也要能看见——库里哪块没素材，是这个页面该回答的问题。
    """
    db = get_db()
    kind = (request.args.get("kind") or "").strip()
    doctype = (request.args.get("doctype") or "").strip()
    part = (request.args.get("part") or "").strip()

    if doctype:
        where, args = ["(doctype=? OR doctype='')"], [doctype]
        if part:
            where.append("part=?")
            args.append(part)
        if kind:
            where.append("kind=?")
            args.append(kind)
        rows = db.execute(
            "SELECT id, kind, doctype, part, title, text, note, example, src, src_ref, freq "
            "FROM yy_items WHERE %s ORDER BY freq DESC, id LIMIT 200" % " AND ".join(where),
            args).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            # 错例和得体的正文都是成对 JSON，摊开给前端（前端不该解析业务 JSON）
            if r["kind"] in ("错例", "得体"):
                try:
                    p = json.loads(r["text"] or "{}")
                    if r["kind"] == "错例":
                        d["bad"], d["good"] = p.get("bad", ""), p.get("good", "")
                    else:
                        d["good"], d["bad"] = p.get("do", ""), p.get("dont", "")
                    d["text"] = ""
                except Exception:
                    pass
            items.append(d)
        return jsonify({"items": items, "doctype": doctype, "part": part})

    # 目录：每个文种 × 部件的条数
    grid = {}
    for r in db.execute("SELECT doctype, part, kind, COUNT(*) c FROM yy_items "
                        + ("WHERE kind=? " if kind else "")
                        + "GROUP BY doctype, part, kind", ([kind] if kind else [])):
        grid.setdefault(r["doctype"] or "", {}).setdefault(r["part"] or "", 0)
        grid[r["doctype"] or ""][r["part"] or ""] += r["c"]

    cats = []
    for g in sorted(GW_DOCTYPES, key=lambda x: (-x.get("freq", 0), -x.get("freq_all", 0), x["k"])):
        cells = grid.get(g["k"], {})
        parts = [{"part": p, "n": cells.get(p, 0), "req": bool(req)}
                 for p, req in parts_of(g["k"])]
        # 库里挂在这个文种下、但不属于它 parts 的部件也列出来（数据和定义不一致要看得见）
        for p, n in sorted(cells.items(), key=lambda x: -x[1]):
            if p and p not in {x["part"] for x in parts}:
                parts.append({"part": p, "n": n, "req": False, "extra": True})
        cats.append({"k": g["k"], "fam": g.get("fam", ""), "cat": g["cat"],
                     "d": g["d"], "freq": g.get("freq", 0),
                     "freq_all": g.get("freq_all", 0),
                     "parts_src": g.get("parts_src", "prior"),
                     "n": sum(cells.values()), "parts": parts})
    kinds = {r[0] or "": r[1] for r in db.execute(
        "SELECT kind, COUNT(*) FROM yy_items GROUP BY kind")}
    return jsonify({"cats": cats, "kinds": kinds, "total": sum(kinds.values()),
                    "generic": grid.get("", {})})


@bp.get("/api/gongwen/errquiz")
def gongwen_errquiz():
    """应用文错例小测：**零 AI 调用**——错例本身就是题。

    题型是判断题：随机给「错句」或「改正后的句子」，让你判这样写对不对，
    然后给出为什么。为什么不做四选一：库里只有 4 类检查项，选项一轮就背下来了，
    变成考「记住了几类」而不是考「认不认得出」。判断题反过来——每次面对的是
    一句具体的话，要真的看出它哪里不合规范。

    一半给错句一半给改正（`want_bad` 按位置定，不用随机数——同一份卷子刷新不该变）。
    只给「错句」的话，做几道就摸出规律「反正都选错」，等于没考。
    """
    n = max(4, min(20, int(request.args.get("n") or 10)))
    db = get_db()
    # 按检查项轮着取，别让占 85% 的「分条方式」霸满一份卷子
    rows = db.execute("SELECT id, doctype, part, title, text, note FROM yy_items "
                      "WHERE kind='错例' ORDER BY freq DESC, RANDOM()").fetchall()
    by_chk = {}
    for r in rows:
        by_chk.setdefault((r["title"] or "").split("·")[0], []).append(r)
    picked, keys = [], sorted(by_chk, key=lambda k: -len(by_chk[k]))
    while len(picked) < n and any(by_chk[k] for k in keys):
        for k in keys:
            if by_chk[k] and len(picked) < n:
                picked.append(by_chk[k].pop(0))

    out = []
    for i, r in enumerate(picked):
        try:
            pair = json.loads(r["text"] or "{}")
        except Exception:
            continue
        bad, good = (pair.get("bad") or "").strip(), (pair.get("good") or "").strip()
        if not bad or not good:
            continue
        want_bad = (i % 2 == 0)
        out.append({
            "id": r["id"], "seq": i + 1,
            "check": (r["title"] or "").split("·")[0],
            "where": " · ".join(x for x in [r["doctype"] or "", r["part"] or ""] if x),
            "text": bad if want_bad else good,
            "answer": "wrong" if want_bad else "right",   # 客户端判分（自学用，不防作弊）
            "bad": bad, "good": good, "why": r["note"] or "",
        })
    return jsonify({"items": out, "total": len(out)})


@bp.delete("/api/gongwen/<int:gid>")
def gongwen_del(gid):
    db = get_db()
    db.execute("DELETE FROM gongwen_items WHERE id=? AND source='ai'", (gid,))  # 种子词库不许删
    db.commit()
    return jsonify({"ok": True})

