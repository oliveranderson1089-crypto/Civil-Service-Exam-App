"""AI 工具注册表 + 全部「读」工具。

原来 agent.py 把 4 个工具的 schema 和 if/elif 分发焊死在一起，加一个工具要改三处。
这里换成注册表：@tool 把 schema 和 handler 焊在一处，agent.py 的对话循环只认
tool_specs()/exec_tool() 两个口子，不用再碰。

依赖单向：agent.py → agent_tools.py → core。本文件绝不 import mods.agent（否则成环）。
「写/改/删/导航」类工具留在 agent.py（它们要调 agent.py 里的入库助手，且 entries.py
还在 import 那些助手）；本文件放注册表基建 + 所有只读工具（只依赖 core，最干净）。

工具 handler 契约不变：入参 (args, db)，返回 (给模型看的文本, 给前端的 action | None)。
读工具一律 action=None，把查到的数据以紧凑 JSON 回给模型，让它据实回答。
"""
import json
import re
from datetime import datetime

from core import _study_stats, get_db, log, lookup, uid

# name -> {"spec": {...}, "handler": fn, "kind": str, "confirm": bool}
TOOL_REGISTRY = {}


def tool(name, desc, params, kind="write", confirm=False, preview=None):
    """把一个工具登记进注册表。

    kind: read（只查）| write（新增，可撤销）| update（改已有）|
          destructive（删除/覆盖，需确认）| navigate（跳前端页）
    confirm: True 时要二次确认——没带 _confirmed 就先回确认请求，不真执行。
             不只给删除用：写长期记忆也走它（AI 悄悄记错一条，之后每轮都拿它答，
             比删错还难发现；让用户点一下头，记忆才配一直待在上下文里）。
    preview: 仅 confirm 类要给。(args, db) -> 一句话说清「要删的到底是哪一条」，
             进确认弹窗给用户看。没有它，删错题/删小记只能弹「确认删除这条内容？」，
             用户根本不知道是哪条，只能盲点确定。
    """
    def deco(fn):
        TOOL_REGISTRY[name] = {
            "spec": {"type": "function", "function": {
                "name": name, "description": desc, "parameters": params}},
            "handler": fn, "kind": kind, "confirm": confirm, "preview": preview}
        return fn
    return deco


# 工具名 → 给用户看的人话。流式时前端拿它显示「正在查你的错题本…」，
# 而不是所有工具一律显示成「正在操作…」——这个助手能改能删，得说清在动谁的数据。
TOOL_LABELS = {
    "get_user_overview": "查你的数据总览", "get_library_stats": "查题库规模",
    "lookup_word": "查词义", "global_search": "全局搜索",
    "list_words": "查你的收录", "list_wrong_questions": "查你的错题本",
    "list_notes": "查你的小记", "get_today_review": "查今天要复习的",
    "get_daily_tasks": "查今天的任务", "get_plan_today": "查今天的计划",
    "get_plan_progress": "查计划进度", "search_yy": "查言语题",
    "search_sucai": "找素材", "list_bookmarks": "查你的收藏",
    "get_daily_news": "查今日时政", "search_classics": "找古诗文",
    "search_changshi": "查常识", "list_materials": "查资料库",
    "search_kb": "查知识库",
    "list_project_files": "查项目资料", "read_project_file": "读项目资料", "get_study_stats": "查学习统计",
    "search_real_questions": "翻真题库", "search_basics": "查讲义知识点",
    "list_drive": "查云盘", "read_drive_file": "读云盘文件",
    "get_exam_countdown": "算考试倒计时",
    "web_search": "上网搜", "web_fetch": "读网页",
    "add_word": "收录到成语词语积累", "open_feature": "打开功能",
    "create_note": "记一条小记", "add_wrong_question": "加进错题本",
    "update_wrong_question": "修改错题", "star_word": "收藏词条",
    "append_to_note": "追加到小记", "add_daily_task": "加每日任务",
    "complete_daily_task": "完成任务", "complete_plan_item": "完成计划项",
    "star_classic": "收藏古诗文", "remember_fact": "记住这件事",
    "create_file": "生成文件", "deliver_file": "投放文件", "list_files": "查 AI 产出",
    "delete_entry": "删除收录的词",
    "delete_wrong_question": "删除错题", "delete_note": "删除小记",
}


def tool_label(name):
    return TOOL_LABELS.get(name) or ("调用 " + str(name or ""))


def tool_specs(kinds=None):
    """给模型的 tools 列表。kinds 可传如 ("read",) 只给读工具（一问一答入口用）。"""
    return [t["spec"] for t in TOOL_REGISTRY.values()
            if not kinds or t["kind"] in kinds]


# 读工具按主题分组，配一组触发词。**只用来裁读工具**：
# 写/改/删/导航一律全给（用户明确要求时才会用到，裁掉就变成「它突然不会做这件事了」）。
READ_GROUPS = (
    ("错题|做错|错的题|订正|判断推理|言语|资料分析|常识|申论|行测",
     ("list_wrong_questions", "get_study_stats", "search_yy")),
    ("复习|背|记忆|遗忘|今天学|今日",
     ("get_today_review", "get_daily_tasks", "get_plan_today", "get_plan_progress")),
    ("计划|进度|坚持|连续|多少天|正确率|成绩",
     ("get_plan_today", "get_plan_progress", "get_study_stats", "get_user_overview")),
    ("成语|词语|实词|收录|积累|释义|什么意思|读音",
     ("list_words", "lookup_word", "search_changshi")),
    ("小记|笔记|记过|写过",
     ("list_notes", "list_bookmarks")),
    ("古诗|诗词|文言|名句|古文|典故",
     ("search_classics",)),
    ("素材|范文|时评|金句|例子|案例",
     ("search_sucai", "get_daily_news", "list_materials")),
    ("时政|新闻|政策|会议|讲话",
     ("get_daily_news", "search_sucai", "search_changshi")),
    ("资料|文件|讲义|知识库|题库|多少题",
     ("list_materials", "search_kb", "get_library_stats", "search_basics", "list_files",
      "list_project_files", "read_project_file")),
    # 项目资料是**挂在项目上、项目下所有对话共享**的那几份文件。这一组要宽：
    # 在项目里问「这份怎么讲的」「按标准给我打分」，问句里常常连「资料」两个字都没有。
    ("项目|挂的|挂了|参考资料|评分标准|模板|标准|原文|这份|那份|按标准|范文",
     ("list_project_files", "read_project_file")),
    # ↓ 下面这几组是随新工具一起加的。**加读工具必须同时加触发词**：这个函数只裁读工具，
    #   漏了就等于「明明有这个工具，它却回一句我做不到」——比没有这个工具更让人火大。
    ("真题|考过|历年|原题|类似的题|出几道|做几道|练几道|来一道|来几道",
     ("search_real_questions", "search_yy", "list_wrong_questions")),
    ("知识点|考点|讲义|书上|怎么讲|方法|技巧|公式|口诀|怎么做",
     ("search_basics", "search_kb", "search_real_questions")),
    ("云盘|网盘|我传的|上传过|存过|文档|附件",
     ("list_drive", "read_drive_file", "list_materials", "list_files")),
    ("还有多少天|倒计时|考试时间|什么时候考|几号考|考期",
     ("get_exam_countdown", "get_plan_progress", "get_plan_today")),
    # 联网这一组要**宽**：漏掉它的代价是模型拿两年前的印象回答「最近怎么样」，
    # 而多给一个工具的代价只是多几百 token。
    ("最新|最近|今年|今天|昨天|现在|目前|公告|官网|报名|职位表|大纲|上网|搜一下|查一下|新闻|时政|政策",
     ("web_search", "web_fetch", "get_daily_news")),
    ("生成|导出|存成|做成|写一份|整理成|PDF|文件|下载",
     ("list_files", "list_materials")),
)
# 无论问什么都带上的读工具：总览 + 全局搜索是「不知道去哪找」时的兜底
ALWAYS_READ = ("get_user_overview", "global_search")


# 会话本身带来的工具：当前对话挂在某个项目下时，项目资料那两个**永远给**。
# 它们是「随时调用挂在项目上的资料」的唯一途径，被意图裁掉的表现是模型回一句
# 「我看不到你的文件」—— 而文件就挂在那儿，用户刚传完。
PROJECT_TOOLS = ("list_project_files", "read_project_file")


def tool_specs_for(text, min_tools=12, always=()):
    """按这句话的意图挑工具。命中不了任何主题就**原样全给**——宁可多给，
    也不能让模型因为工具被裁掉而回一句「我做不到」。

    always 是**跟这句话无关、由会话上下文决定**要留的读工具（见 PROJECT_TOOLS）。

    动机：34 个工具的 schema 每轮都发一遍，既是固定开销，也让模型在一堆相近的
    list_*/get_* 里挑，选错的概率随数量上升。
    """
    t = text or ""
    hit = set()
    for pat, names in READ_GROUPS:
        if re.search(pat, t):
            hit.update(names)
    if not hit:
        return tool_specs()
    keep = hit | set(ALWAYS_READ) | set(always)
    out = [v["spec"] for k, v in TOOL_REGISTRY.items()
           if v["kind"] != "read" or k in keep]
    # 裁得只剩几个反而更容易选错（模型会硬套手上有的那个），太少就别裁了
    return out if len(out) >= min_tools else tool_specs()


def exec_tool(name, args, db):
    """执行一个工具。返回 (给模型看的结果文本, 给前端的 action | None)。"""
    t = TOOL_REGISTRY.get(name)
    if not t:
        return "未知工具：" + str(name), None
    if t["confirm"] and not args.get("_confirmed"):
        # 破坏性操作：先把「要用户点确认」这件事回给模型和前端，确认后带 _confirmed 重调才真做。
        # summary 是那条数据的原文摘要，直接进确认弹窗——不能让人对着「这条内容」盲点确定。
        summary = ""
        if t.get("preview"):
            try:
                summary = t["preview"](args, db) or ""
            except Exception:
                log.warning("确认预览生成失败：%s", name, exc_info=True)
        ask = ("「%s」是删除类操作，需要用户确认后才能执行。请向用户复述将删除的内容并等待确认。"
               if t["kind"] == "destructive" else
               "「%s」要用户点头才生效。请向用户说清你打算做的是哪一件事，然后停下等他确认。")
        return (ask % name,
                {"type": "confirm", "tool": name, "args": args, "kind": t["kind"],
                 "label": tool_label(name), "summary": summary})
    return t["handler"](args, db)


# ---------------------------------------------------------------- 小工具
def _snip(s, n=80):
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _like(kw):
    return "%" + kw.strip() + "%"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _j(obj):
    return json.dumps(obj, ensure_ascii=False)


# ================================================================ 通用 / 总览
@tool("get_user_overview",
      "查当前用户在本应用里的个人数据总览（收录多少、错题多少、连续学习多少天等）。"
      "用户问「我攒了多少/我的进度/帮我看看我的数据」这类总体情况时调用。只查自己的。",
      {"type": "object", "properties": {}}, kind="read")
def _t_overview(args, db):
    u = uid()
    def one(sql, p=()):
        return db.execute(sql, (u,) + p).fetchone()[0]
    ent = [dict(word=r[0], n=r[1]) for r in db.execute(
        "SELECT category, COUNT(*) FROM entries WHERE user_id=? GROUP BY category", (u,))]
    out = {
        "收录成语词语": sum(r["n"] for r in ent), "按类别": {r["word"]: r["n"] for r in ent},
        "收录已收藏": one("SELECT COUNT(*) FROM entries WHERE user_id=? AND starred=1"),
        "错题本": one("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?"),
        "小记": one("SELECT COUNT(*) FROM notes WHERE user_id=?"),
        "知识库文档": one("SELECT COUNT(*) FROM kb_nodes WHERE user_id=? AND type='doc'"),
        "资料库文件": one("SELECT COUNT(*) FROM materials WHERE user_id=?"),
        "收藏古诗文": one("SELECT COUNT(*) FROM classic_stars WHERE user_id=?"),
        "书签": one("SELECT COUNT(*) FROM bookmarks WHERE user_id=?"),
    }
    out.update(_study_stats(db, u))  # streak / total
    return _j(out), None


@tool("get_library_stats",
      "查本应用各内容库的总量（古诗文/成语/词语/常识/常考/时政/党建词典等，全体用户共享的库，"
      "不是某个用户的收录）。用户问「这个应用有多少古诗文/成语库多大/收了多少常识」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_library(args, db):
    def c(sql):
        try:
            return db.execute(sql).fetchone()[0]
        except Exception:
            return None
    cls = {r[0]: r[1] for r in db.execute("SELECT category, COUNT(*) FROM classics GROUP BY category")}
    return _j({
        "古诗文库": {"总数": sum(cls.values()), "按类别": cls},
        "成语库": c("SELECT COUNT(*) FROM ref_idiom"),
        "词语库": c("SELECT COUNT(*) FROM ref_ci"),
        "常识条目": c("SELECT COUNT(*) FROM changshi_items"),
        "常考条目": c("SELECT COUNT(*) FROM changkao_items"),
        "党建理论学习词典": c("SELECT COUNT(*) FROM party_dict"),
        "时政要文库": c("SELECT COUNT(*) FROM policy_docs"),
        "每日时政": c("SELECT COUNT(*) FROM news_items"),
        "新闻视频": c("SELECT COUNT(*) FROM video_items"),
    }), None


@tool("lookup_word",
      "查一个成语/词语/词组的词典释义（拼音、释义、出处、例句），只查不入库。"
      "用户问「XX 是什么意思/解释一下 XX」时调用；若用户要「收录/记下」才另用 add_word。",
      {"type": "object", "properties": {
          "word": {"type": "string", "description": "要查的词，如「筚路蓝缕」"}},
          "required": ["word"]}, kind="read")
def _t_lookup(args, db):
    w = (args.get("word") or "").strip()
    if not w:
        return "没给要查的词。", None
    info = lookup(w)
    if not (info.get("explanation") or "").strip():
        return _j({"word": w, "found": False,
                   "note": "词典里查不到释义。若要收录并让 AI 生成释义，请用 add_word。"}), None
    return _j({k: info.get(k) for k in
               ("word", "pinyin", "category", "explanation", "derivation", "example", "source")}), None


@tool("global_search",
      "在用户的个人数据里跨库搜关键词：成语收录、错题本、小记，以及古诗文库、常识库、时政。"
      "用户说「找一下…/我之前收/记过…吗/哪里有讲…」而不确定在哪个功能时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "搜索关键词"}},
          "required": ["keyword"]}, kind="read")
def _t_global(args, db):
    kw = (args.get("keyword") or "").strip()
    if not kw:
        return "没给关键词。", None
    u, lk = uid(), _like(args["keyword"])
    res = {}
    r = db.execute("SELECT word, explanation FROM entries WHERE user_id=? AND "
                   "(word LIKE ? OR explanation LIKE ?) LIMIT 5", (u, lk, lk)).fetchall()
    if r:
        res["我的成语收录"] = [{"word": x[0], "释义": _snip(x[1], 40)} for x in r]
    r = db.execute("SELECT id, board, question FROM wrong_questions WHERE user_id=? AND "
                   "question LIKE ? LIMIT 5", (u, lk)).fetchall()
    if r:
        res["我的错题"] = [{"id": x[0], "板块": x[1], "题": _snip(x[2], 50)} for x in r]
    r = db.execute("SELECT id, content FROM notes WHERE user_id=? AND content LIKE ? LIMIT 5",
                   (u, lk)).fetchall()
    if r:
        res["我的小记"] = [{"id": x[0], "内容": _snip(x[1], 50)} for x in r]
    r = db.execute("SELECT id, title, author FROM classics WHERE title LIKE ? OR author LIKE ? "
                   "OR content LIKE ? LIMIT 5", (lk, lk, lk)).fetchall()
    if r:
        res["古诗文库"] = [{"id": x[0], "题": x[1], "作者": x[2]} for x in r]
    r = db.execute("SELECT id, title, board FROM changshi_items WHERE title LIKE ? OR content LIKE ? "
                   "LIMIT 5", (lk, lk)).fetchall()
    if r:
        res["常识库"] = [{"id": x[0], "标题": x[1], "板块": x[2]} for x in r]
    r = db.execute("SELECT id, title FROM news_items WHERE title LIKE ? OR content LIKE ? "
                   "ORDER BY created_at DESC LIMIT 5", (lk, lk)).fetchall()
    if r:
        res["时政"] = [{"id": x[0], "标题": _snip(x[1], 50)} for x in r]
    return _j(res or {"结果": "没找到相关内容"}), None


# ================================================================ 成语词语积累
@tool("list_words",
      "列出/筛选用户在「成语词语积累」里收录的词。用户问「我收录了哪些…/我收藏的词有哪些/"
      "我有没有收过 XX」时调用。",
      {"type": "object", "properties": {
          "category": {"type": "string", "enum": ["成语", "词语", "词组"], "description": "按类别筛，可空"},
          "starred": {"type": "boolean", "description": "只看已收藏，可空"},
          "keyword": {"type": "string", "description": "词或释义里的关键词，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 20"}},
       }, kind="read")
def _t_list_words(args, db):
    sql = "SELECT id, word, category, starred, explanation FROM entries WHERE user_id=?"
    p = [uid()]
    if args.get("category"):
        sql += " AND category=?"; p.append(args["category"])
    if args.get("starred"):
        sql += " AND starred=1"
    if args.get("keyword"):
        sql += " AND (word LIKE ? OR explanation LIKE ?)"; p += [_like(args["keyword"])] * 2
    sql += " ORDER BY created_at DESC LIMIT ?"; p.append(min(int(args.get("limit") or 20), 50))
    rows = [{"id": r[0], "word": r[1], "类别": r[2], "收藏": bool(r[3]), "释义": _snip(r[4], 40)}
            for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ================================================================ 错题本
@tool("list_wrong_questions",
      "查用户错题本里的题目，可按板块/题型/关键词筛。用户问「我 XX 的错题有哪些/有几道/"
      "还有哪些错题没补解析」时调用。",
      {"type": "object", "properties": {
          "board": {"type": "string", "description": "板块，如「资料分析」「言语理解与表达」，可空"},
          "qtype": {"type": "string", "description": "题型关键词，可空"},
          "keyword": {"type": "string", "description": "题干关键词，可空"},
          "limit": {"type": "integer", "description": "最多返回几道，默认 10"}},
       }, kind="read")
def _t_list_wq(args, db):
    sql = "SELECT id, board, qtype, answer, question, method FROM wrong_questions WHERE user_id=?"
    p = [uid()]
    if args.get("board"):
        sql += " AND board LIKE ?"; p.append(_like(args["board"]))
    if args.get("qtype"):
        sql += " AND qtype LIKE ?"; p.append(_like(args["qtype"]))
    if args.get("keyword"):
        sql += " AND question LIKE ?"; p.append(_like(args["keyword"]))
    sql += " ORDER BY created_at DESC LIMIT ?"; p.append(min(int(args.get("limit") or 10), 30))
    rows = [{"id": r[0], "板块": r[1], "题型": r[2], "答案": r[3],
             "题干": _snip(r[4], 60), "有解析": bool((r[5] or "").strip())}
            for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ================================================================ 小记
@tool("list_notes",
      "查/搜用户的「小记」笔记。用户问「我小记里记过 XX 吗/我最近记了些什么」时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "内容关键词，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 10"}},
       }, kind="read")
def _t_list_notes(args, db):
    sql = "SELECT id, content, tags, created_at FROM notes WHERE user_id=?"
    p = [uid()]
    if args.get("keyword"):
        sql += " AND content LIKE ?"; p.append(_like(args["keyword"]))
    sql += " ORDER BY created_at DESC LIMIT ?"; p.append(min(int(args.get("limit") or 10), 30))
    rows = [{"id": r[0], "内容": _snip(r[1], 70), "标签": r[2], "时间": r[3]}
            for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ================================================================ 今日复习
@tool("get_today_review",
      "查用户今天需要复习的内容（间隔复习到期项），按类别给出数量。用户问「今天要复习什么/"
      "我有多少要复习的」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_review(args, db):
    from mods.review import _review_due  # 复用应用自身的到期判定，避免口径不一
    due = _review_due(db, uid(), _today())
    by = {}
    for it in due:
        by[it.get("kind") or "其他"] = by.get(it.get("kind") or "其他", 0) + 1
    return _j({"今日待复习总数": len(due), "按类别": by,
               "提示": "在「今日复习」页可逐项过。可用 open_feature 打开。"}), None


# ================================================================ 每日任务
@tool("get_daily_tasks",
      "查用户今天的每日任务清单及完成情况。用户问「我今天的任务/还有什么没做/今天打卡了吗」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_tasks(args, db):
    u, today = uid(), _today()
    tpls = db.execute("SELECT id, text FROM task_templates WHERE user_id=? AND active=1 ORDER BY sort, id",
                      (u,)).fetchall()
    done = {r[0] for r in db.execute("SELECT tpl_id FROM task_done WHERE user_id=? AND date=?", (u, today))}
    items = [{"id": t[0], "任务": t[1], "已完成": t[0] in done} for t in tpls]
    return _j({"date": today, "已完成": len(done), "总数": len(tpls), "items": items}), None


# ================================================================ 备考计划
@tool("get_plan_today",
      "查用户今天的备考规划任务（自动排好的学习计划）。用户问「今天计划学什么/今天要刷哪些」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_plan_today(args, db):
    rows = db.execute("SELECT id, title, module, minutes, done FROM plan_items WHERE user_id=? AND date=? "
                      "ORDER BY seq, id", (uid(), _today())).fetchall()
    items = [{"id": r[0], "内容": r[1], "模块": r[2], "分钟": r[3], "已完成": bool(r[4])} for r in rows]
    return _j({"date": _today(), "items": items,
               "已完成": sum(1 for r in rows if r[4]), "总数": len(rows)}), None


@tool("get_plan_progress",
      "查用户的备考进度：连续学习天数、累计学习天数、最近几天的计划完成情况。"
      "用户问「我坚持多少天了/我最近学得怎么样/我的进度」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_plan_progress(args, db):
    u = uid()
    st = _study_stats(db, u)
    logs = [{"日期": r[0], "完成": "%s/%s" % (r[1], r[2]), "分钟": r[3]} for r in db.execute(
        "SELECT date, done_n, total, minutes_total FROM plan_log WHERE user_id=? "
        "ORDER BY date DESC LIMIT 7", (u,))]
    return _j({"连续学习天数": st["streak"], "累计学习天数": st["total"], "最近计划": logs}), None


# ================================================================ 应用文素材库
@tool("search_yy",
      "查应用文（贯彻执行题）素材库：按**文种 + 结构部件**取骨架、规范表述、格式错例等。"
      "用户问「简报的开头怎么写／写通知有哪些常见错误／汇报要有哪几块／"
      "『一是二是』能不能用」这类**应用文格式**问题时调用。"
      "注意：文种带真题频次（freq），可以据此回答「这个文种值不值得练」。",
      {"type": "object", "properties": {
          "doctype": {"type": "string", "description": "文种，如 简报／汇报／经验交流材料／公开信，可空"},
          "part": {"type": "string", "description": "结构部件，如 标题／称谓／开头·缘由／主体·举措／落款，可空"},
          "kind": {"type": "string",
                   "enum": ["骨架", "表述", "情景", "要点", "得体", "错例", "要求", "范文"],
                   "description": "素材类型，可空。目前库里主要是「错例」"},
          "keyword": {"type": "string", "description": "内容关键词，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 8"}},
       }, kind="read")
def _t_yy(args, db):
    from mods.gongwen import GW_MAP, parts_of
    dt = (args.get("doctype") or "").strip()
    out = {}
    if dt and dt in GW_MAP:
        g = GW_MAP[dt]
        # 先把这个文种的「该长什么样」交代清楚——用户问格式，这才是正面回答；
        # 素材条目是佐证。freq 一并给：能据此说「这个文种近五年考过几次」。
        out["文种"] = {
            "名称": dt, "说明": g["d"], "格式骨架": g["fmt"],
            "字数": "%d~%d 字" % (g["min"], g["max"]),
            "真题频次": "2018 年起考过 %d 次（全部年份 %d 次）" % (
                g.get("freq", 0), g.get("freq_all", 0)),
            "部件": ["%s%s" % (p, "（必需）" if r else "") for p, r in parts_of(dt)],
            "依据": "部件清单有真题参考答案支撑" if g.get("parts_src") == "real"
                    else "部件清单是先验设定，真题样本还不够（n<3），仅供参考",
        }
    sql, p = "SELECT kind, doctype, part, title, text, note FROM yy_items WHERE 1=1", []
    for col, key in (("doctype", "doctype"), ("part", "part"), ("kind", "kind")):
        if args.get(key):
            sql += " AND %s=?" % col
            p.append(args[key].strip())
    if args.get("keyword"):
        sql += " AND (title LIKE ? OR text LIKE ? OR note LIKE ?)"
        p += [_like(args["keyword"])] * 3
    sql += " ORDER BY freq DESC, id LIMIT ?"
    p.append(min(int(args.get("limit") or 8), 20))
    items = []
    for r in db.execute(sql, p):
        it = {"类型": r[0], "文种": r[1] or "通用", "部件": r[2] or ""}
        if r[0] in ("错例", "得体"):             # 都是成对的，摊开才说得清
            try:
                d = json.loads(r[4] or "{}")
                if r[0] == "错例":
                    it["错误写法"], it["正确写法"] = d.get("bad", ""), d.get("good", "")
                else:
                    it["该这么写"], it["不能这么写"] = d.get("do", ""), d.get("dont", "")
            except Exception:
                it["内容"] = _snip(r[4], 100)
        else:
            it["内容"] = _snip(r[4], 120)
        if r[5]:
            it["为什么"] = _snip(r[5], 110)
        items.append(it)
    out["count"] = len(items)
    out["items"] = items
    if not items and not out.get("文种"):
        out["提示"] = "素材库里没有匹配的条目。库目前只有「错例」一类，其余类型还没灌。"
    return _j(out), None


# ================================================================ 写作素材
@tool("search_sucai",
      "在每日写作素材库里搜（人物事例、理论论据、衔接表达等），供申论/作文用。"
      "用户问「有没有关于 XX 的素材/给我几个 XX 的例子/找个万能句式」时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "主题或内容关键词，可空"},
          "kind": {"type": "string", "enum": ["人物事例", "具体事例", "理论论据", "衔接表达"],
                   "description": "素材类型，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 8"}},
       }, kind="read")
def _t_sucai(args, db):
    sql = "SELECT kind, topic, content, example FROM sucai_items WHERE 1=1"
    p = []
    if args.get("kind"):
        sql += " AND kind=?"; p.append(args["kind"])
    if args.get("keyword"):
        sql += " AND (topic LIKE ? OR content LIKE ?)"; p += [_like(args["keyword"])] * 2
    sql += " ORDER BY date DESC LIMIT ?"; p.append(min(int(args.get("limit") or 8), 20))
    rows = [{"类型": r[0], "主题": r[1], "内容": _snip(r[2], 100),
             "例句": _snip(r[3], 60) if r[3] else ""} for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ================================================================ 书签
@tool("list_bookmarks",
      "列出用户的书签（各功能里「看到哪了」的记录和手动打点）。用户问「我上次看到哪了/我的书签」时调用。",
      {"type": "object", "properties": {
          "limit": {"type": "integer", "description": "最多返回几条，默认 15"}},
       }, kind="read")
def _t_bookmarks(args, db):
    rows = db.execute("SELECT kind, title, note, updated_at FROM bookmarks WHERE user_id=? "
                      "ORDER BY updated_at DESC LIMIT ?",
                      (uid(), min(int(args.get("limit") or 15), 40))).fetchall()
    items = [{"类型": r[0], "标题": _snip(r[1], 40), "备注": r[2], "时间": r[3]} for r in rows]
    return _j({"count": len(items), "items": items}), None


# ================================================================ 时政 / 古诗文 / 常识（全局库）
@tool("get_daily_news",
      "查最新的每日时政新闻（含 AI 摘要）。用户问「今天有什么时政/最近的新闻/给我几条时政」时调用。",
      {"type": "object", "properties": {
          "limit": {"type": "integer", "description": "最多返回几条，默认 8"}},
       }, kind="read")
def _t_news(args, db):
    rows = db.execute("SELECT title, source, pub_date, ai_summary FROM news_items "
                      "ORDER BY COALESCE(pub_date,'') DESC, created_at DESC LIMIT ?",
                      (min(int(args.get("limit") or 8), 20),)).fetchall()
    items = [{"标题": r[0], "来源": r[1], "日期": r[2], "摘要": _snip(r[3], 80)} for r in rows]
    return _j({"count": len(items), "items": items}), None


@tool("search_classics",
      "在古诗文名句库里搜（按题目/作者/朝代/正文关键词）。用户问「有没有 XX 的诗/写 XX 的名句/"
      "XX 那首诗」时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "题目、作者、朝代或正文关键词"},
          "category": {"type": "string", "description": "类别筛选（如 诗/词/文言文），可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 8"}},
          "required": ["keyword"]}, kind="read")
def _t_classics(args, db):
    kw = (args.get("keyword") or "").strip()
    if not kw:
        return "没给关键词。", None
    lk = _like(kw)
    sql = ("SELECT id, category, title, author, dynasty, content FROM classics "
           "WHERE (title LIKE ? OR author LIKE ? OR dynasty LIKE ? OR content LIKE ?)")
    p = [lk, lk, lk, lk]
    if args.get("category"):
        sql += " AND category=?"; p.append(args["category"])
    sql += " ORDER BY freq DESC, id LIMIT ?"; p.append(min(int(args.get("limit") or 8), 20))
    rows = [{"id": r[0], "类别": r[1], "题目": r[2], "作者": r[3], "朝代": r[4],
             "正文": _snip(r[5], 60)} for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


@tool("search_changshi",
      "在常识积累库里搜（政治/科技/历史/地理等常识条目）。用户问「有没有讲 XX 的常识/关于 XX 的知识点」时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "标题、主题或内容关键词"},
          "board": {"type": "string", "description": "板块筛选，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 8"}},
          "required": ["keyword"]}, kind="read")
def _t_changshi(args, db):
    kw = (args.get("keyword") or "").strip()
    if not kw:
        return "没给关键词。", None
    lk = _like(kw)
    sql = ("SELECT id, board, topic, title, content FROM changshi_items "
           "WHERE (title LIKE ? OR topic LIKE ? OR content LIKE ?)")
    p = [lk, lk, lk]
    if args.get("board"):
        sql += " AND board LIKE ?"; p.append(_like(args["board"]))
    sql += " ORDER BY date DESC, id DESC LIMIT ?"; p.append(min(int(args.get("limit") or 8), 20))
    rows = [{"id": r[0], "板块": r[1], "主题": r[2], "标题": r[3], "内容": _snip(r[4], 70)}
            for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ================================================================ 资料库 / 知识库
@tool("list_materials",
      "列出/筛选用户资料库里的文件。用户问「我资料库里有什么/我传过 XX 的资料吗」时调用。",
      {"type": "object", "properties": {
          "board": {"type": "string", "description": "板块筛选，可空"},
          "keyword": {"type": "string", "description": "文件名关键词，可空"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 15"}},
       }, kind="read")
def _t_materials(args, db):
    sql = "SELECT id, title, board, ext, size FROM materials WHERE user_id=?"
    p = [uid()]
    if args.get("board"):
        sql += " AND board LIKE ?"; p.append(_like(args["board"]))
    if args.get("keyword"):
        sql += " AND (title LIKE ? OR orig_name LIKE ?)"; p += [_like(args["keyword"])] * 2
    sql += " ORDER BY created_at DESC LIMIT ?"; p.append(min(int(args.get("limit") or 15), 40))
    rows = [{"id": r[0], "标题": r[1], "板块": r[2], "格式": r[3], "字节": r[4]}
            for r in db.execute(sql, p)]
    return _j({"count": len(rows), "items": rows}), None


# ---- 项目资料 ----------------------------------------------------------------
# 挂在「项目」上的参考资料（评分标准、讲义、真题卷）。跟对话附件的分界要说死：
#   对话附件 = 这一轮临时给的，只有那个对话看得见；
#   项目资料 = 挂在项目上的，项目下**每一个对话**都能随时读 —— 也就是这两个工具。
# 每轮注入的只是清单 + 前一段（见 aisession._project_files），后面的靠它们按需取，
# 否则一本几十万字的讲义要么塞爆上下文、要么被无声截掉半本。
PROJ_PART = 6000        # 按段读时一段给多少字
PROJ_OCR_MAX = 3        # 一次现场 OCR 最多几页
# 现场 OCR 的时间闸。实测这台机器**稳态**一页 4~5 秒，但**冷的时候**（tesseract 头一次
# 加载 chi_sim 模型）量到过一页 100 秒以上 —— 一轮对话的总预算只有 100 秒（agent.AI_BUDGET），
# 光靠"最多几页"根本挡不住：页数是常数，耗时不是。所以两道闸都要，谁先到听谁的。
PROJ_OCR_SECONDS = 25


def _proj_file_row(db, fid):
    """按 id 取一份项目资料。限本人；在项目对话里再限本项目 —— 别让 A 项目的对话
    读到 B 项目的资料（同一个人，不是安全问题，但会答得驴唇不对马嘴）。"""
    sql = "SELECT * FROM ai_project_files WHERE id=? AND user_id=?"
    a = [fid, uid()]
    cur = cur_project()
    if cur:
        sql += " AND project_id=?"
        a.append(cur)
    return db.execute(sql, a).fetchone()


def cur_project():
    """当前对话属于哪个项目（aisession._build 挂在 g 上）。拿不到就返回 0 = 不限。"""
    try:
        from flask import g
        return int(getattr(g, "ai_project_id", 0) or 0)
    except Exception:
        return 0


@tool("list_project_files",
      ("列出**当前项目**挂着的参考资料（项目下所有对话共享的那些文件）。"
       "用户说「我挂的资料/项目里的讲义/传上去的那份文件」时用它拿 id，再用 read_project_file 读。"),
      {"type": "object", "properties": {}}, kind="read")
def _t_list_proj_files(args, db):
    cur = cur_project()
    sql = ("SELECT f.id, f.name, LENGTH(f.text) n, COALESCE(f.pages,0) pages, "
           "COALESCE(f.ocr_pages,0) ocr, p.name pname FROM ai_project_files f "
           "LEFT JOIN ai_projects p ON p.id=f.project_id WHERE f.user_id=?")
    a = [uid()]
    if cur:
        sql += " AND f.project_id=?"
        a.append(cur)
    rows = db.execute(sql + " ORDER BY f.id", a).fetchall()
    if not rows:
        return ("这个项目还没挂参考资料。" if cur else
                "用户还没有在任何项目里挂参考资料（项目设置里可以传文件）。"), None
    items = [{"id": r["id"], "名字": r["name"], "字数": r["n"],
              "页数": r["pages"] or None, "只识别到第几页": r["ocr"] or None,
              "项目": None if cur else r["pname"]} for r in rows]
    return _j({"count": len(items), "items": items,
               "提示": "用 read_project_file(id=…) 读正文，别凭名字猜内容"}), None


@tool("read_project_file",
      ("读项目参考资料的正文。先用 list_project_files 拿 id（每轮的系统提示里也带着 id）。\n"
       "· 不给 part 就从头读，一次给一段，末尾会告诉你还有几段；\n"
       "· 给 keyword 就直接定位到出现那个词的地方（找某条评分标准、某道题时优先用它）；\n"
       "· 扫描件超出已识别页数的部分，给 page=页码 现场识别（慢，一次最多几页）。"),
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "资料 id"},
          "part": {"type": "integer", "description": "第几段（1 起），默认 1"},
          "keyword": {"type": "string", "description": "要找的词，给了就按它定位"},
          "page": {"type": "integer", "description": "PDF 页码；只在这份是扫描件、"
                                                     "且这一页超出已识别范围时才需要"}},
          "required": ["id"]}, kind="read")
def _t_read_proj_file(args, db):
    try:
        fid = int(args.get("id") or 0)
    except (TypeError, ValueError):
        return "id 得是数字。", None
    r = _proj_file_row(db, fid)
    if not r:
        return "没有 id=%s 这份项目资料（用 list_project_files 看看有哪些）。" % fid, None
    name, text = r["name"] or "资料", r["text"] or ""
    page = args.get("page")
    if page:
        return _proj_page(r, page), None
    kw = (args.get("keyword") or "").strip()
    if kw:
        hits = _proj_hits(text, kw)
        if not hits:
            return ("《%s》里没有出现「%s」（全文 %d 字，已经全文找过了 —— "
                    "不要因此说「资料里可能有」）。" % (name, kw, len(text))), None
        return "【%s：命中「%s」%d 处】\n%s" % (name, kw, len(hits), "\n…\n".join(hits)), None
    parts = max(1, (len(text) + PROJ_PART - 1) // PROJ_PART)
    try:
        part = max(1, int(args.get("part") or 1))
    except (TypeError, ValueError):
        part = 1
    if part > parts:
        return "《%s》只有 %d 段，没有第 %d 段。" % (name, parts, part), None
    seg = text[(part - 1) * PROJ_PART: part * PROJ_PART]
    head = "【%s：第 %d/%d 段】" % (name, part, parts)
    if part < parts:
        head += "（后面还有 %d 段，需要就用 part=%d 接着读）" % (parts - part, part + 1)
    elif r["ocr_pages"]:
        head += "（这是扫描件，入库时只识别到第 %d 页；更后面的页用 page=页码 现场识别）" % r["ocr_pages"]
    return head + "\n" + seg, None


def _proj_hits(text, kw, span=400, limit=3):
    """关键词命中处的上下文。给 limit 处就够了 —— 再多模型也只会挑着看，
    还把上下文挤没了。"""
    out, start = [], 0
    low, lkw = text.lower(), kw.lower()
    while len(out) < limit:
        i = low.find(lkw, start)
        if i < 0:
            break
        out.append(text[max(0, i - span): i + len(kw) + span])
        start = i + len(kw) + span
    return out


def _proj_page(r, page):
    """现场识别扫描件的某一页（及其后几页）。原件还在盘上才做得到 —— 这正是
    上传时要留原件的理由。"""
    import os
    from core import AI_PROJ_DIR
    from mods.files import _ocr_image_page
    try:
        page = int(page)
    except (TypeError, ValueError):
        return "page 得是数字。"
    if not (r["stored_name"] or "") or (r["ext"] or "").lower() != ".pdf":
        return "《%s》不是 PDF 原件，按页识别对它不适用（用 part 按段读就行）。" % (r["name"] or "资料")
    # 页码先判、文件后判：「这份只有 10 页」是模型该马上知道的事，
    # 别让它先撞上一句「原件不在磁盘上」然后换个页码再试一遍。
    total = int(r["pages"] or 0)
    if total and (page < 1 or page > total):
        return "《%s》一共 %d 页，没有第 %d 页。" % (r["name"] or "资料", total, page)
    path = os.path.join(AI_PROJ_DIR, str(uid()), os.path.basename(r["stored_name"]))
    if not os.path.exists(path):
        return "《%s》的原件已经不在磁盘上了，只能读已入库的正文（用 part 按段读）。" % (r["name"] or "资料")
    import tempfile
    import time
    out, last, t0 = [], page, time.time()
    tmp = tempfile.mkdtemp(prefix="aipf_")
    try:
        for p in range(page, page + PROJ_OCR_MAX):
            if total and p > total:
                break
            if out and time.time() - t0 > PROJ_OCR_SECONDS:
                break                        # 已经有货了就先交差，别把这一轮拖死
            t = (_ocr_image_page(path, p, tmp) or "").strip()
            last = p
            if t:
                out.append("【第 %d 页】\n%s" % (p, t))
    except Exception as e:
        log.warning("项目资料按页识别失败：%r", e)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    if not out:
        return "第 %d 页没识别出文字（可能是纯图形页）。" % page
    tail = ""
    if not total or last < total:
        tail = "\n（识别到第 %d 页；还要后面的就再给一次 page=%d）" % (last, last + 1)
    return "【%s：现场识别】\n%s%s" % (r["name"] or "资料", "\n\n".join(out), tail)


@tool("search_kb",
      "在用户的知识库文档里搜（标题/正文关键词）。用户问「我知识库里写过 XX 吗/找我那篇讲 XX 的文档」时调用。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "标题或正文关键词"},
          "limit": {"type": "integer", "description": "最多返回几条，默认 10"}},
          "required": ["keyword"]}, kind="read")
def _t_kb(args, db):
    kw = (args.get("keyword") or "").strip()
    if not kw:
        return "没给关键词。", None
    lk = _like(kw)
    rows = db.execute("SELECT id, title, content FROM kb_nodes WHERE user_id=? AND type='doc' "
                      "AND (title LIKE ? OR content LIKE ?) ORDER BY updated_at DESC LIMIT ?",
                      (uid(), lk, lk, min(int(args.get("limit") or 10), 30))).fetchall()
    items = [{"id": r[0], "标题": r[1], "摘录": _snip(r[2], 80)} for r in rows]
    return _j({"count": len(items), "items": items}), None


# ================================================================ 学习统计
@tool("get_study_stats",
      "查用户的刷题与测验统计：刷题总正确率、最近每日测验成绩、连续学习天数。"
      "用户问「我刷题正确率多少/我测验考得怎么样/我的成绩趋势」时调用。",
      {"type": "object", "properties": {}}, kind="read")
def _t_study_stats(args, db):
    u = uid()
    st = _study_stats(db, u)
    dr = db.execute("SELECT COALESCE(SUM(correct),0), COALESCE(SUM(total),0), COUNT(*) "
                    "FROM drill_records WHERE user_id=?", (u,)).fetchone()
    correct, total, sessions = dr[0], dr[1], dr[2]
    rate = round(correct * 100.0 / total, 1) if total else None
    by_board = [{"板块": r[0], "正确率": (round(r[1] * 100.0 / r[2], 1) if r[2] else None), "题数": r[2]}
                for r in db.execute(
                    "SELECT board, SUM(correct), SUM(total) FROM drill_records WHERE user_id=? "
                    "GROUP BY board ORDER BY SUM(total) DESC LIMIT 8", (u,))]
    tests = [{"日期": r[0], "得分": "%s/%s" % (r[1], r[2])} for r in db.execute(
        "SELECT date, score, total FROM dtest_records WHERE user_id=? ORDER BY date DESC LIMIT 7", (u,))]
    return _j({"连续学习天数": st["streak"], "累计学习天数": st["total"],
               "刷题": {"总题数": total, "总正确率": rate, "场次": sessions, "分板块": by_board},
               "最近测验": tests}), None


# ================================================================ 真题库（这个应用最硬的资产）
# AI 以前完全够不着它：问「找几道类似的选词填空」，它只能从错题本和收录里翻。
# 7600 道真题就在库里，不给它反而要它凭印象编题 —— 那正是最该避免的事。

@tool("search_real_questions",
      ("在**历年真题库**里找题（7000+ 道，按模块/题型/关键词）。用户说「找几道…真题」"
       "「有没有考过…」「来道类似的」时用它。\n"
       "**别自己编题**：这个库里有真题就用真题，编出来的题会把用户练坏。"),
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "题干关键词，如「不负众望」「基尼系数」；不限就留空"},
          "module": {"type": "string",
                     "description": "模块：言语理解与表达 / 判断推理 / 常识判断 / 资料分析 / 数量关系"},
          "qtype": {"type": "string", "description": "题型，如「逻辑填空」「图形推理」，不确定就留空"},
          "limit": {"type": "integer", "description": "最多几道，默认 5，上限 10"}}}, kind="read")
def _t_search_real(args, db):
    kw = (args.get("keyword") or "").strip()
    mod = (args.get("module") or "").strip()
    qt = (args.get("qtype") or "").strip()
    n = max(1, min(int(args.get("limit") or 5), 10))
    sql = ["SELECT id, module, qtype, stem, options, answer, year_max FROM real_questions WHERE 1=1"]
    a = []
    # needs_asset：脱离图/材料就做不了的题，纯文字聊天里发出去是残的
    sql.append("AND COALESCE(needs_asset,0)=0")
    if kw:
        sql.append("AND (stem LIKE ? ESCAPE '\\' OR options LIKE ? ESCAPE '\\')")
        k = "%" + kw.replace("%", r"\%").replace("_", r"\_") + "%"
        a += [k, k]
    if mod:
        sql.append("AND module LIKE ?")
        a.append("%" + mod + "%")
    if qt:
        sql.append("AND qtype LIKE ?")
        a.append("%" + qt + "%")
    sql.append("ORDER BY COALESCE(year_max,0) DESC, id DESC LIMIT ?")
    a.append(n)
    rows = db.execute(" ".join(sql), a).fetchall()
    if not rows:
        return "真题库里没找到符合条件的题（关键词=%s 模块=%s 题型=%s）。" % (kw or "不限", mod or "不限", qt or "不限"), None
    out = []
    for r in rows:
        out.append({"id": r["id"], "模块": r["module"], "题型": r["qtype"],
                    "题干": (r["stem"] or "")[:400], "选项": (r["options"] or "")[:300],
                    "答案": r["answer"] or "", "年份": r["year_max"]})
    return json.dumps(out, ensure_ascii=False), None


@tool("search_basics",
      ("在**机构讲义的基础知识点**里查（优路/三色两套书的考点大纲和讲解正文）。"
       "用户问某个考点「书上怎么讲的」「有哪些方法」时用它。"),
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "考点关键词，如「工程问题」「削弱论证」"},
          "limit": {"type": "integer", "description": "最多几条，默认 3，上限 6"}},
          "required": ["keyword"]}, kind="read")
def _t_search_basics(args, db):
    kw = (args.get("keyword") or "").strip()
    if not kw:
        return "要给个关键词。", None
    n = max(1, min(int(args.get("limit") or 3), 6))
    k = "%" + kw.replace("%", r"\%").replace("_", r"\_") + "%"
    rows = db.execute(
        "SELECT n.id, n.board, n.source, n.title FROM basic_nodes n "
        "WHERE n.title LIKE ? ESCAPE '\\' ORDER BY n.id LIMIT ?", (k, n)).fetchall()
    if not rows:
        # 标题没命中就翻正文：考点名和书里的说法常常对不上
        rows = db.execute(
            "SELECT n.id, n.board, n.source, n.title FROM basic_nodes n "
            "WHERE EXISTS(SELECT 1 FROM basic_blocks b WHERE b.node_id=n.id "
            "AND b.content_md LIKE ? ESCAPE '\\') ORDER BY n.id LIMIT ?", (k, n)).fetchall()
    if not rows:
        return "讲义里没找到「%s」相关的知识点。" % kw, None
    out = []
    for r in rows:
        blocks = db.execute("SELECT kind, content_md FROM basic_blocks WHERE node_id=? "
                            "ORDER BY sort LIMIT 6", (r["id"],)).fetchall()
        body = "\n".join((b["content_md"] or "")[:400] for b in blocks)[:1200]
        out.append({"id": r["id"], "板块": r["board"], "出处": r["source"],
                    "考点": r["title"], "讲解": body})
    return json.dumps(out, ensure_ascii=False), None


@tool("list_drive",
      "列出用户云盘里的文件（可按关键词筛）。用户问「我云盘里有没有…」时用它。",
      {"type": "object", "properties": {
          "keyword": {"type": "string", "description": "文件名关键词，不限就留空"},
          "limit": {"type": "integer", "description": "最多几条，默认 15，上限 40"}}}, kind="read")
def _t_list_drive(args, db):
    kw = (args.get("keyword") or "").strip()
    n = max(1, min(int(args.get("limit") or 15), 40))
    sql = ("SELECT id, folder, name, ext, size, created_at FROM drive_files "
           "WHERE owner_id=? AND is_dir=0 AND COALESCE(deleted_at,'')=''")
    a = [uid()]
    if kw:
        sql += " AND name LIKE ? ESCAPE '\\'"
        a.append("%" + kw.replace("%", r"\%").replace("_", r"\_") + "%")
    sql += " ORDER BY id DESC LIMIT ?"
    a.append(n)
    rows = db.execute(sql, a).fetchall()
    if not rows:
        return "云盘里没有%s文件。" % ("匹配「%s」的" % kw if kw else ""), None
    return json.dumps([dict(r) for r in rows], ensure_ascii=False), None


@tool("read_drive_file",
      ("读云盘里某个文件的正文（PDF/Word/文本会抽成文字；扫描件会 OCR 前几页）。"
       "先用 list_drive 拿 id。文件很大时只会给开头一部分，**会明确告诉你截到哪**。"),
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "云盘文件 id（来自 list_drive）"}},
          "required": ["id"]}, kind="read")
def _t_read_drive(args, db):
    import os
    from core import UPLOADS
    from mods.files import _pdf_text_or_ocr
    fid = int(args.get("id") or 0)
    r = db.execute("SELECT * FROM drive_files WHERE id=? AND owner_id=? AND is_dir=0 "
                   "AND COALESCE(deleted_at,'')=''", (fid, uid())).fetchone()
    if not r:
        return "云盘里没有这个文件（id=%s）。" % fid, None
    path = os.path.join(UPLOADS, "drive", str(uid()), r["stored_name"] or "")
    if not os.path.exists(path):
        return "这个文件的内容已经不在磁盘上了。", None
    try:
        text = (_pdf_text_or_ocr(path, (r["ext"] or "").lower(), max_pages=20) or "").strip()
    except Exception as e:
        log.warning("读云盘文件失败：%r", e)
        return "读不出这个文件的文字（%s）。" % e, None
    if not text:
        return "这个文件里没抽出文字（可能是纯图片或不支持的格式）。", None
    LIMIT = 20000
    head = "【云盘文件：%s】" % (r["name"] or "")
    if len(text) > LIMIT:
        # 跟附件那条路一个规矩：截断必须留痕，否则模型会拿半截当全文下结论
        head += ("（全文约 %d 字，以下只给前 %d 字，后面还有。需要通读才能回答的问题，"
                 "先说明你只看到了前面一部分）" % (len(text), LIMIT))
    return head + "\n" + text[:LIMIT], None


@tool("get_exam_countdown",
      "查距离用户的考试还有多少天（来自他在「备考计划」里填的考试日期）。",
      {"type": "object", "properties": {}}, kind="read")
def _t_countdown(args, db):
    from datetime import date
    r = db.execute("SELECT exam, exam_date FROM plan_profile WHERE user_id=?", (uid(),)).fetchone()
    if not r or not (r["exam_date"] or "").strip():
        return "用户还没在「备考计划」里填考试日期，所以算不出倒计时（可以建议他去填）。", None
    try:
        y, m, d = [int(x) for x in str(r["exam_date"])[:10].replace("/", "-").split("-")[:3]]
        days = (date(y, m, d) - date.today()).days
    except Exception:
        return "考试日期「%s」看不懂，算不出倒计时。" % r["exam_date"], None
    name = (r["exam"] or "考试").strip() or "考试"
    if days > 0:
        return "距离%s（%s）还有 %d 天。" % (name, r["exam_date"], days), None
    if days == 0:
        return "%s就是今天（%s）。" % (name, r["exam_date"]), None
    return "%s（%s）已经过去 %d 天了。" % (name, r["exam_date"], -days), None


# ================================================================ 联网
# DeepSeek 自己不带联网，所以这两个是我们接的。**分成两个**：只给摘要的话模型照样会
# 顺着摘要编，得让它能真的把正文读回来再说。
# 搜不到 ≠ 连不上：前者是事实（就说没有），后者是这台机器的网络问题（要说清楚，
# 别让用户以为「网上没有这个东西」）。两种都绝不许退回「拿记忆冒充搜索结果」。

@tool("web_search",
      ("上网搜。当问题涉及**你不可能知道的信息**时用它：今天/最近发生的事、"
       "具体的公告与时间、政策原文、某地某年的招考安排。\n"
       "**规矩**：① 搜完必须在回答里说清哪几条来自网络（给标题和链接）；"
       "② 只有摘要不足以下结论时，用 web_fetch 把正文读回来再答；"
       "③ 搜不到就说搜不到，**绝不用你自己的印象顶替搜索结果**。"),
      {"type": "object", "properties": {
          "query": {"type": "string", "description": "搜索词，尽量具体（含地名、年份、机构名）"},
          "count": {"type": "integer", "description": "要几条，默认 5，上限 8"}},
          "required": ["query"]}, kind="read")
def _t_web_search(args, db):
    from mods.websearch import SearchError, search
    q = (args.get("query") or "").strip()
    if not q:
        return "要给个搜索词。", None
    try:
        hits = search(q, args.get("count") or 5)
    except SearchError as e:
        # 把「去不了」原样说给模型，让它转告用户 —— 这不是「网上没有」
        return "没能去搜（%s）。请如实告诉用户这一点，不要用你自己的印象代替搜索结果。" % e, None
    except Exception as e:
        log.warning("联网搜索异常：%r", e)
        return "搜索出错了（%s）。请如实告诉用户，不要拿印象顶替。" % e, None
    if not hits:
        return "搜了「%s」，一条结果也没有。" % q, None
    return json.dumps(hits, ensure_ascii=False), None


@tool("web_fetch",
      ("把某个网页的正文读回来（配合 web_search 用：先搜到链接，再读正文）。"
       "网页很长时只给开头一部分，**会明确告诉你截到哪**。"),
      {"type": "object", "properties": {
          "url": {"type": "string", "description": "http/https 链接，通常来自 web_search 的结果"}},
          "required": ["url"]}, kind="read")
def _t_web_fetch(args, db):
    from mods.websearch import SearchError, fetch
    try:
        title, body, cut = fetch(args.get("url") or "")
    except SearchError as e:
        return "读不了这个网页（%s）。如实告诉用户。" % e, None
    except Exception as e:
        log.warning("读网页异常：%r", e)
        return "读这个网页时出错了（%s）。" % e, None
    if not body.strip():
        return "这个网页没读出正文（可能整页都靠脚本渲染）。", None
    head = "【网页：%s】" % (title or args.get("url"))
    if cut:
        head += "（正文很长，以下只是开头一部分，后面还有）"
    return head + "\n" + body, None
