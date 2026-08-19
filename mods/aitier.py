"""AI 档位控制：按「服务」把模型档位钉成便宜的还是质量优先的。

**为什么要有这一页**：档位（fast/pro）本来是写死在代码里的——哪个任务值得用旗舰
模型，是写代码时的判断。可「值不值」会随钱变：账单紧的月份，宁可让每日范文差一点
也不想烧那么多 token；反过来临考前，又愿意把批改全调到 pro。这种取舍不该每次都去
改代码、改完还要重启 13 个定时器脚本。

**旋钮只有一个**：真正生效的地方在 `aiclient.effective_tier()` / `effective_vision()`
——全站（含那些没人 import 的定时器脚本）唯一都要经过的隘口。这里只负责「给旋钮配
一张能看懂的面板」：把 aimeter 记的 caller（模块名）翻成人话，配上近期用量，好让
管理员知道**降谁最省**。

**两家模型一页管**：文字走 DeepSeek（fast / pro），读图走智谱（free / pro）。两套
键的形状、优先级、清除方式完全一致，只是存在 config.json 的不同键里。

**降档有闸**：把默认走旗舰的服务降下来不会报错，只会悄悄变差——真题解析错了会带偏
出题、批改降档用户当场看不出来。所以这类改动后端会先回一份「你正在降这几项、后果
是什么」，带 confirmed 再来才执行。闸在后端而不只在前端：绕过界面直接打接口的也得过。

**服务名 = caller**，跟后台「AI 用量」报表同一套口径。名册里没登记的会从 ai_calls
里自动冒出来（显示原名），所以新增业务模块不会从这页消失——只是没中文名而已。
tests/test_aitier.py 守着「代码里写了 tier="pro" 的模块，名册必须标了 pro」。
"""
from flask import Blueprint, jsonify, request

import aiclient
from core import CFG, _save_cfg, get_db

bp = Blueprint("aitier", __name__)

# 名册：caller → (中文名, 说明, 文字档位, 读图档位, 归类)
# 归类只影响面板怎么分组：web=用户点了才跑，cron=定时器/离线脚本在后台跑。
# 档位写全（("fast", "pro") 表示这个模块两种调用都有），面板才能分别给旋钮；
# 读图那列为空表示它不碰视觉模型。
SERVICES = [
    # ---- 应用内，用户触发 ----
    ("agent",      "AI 助手 · 对话与工具", "全局助手的每一轮回答（会调工具操作应用）", ("fast",), (), "web"),
    ("aisession",  "AI 助手 · 看图与摘要", "对话里发的图、起标题、压缩历史", ("fast",), ("pro",), "web"),
    ("aichat",     "AI 问答", "不带工具的直接问答与后台连通性自检", ("fast",), (), "web"),
    ("write",      "大作文成文", "取材、列提纲走 fast；成文与润色走 pro", ("fast", "pro"), (), "web"),
    ("gongwen",    "应用文写作", "公文成文走 pro；提法校对这类小活走 fast", ("fast", "pro"), (), "web"),
    ("find",       "申论小题（找点 / 写点）", "找要点与批改走 pro，材料预处理走 fast", ("fast", "pro"), (), "web"),
    ("shequ",      "社区主观题批改", "案例分析 + 公文按采分点逐点批改（判「沾边」比判对错难，走 pro）",
     ("pro",), (), "web"),
    ("fanwen",     "范文拆解与批注", "人民时评逐段拆解，质量敏感", ("pro",), (), "web"),
    ("dailytest",  "每日巩固测试出题", "按当天学的内容现出小测", ("pro",), (), "web"),
    ("dtest",      "测试结果分析", "对着做题记录给学习建议", ("pro",), (), "web"),
    ("drill",      "专项练", "资料分析 / 判断推理 / 数量关系", ("fast",), (), "web"),
    ("docqa",      "文档识题", "从资料里抽例题并解答，图要看清才抽得准", ("fast",), ("pro",), "web"),
    ("ocr",        "拍照识题", "把照片里的题转写成文字", (), ("free",), "web"),
    ("attach",     "附件文本提取", "读图转写，AI 对话里传的附件走这条", ("fast",), ("free",), "web"),
    ("marks",      "划重点", "在任意长文本上标考点", ("fast",), (), "web"),
    ("plan",       "冲刺路线图", "按剩余天数铺学习计划", ("fast",), (), "web"),
    ("sucai",      "每日写作素材", "素材入库与整理", ("fast",), (), "web"),
    ("changkao",   "常考合集", "高频考点的释义与例句", ("fast",), (), "web"),
    ("classics",   "古诗文每日推荐", "选诗与推荐语", ("fast",), (), "web"),
    ("classics_lookup", "古诗文速查", "查词条时的补充讲解", ("fast",), (), "web"),
    ("align",      "提纲对照", "提纲与正文的对照呈现", ("fast",), (), "web"),
    ("shenlun",    "申论真题拆题", "把整卷拆成题、判题型", ("fast",), (), "web"),
    ("social",     "聊天助手", "好友聊天里的 AI 搭话", ("fast",), (), "web"),
    ("basics",     "机构讲义知识点", "讲义考点的检索与讲解", ("fast",), (), "web"),
    # ---- 定时器 / 离线脚本 ----
    ("gen_essays", "范文生成（每日）", "仿真卷 + 全套参考答案，token 大户", ("pro",), (), "cron"),
    ("gen_quiz",   "题库生成（每周二 / 五）", "按四川省考卷面结构出整套新题", ("pro",), (), "cron"),
    ("gen_real_explain", "真题答案与解析", "真题库是全站标尺，解析错了会带偏出题", ("pro",), (), "cron"),
    ("gen_changshi", "常识速记生成", "常识积累的每日供货", ("fast",), (), "cron"),
    ("gen_changkao", "常考 / 上位词生成", "常考模块的内容供货", ("fast",), (), "cron"),
    ("gen_theory", "理论基础生成", "马原 / 毛中特 / 习思想知识点", ("fast",), (), "cron"),
    ("gen_gushi",  "古诗复习卡生成", "每日古诗那一路的供货", ("fast",), (), "cron"),
    ("crawl_news", "时政摘要（每日）", "抓回来的时政按公考视角压缩", ("fast",), (), "cron"),
    ("crawl_exam", "考情归类", "招考公告的归类与抽日期", ("fast",), (), "cron"),
    ("crawl_video", "新闻视频筛选", "按公考价值筛掉大部分", ("fast",), (), "cron"),
    ("crawl_rmsp", "人民时评抓取", "范文语料的每日供货", ("fast",), (), "cron"),
    ("summarize_ai", "对话总结成笔记", "把与助手的对话整理进资料库", ("fast",), (), "cron"),
    ("ingest_basics", "讲义入库解析", "机构资料解析成考点，只在导入时跑", ("fast",), (), "cron"),
    ("import_teacher", "老师资料导入", "一次性导入，平时不跑", ("fast",), (), "cron"),
    ("fill_examples", "衔接表达补例句", "每天素材更新后跑一次", ("fast",), (), "cron"),
    ("build_ck_meaning", "常考词条释义补全", "建库脚本，按需手跑", ("fast",), (), "cron"),
]

_MAP = {k: (n, d, t, v, g) for k, n, d, t, v, g in SERVICES}
_ORDER = {k: i for i, (k, *_r) in enumerate(SERVICES)}

# 两家模型的档位集合与它们各自的配置键。面板上是两列旋钮，代码里是两张同形状的表。
KINDS = {
    "text":   {"key": aiclient.OVERRIDE_KEY, "tiers": aiclient.TIERS,
               "cheap": "fast", "rich": "pro", "label": "文字", "cheap_name": "快速档"},
    "vision": {"key": aiclient.VISION_KEY, "tiers": aiclient.VISION_TIERS,
               "cheap": "free", "rich": "pro", "label": "读图", "cheap_name": "免费档"},
}

# 记账里 tier 为空串的是历史数据，别混进用量。
_TEXT_TIERS = tuple(aiclient.TIERS)

WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


def _ov(kind):
    o = CFG.get(KINDS[kind]["key"])
    return dict(o) if isinstance(o, dict) else {}


def _usage(win):
    """近 N 天每个 (caller, tier) 的调用数与 token。没有 ai_calls 表就当全 0——
    一次调用都还没发生过是正常状态，不是错误。

    读图那家记的 tier 是 "vision"（没分档，两个模型名都记在 model 列），
    所以视觉那一行的用量按 caller 汇总，不按档位拆。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='ai_calls'").fetchone():
        return {}
    rows = db.execute(
        "SELECT caller, tier, COUNT(*) calls, SUM(ok) ok_calls, "
        "SUM(prompt_tokens+completion_tokens+reasoning_tokens) tk "
        "FROM ai_calls WHERE ts >= datetime('now','localtime','-%d day') "
        "GROUP BY caller, tier" % WINDOWS[win]).fetchall()
    return {(r["caller"] or "?", r["tier"] or ""): {
        "calls": r["calls"], "tokens": r["tk"] or 0,
        "failed": r["calls"] - (r["ok_calls"] or 0)} for r in rows}


def _rows(key, kind, tiers, ov, use, usage_tier):
    """一个服务在一家模型下的若干行：代码里用到几个档位就有几行，各自能单独设。"""
    out = []
    for t in tiers:
        # 读图那家没按档位记账（usage_tier 固定是 "vision"），所以整份用量只挂在
        # 第一行上——挂到每一行会让同一批调用被数两遍，排序和「谁在烧钱」全错。
        u = ({"calls": 0, "tokens": 0, "failed": 0} if usage_tier and out else
             use.get((key, usage_tier or t)) or {"calls": 0, "tokens": 0, "failed": 0})
        out.append({
            "tier": t, "override": ov.get("%s:%s" % (key, t), ""),
            "effective": (aiclient.effective_tier(t, CFG, key) if kind == "text"
                          else aiclient.effective_vision(t, CFG, key)),
            "calls": u["calls"], "tokens": u["tokens"], "failed": u["failed"],
        })
    return out


def _service(key, ovs, use):
    name, desc, tiers, vtiers, group = _MAP.get(key) or (
        key, "名册里还没登记这个服务（它照样能设）", ("fast",), (), "web")
    # 历史用量里出现过、但名册没写的档位也要摆出来：代码改过档位而名册没跟上时，
    # 面板不能装作那些调用不存在——否则管理员会以为自己已经全管住了。
    tiers = tuple(dict.fromkeys(tiers + tuple(t for t in _TEXT_TIERS if (key, t) in use)))
    if not vtiers and (key, "vision") in use:
        vtiers = ("free",)
    text = _rows(key, "text", tiers, ovs["text"], use, None)
    vision = _rows(key, "vision", vtiers, ovs["vision"], use, "vision")
    return {
        "key": key, "name": name, "desc": desc, "group": group, "known": key in _MAP,
        "text": {"override": ovs["text"].get(key, ""), "rows": text},
        "vision": {"override": ovs["vision"].get(key, ""), "rows": vision},
        "calls": sum(r["calls"] for r in text + vision),
        "tokens": sum(r["tokens"] for r in text + vision),
    }


@bp.get("/api/admin/ai/tiers")
def tiers_get():
    win = request.args.get("win", "30d")
    if win not in WINDOWS:
        win = "30d"
    ovs = {k: _ov(k) for k in KINDS}
    use = _usage(win)
    # 自动发现名册外的服务，但**设不了的不摆出来**：caller 记成 "?" 的那些
    # （异常栈里找不到发起方）没有可写的键，摆出来只会让人点了没反应。
    extra = sorted({c for (c, t) in use if c not in _MAP and _clean(c)})
    svcs = [_service(k, ovs, use) for k in list(_MAP) + extra]
    svcs.sort(key=lambda s: (-s["tokens"], _ORDER.get(s["key"], 999)))
    return jsonify({
        "win": win,
        "models": {"fast": aiclient.conf("fast", CFG, who="")["model"],
                   "pro": aiclient.conf("pro", CFG, who="")["model"],
                   "vision_free": CFG.get("vision_model_free") or "",
                   "vision_pro": CFG.get("vision_model") or ""},
        "vision_configured": bool(CFG.get("vision_key") and CFG.get("vision_base")),
        "global": {k: ovs[k].get("*", "") for k in KINDS},
        "groups": [
            {"key": "web", "name": "应用内 · 用户触发",
             "services": [s for s in svcs if s["group"] == "web"]},
            {"key": "cron", "name": "定时任务 · 后台自动跑",
             "services": [s for s in svcs if s["group"] != "web"]},
        ],
    })


def _clean(k, tiers=_TEXT_TIERS):
    """键只允许 `*`、`服务名`、`服务名:档位` 三种形状。配置文件是全站共用的，
    不校验就等于让接口往里写任意键。"""
    k = (k or "").strip()
    if k == "*":
        return k
    base, _, t = k.partition(":")
    if not base or not base.replace("_", "").replace("-", "").isalnum():
        return ""
    if t and t not in tiers:
        return ""
    return k


# ---------------------------------------------------------------- 降档闸
def _defaults(key, kind):
    """这个服务在这家模型下，代码里写的是哪几个档。名册没登记的按最省的算——
    宁可少弹一次确认，也不要对着一个连档位都不知道的服务吓唬人。"""
    e = _MAP.get(key)
    if not e:
        return ()
    return e[2] if kind == "text" else e[3]


def _guarded(k, v, kind):
    """这一改是不是「把本来走旗舰的降下来」。返回一句说清后果的话，不是就返回空。

    只拦降档：升档只是多花钱，钱是管理员自己的事，用不着挡一道。
    """
    rich, cheap = KINDS[kind]["rich"], KINDS[kind]["cheap"]
    if v != cheap:
        return ""
    what, cheap_name = KINDS[kind]["label"], KINDS[kind]["cheap_name"]
    if k == "*":
        hit = [_MAP[s][0] for s in _MAP if rich in _defaults(s, kind)
               and not _ov(kind).get(s)]
        if not hit:
            return ""
        more = "，等 %d 项" % len(hit) if len(hit) > 6 else ""
        return "把%s任务全站压到%s：这些还没单独设过的服务会一起降下来——%s%s。" % (
            what, cheap_name, "、".join(hit[:6]), more)
    base, _, t = k.partition(":")
    if (t or rich) != rich or rich not in _defaults(base, kind):
        return ""
    name, desc = (_MAP[base][0], _MAP[base][1]) if base in _MAP else (base, "")
    return "「%s」的%s任务默认走旗舰档（%s），现在要降到%s。降档不会报错，只会悄悄变差。" % (
        name, what, desc, cheap_name)


def _apply(sets, kind, ov, confirmed):
    """把一批设置合进覆盖表。返回 (改了几条, 需要确认的清单)。"""
    tiers = KINDS[kind]["tiers"]
    changed, need = 0, []
    for k, v in (sets or {}).items():
        k = _clean(k, tiers)
        if not k:
            continue
        v = (v or "").strip().lower()
        if v and v not in tiers:
            raise ValueError("%s 档位只能是 %s" % (KINDS[kind]["label"], " 或 ".join(tiers)))
        if not confirmed:
            why = _guarded(k, v, kind)
            if why:
                need.append({"key": k, "kind": kind, "why": why})
                continue
        if v:
            if ov.get(k) != v:
                ov[k], changed = v, changed + 1
        elif k in ov:
            del ov[k]
            changed += 1
    return changed, need


@bp.post("/api/admin/ai/tiers")
def tiers_set():
    """批量设置。body:
        {"set": {"gen_essays": "fast", "write:pro": "", "*": "fast"},
         "vision": {"docqa": "free"},
         "confirmed": true}

    值为空串 = 取消覆盖、跟随代码默认；这也是**唯一**的清除方式，所以空值不是
    「没传」而是「删掉这条」——面板上那个「跟随默认」选项就靠它。

    降档要过闸：没带 confirmed 时**一条都不写**，回一份 need_confirm 说清后果。
    要么全过要么全不过，免得「确认弹窗还开着，一半改动已经生效了」。
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("set"), dict) and not isinstance(data.get("vision"), dict):
        return jsonify({"error": "没有要改的项"}), 400
    confirmed = bool(data.get("confirmed"))
    ovs = {k: _ov(k) for k in KINDS}
    changed, need = 0, []
    try:
        for kind, field in (("text", "set"), ("vision", "vision")):
            n, q = _apply(data.get(field), kind, ovs[kind], confirmed)
            changed += n
            need += q
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if need:
        return jsonify({"ok": False, "need_confirm": need})
    for kind in KINDS:
        CFG[KINDS[kind]["key"]] = ovs[kind]
    _save_cfg()
    # 改完即生效：Web 侧读内存 CFG，定时器脚本是每次唤醒新起进程读盘。都不用重启。
    return jsonify({"ok": True, "changed": changed,
                    "overrides": {k: ovs[k] for k in KINDS}})
