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
from datetime import datetime

from core import _study_stats, get_db, lookup, uid

# name -> {"spec": {...}, "handler": fn, "kind": str, "confirm": bool}
TOOL_REGISTRY = {}


def tool(name, desc, params, kind="write", confirm=False):
    """把一个工具登记进注册表。

    kind: read（只查）| write（新增，可撤销）| update（改已有）|
          destructive（删除/覆盖，需确认）| navigate（跳前端页）
    confirm: True 时破坏性操作要二次确认——没带 _confirmed 就先回确认请求，不真执行。
    """
    def deco(fn):
        TOOL_REGISTRY[name] = {
            "spec": {"type": "function", "function": {
                "name": name, "description": desc, "parameters": params}},
            "handler": fn, "kind": kind, "confirm": confirm}
        return fn
    return deco


def tool_specs(kinds=None):
    """给模型的 tools 列表。kinds 可传如 ("read",) 只给读工具（一问一答入口用）。"""
    return [t["spec"] for t in TOOL_REGISTRY.values()
            if not kinds or t["kind"] in kinds]


def exec_tool(name, args, db):
    """执行一个工具。返回 (给模型看的结果文本, 给前端的 action | None)。"""
    t = TOOL_REGISTRY.get(name)
    if not t:
        return "未知工具：" + str(name), None
    if t["confirm"] and not args.get("_confirmed"):
        # 破坏性操作：先把「要用户点确认」这件事回给模型和前端，确认后带 _confirmed 重调才真做
        return ("「%s」是删除类操作，需要用户确认后才能执行。请向用户复述将删除的内容并等待确认。" % name,
                {"type": "confirm", "tool": name, "args": args})
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
