"""AI 工具调用：让 AI 真能操作应用（而不只是嘴上说做了）。

原来 AI 只会「嘴上说」帮你做了（比如说「已把成语加入收录」其实没写库）。
给它 function calling：服务端能直接做的（加收录…）就执行；只能前端做的（跳到某功能）
记成一个 action 交回前端执行。这样 AI 说「已加入」就是真的加了。
"""
import json
import re
import time
from datetime import datetime

from flask import jsonify

import aiclient
from core import CFG, CJK_RE, _mark_study, log, lookup, to_pinyin, uid
from mods.agent_tools import (PROJECT_TOOLS, cur_project, exec_tool, tool,
                              tool_label, tool_specs, tool_specs_for)
from mods.ai import _ai_call_or_error


# 对话是**用户盯着屏幕等**的场景，超时口径跟离线脚本（出题/批改，动辄一两分钟）不同。
# 这里有**两个**口径，2026-08 那批超时就是因为拿一个数当两个用（近 14 天 162 次调用里
# 33 次 timeout，elapsed 最大 41.7 秒，正正卡在下面这条线上）：
#
#   AI_FIRST_BYTE  等第一个字节。实测正常 1~3 秒；等更久不是「模型在想」，是这条 TCP
#                  已经死了（代理/路由一抖，连接静默失效，read 只会干等到超时）。
#                  这一段**会被重试放大**（重试只发生在一个字都没吐出去时），所以它才是
#                  需要按尝试次数分摊的那一份。
#   AI_TIMEOUT     已经在吐字之后，两片之间能空多久。这一段不会再重试，给满即可。
#                  实测成功调用最慢 34.5 秒，原来的 40 秒只比它高 16%，稍慢一点就被误杀。
AI_FIRST_BYTE = 12
AI_TIMEOUT = 60
AI_RETRIES = 2
# 一次对话的总预算。工具循环最多 5 次调用，不封顶的话最坏叠成十分钟：
# 手机端早在 Cloudflare 隧道的 100 秒上限处就 524 断了，服务端还在空转占线程。
AI_BUDGET = 100
# 用户手动按了「联网」时的预算：搜一次不够就得再搜、还要把正文读回来，
# 三四次网络往返打底，拿聊天那份 100 秒去套，必然在收尾前就被自己的预算掐断。
AI_WEB_BUDGET = 220

WEB_TOOLS = ("web_search", "web_fetch")

# 按下「联网」意味着**这一轮必须真的去搜**。不把话说死的话，模型会觉得
# 「我知道啊」然后凭印象答 —— 那正是联网按钮最没用的一种失败：用户以为查过了。
WEB_ON_PROMPT = (
    "【用户已开启联网】这一轮**必须先调用 web_search 真的去搜**，再根据搜到的内容回答。\n"
    "· 摘要不足以下结论时，用 web_fetch 把正文读回来再答（尤其是公告、政策原文这类）。\n"
    "· 回答里**必须注明出处**：写清哪几条来自网络，附标题和链接。\n"
    "· 搜不到就直说搜不到，**绝对不许拿你自己的印象冒充搜索结果** —— 用户按这个按钮，"
    "要的就是「真去查过」，编一个看起来对的答案比说搜不到糟得多。")

# DeepSeek 在「它还想调工具、但这一轮没给它 tools」时，会把工具调用**当正文吐出来**：
# 屏幕上是一串 <｜｜DSML｜｜tool_calls>…，真正的答案没了。这就是「联网搜索用不了」的
# 真相 —— 搜是搜到了（trace 里几条 web_search 都有结果），最后那句话被这堆标记顶掉。
# 治本是收尾轮那条硬指令（见下面 ai_chat_agentic_stream 末尾）；这里是兜底。
_TOOL_MARK = re.compile(r"<[｜|]{1,2}\s*(DSML|tool[_▁\s]?calls?|function[_▁\s]?calls?)", re.I)


def _cut_markup(text):
    """从第一个工具调用标记处截断。返回 (可见正文, 是否截到了)。"""
    m = _TOOL_MARK.search(text or "")
    return (text[:m.start()], True) if m else (text, False)


def _collect_hits(bag, result):
    """把 web_search 这一次的命中攒起来（**趁结果还完整**）。

    不从 trace 里取：那份 result 只留 400 字给界面回放，JSON 早断了，解析必然失败——
    兜底会「看起来接了、其实永远是空的」，这是最难发现的一类坏法。
    """
    try:
        hits = json.loads(result or "")
    except Exception:
        return                             # 「没搜着」那类是人话不是 JSON，跳过
    if not isinstance(hits, list):
        return
    for h in hits:
        if isinstance(h, dict) and h.get("url"):
            bag.append(h)


def _fallback_from_hits(hits):
    """收尾那一轮一个字都没说出来时，拿查到的东西自己交代。

    这一步不是锦上添花：模型在收尾轮**还想调工具**的时候（找不到直达链接就反复换词搜
    是常态），正文会被上面那道闸整段挡掉 —— 用户屏幕上就只剩几句「我再查一下」，
    而那几条搜索结果明明是真查到的。宁可给一份朴素的清单，也不能让人对着半句话收场。
    """
    seen, lines = set(), []
    for h in hits or []:
        u = h.get("url") or ""
        if not u or u in seen:
            continue
        seen.add(u)
        lines.append("· [%s](%s)%s" % ((h.get("title") or u)[:80], u,
                                       "\n  " + h["snippet"][:120] if h.get("snippet") else ""))
    if not lines:
        return ""
    return ("\n\n**这一轮查到的来源（我没能把话说完，先把出处给你）：**\n"
            + "\n".join(lines[:8])
            + "\n\n以上是搜索直接给回的结果，链接可以点开核对。")


def _ai_stream(messages, tools=None, temperature=0.4, max_tokens=1600, deadline=None, tier="fast"):
    """一次流式调用，把 aiclient 的事件原样传出来。

    走 aiclient 而不是自己拼 URL：模型名解析、官方改名时的探活自愈，跟全站一套。

    deadline 是这一整轮对话的截止时刻（time.time() 口径）：越到后面留给单次调用的
    时间越短，免得最后一次调用把总预算撑爆。
    """
    timeout, first = AI_TIMEOUT, AI_FIRST_BYTE
    if deadline is not None:
        left = deadline - time.time()
        # **只有首字节那一段按尝试次数分摊**：重试只在一个字都没吐出去时发生，所以
        # 会被乘以三的只有它。以前连「两片之间」也一起除，100 秒预算落到每次调用只剩
        # 33 秒 —— 模型写得稍长就被自己的预算掐死，而真正该早点放弃的死连接反倒等满。
        first = max(4, min(first, left / (AI_RETRIES + 1)))
        timeout = max(5, min(timeout, left))
    return aiclient.stream(messages, tier=tier, temperature=temperature,
                           max_tokens=max_tokens, timeout=timeout, first_byte=first, cfg=CFG,
                           retries=AI_RETRIES, extra={"tools": tools} if tools else None)


# 应用里能让 AI 帮你打开的功能（名字 → 前端的 openXxx 函数）
AI_FEATURES = {
    "成语词语积累": "openIdiom", "每日时政": "openNews", "每日新闻视频": "openVideos",
    "人民时评范文": "openFanwen", "今日复习": "openReview", "常识积累": "openChangshi",
    "错题本": "openWrongq", "小记": "openNotes", "资料库": "openMaterials",
    "古诗文名句": "openClassics", "时政要文库": "openPolicyDocs", "任务清单": "openTasks",
    "党的创新理论学习词典": "openPartyDict", "常考": "openChangkao",
}

def _gen_ai_explanation(db, word, cat=""):
    """词典查不到时，用 AI 生成释义并写进全局 ci_ai 缓存（此后 lookup 直接命中）。
    返回 dict(explanation/derivation/example/category/pinyin)；失败时释义为空串。"""
    cat = (cat or "").strip()
    if cat not in ("成语", "词语", "词组"):
        cat = "词组" if (len(word) >= 4 and CJK_RE.match(word)) else "词语"
    py = to_pinyin(word)
    out = {"explanation": "", "derivation": "", "example": "", "category": cat, "pinyin": py}
    prompt = (
        "请解释%s「%s」，面向公务员考试考生，用简体中文，只输出 JSON（不要多余文字），字段：\n"
        '{"explanation":"准确通顺的释义，一到三句，可含近义辨析",'
        '"derivation":"出处/典故；没有则留空字符串",'
        '"example":"一个规范例句；没有则留空字符串"}') % (cat, word)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是权威的汉语词典与公考词汇助手，释义准确、简洁，严格输出 JSON，用简体中文。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=700, json_mode=True)
    if err:
        return out
    try:
        obj = json.loads(reply)
    except Exception:
        obj = {"explanation": reply, "derivation": "", "example": ""}
    out["explanation"] = (obj.get("explanation") or "").strip()
    out["derivation"] = (obj.get("derivation") or "").strip()
    out["example"] = (obj.get("example") or "").strip()
    if out["explanation"]:
        db.execute("INSERT OR REPLACE INTO ci_ai(word,pinyin,category,explanation,derivation,example) "
                   "VALUES(?,?,?,?,?,?)",
                   (word, py, cat, out["explanation"], out["derivation"], out["example"]))
        db.commit()
    return out


def _ai_add_entry(db, word, note):
    info = lookup(word)
    # AI 收录时若词典查不到释义，先让 AI 生成释义再入库（用户要求：没释义的不能裸收录）
    if not (info.get("explanation") or "").strip():
        gen = _gen_ai_explanation(db, word, info.get("category") or "")
        if gen["explanation"]:
            info["explanation"] = gen["explanation"]
            info["derivation"] = gen["derivation"]
            info["example"] = gen["example"]
            info["category"] = gen["category"]
            info["pinyin"] = info["pinyin"] or gen["pinyin"]
            info["source"] = "ai"
    db.execute(
        "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), word, info["pinyin"], info["category"], info["explanation"],
         info["derivation"], info["example"], note, info["source"]))
    db.commit()
    return bool((info.get("explanation") or "").strip())


@tool("add_word",
      "把一个成语/词语/词组加入用户的「成语词语积累」收录。当用户说「收录/加入/记下这个词」时调用。"
      "**用户只把一个词单独发过来，不算要收录**——那是问「这个词讲讲」；"
      "刚讲完的词他又原样发一次，多半是上一条没送到他手机上，重讲一遍即可，不要理解成要你收录。"
      "没有明确的收录字样就别调这个工具，写库是他看得见的动作。",
      {"type": "object", "properties": {
          "word": {"type": "string", "description": "要收录的成语或词语本身，如「佶屈聱牙」"},
          "note": {"type": "string", "description": "可选备注"}},
          "required": ["word"]}, kind="write")
def _t_add_word(args, db):
    word = (args.get("word") or "").strip()
    if not word:
        return "没有指定要收录的词。", None
    has_exp = _ai_add_entry(db, word, (args.get("note") or "").strip())
    n = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (uid(),)).fetchone()[0]
    tail = "（已附上释义）" if has_exp else "（暂未查到释义，先收录）"
    return ("已把「%s」加入成语词语积累%s，在 行测→言语理解与表达→成语词语积累 里能看到，当前共 %d 条。"
            % (word, tail, n)), {"type": "refresh", "what": "entries", "toast": "已收录到「成语词语积累」"}


@tool("open_feature",
      "帮用户打开应用里的某个功能页面，省得他自己在菜单里找。当用户说「打开/去/进入某功能」时调用。",
      {"type": "object", "properties": {
          "feature": {"type": "string", "enum": list(AI_FEATURES.keys()), "description": "功能名"}},
          "required": ["feature"]}, kind="navigate")
def _t_open_feature(args, db):
    f = (args.get("feature") or "").strip()
    fn = AI_FEATURES.get(f)
    if not fn:
        return "没有这个功能：" + f, None
    return "已为用户打开「%s」。" % f, {"type": "navigate", "fn": fn, "label": f}


@tool("create_note",
      "帮用户在「小记」里记一条笔记。当用户说「帮我记下/记一条/存到小记」时调用。",
      {"type": "object", "properties": {
          "content": {"type": "string", "description": "要记的内容"},
          "tags": {"type": "array", "items": {"type": "string"}, "description": "可选标签"}},
          "required": ["content"]}, kind="write")
def _t_create_note(args, db):
    content = (args.get("content") or "").strip()
    if not content:
        return "没有要记的内容。", None
    tags = [str(t)[:20] for t in (args.get("tags") or [])][:6]
    db.execute(
        "INSERT INTO notes(user_id,board,content,images,attachments,todos,tags) "
        "VALUES(?,?,?,?,?,?,?)",
        (uid(), "", content, "[]", "[]", "[]", json.dumps(tags, ensure_ascii=False)))
    db.commit()
    return "已记进小记。", {"type": "refresh", "what": "notes"}


@tool("add_wrong_question",
      ("把一道**完整的**题目加入用户的「错题本」。当用户发来的（或截图 OCR 出来的）内容"
       "确实是一道完整题目——有题干、通常还有选项——时调用。只有能确定是完整题目才调用；"
       "若拿不准这是不是题目、或题目残缺不全，**不要调用**，而是用文字反问用户确认。"),
      {"type": "object", "properties": {
          "question": {"type": "string", "description": "完整题干（含选项 A/B/C/D，若有）。尽量保留原文。"},
          "answer": {"type": "string", "description": "正确答案（如 C；不确定就留空）"},
          "board": {"type": "string", "description": "所属板块，如「行测·资料分析」「行测·言语理解」「常识判断」，判断不了就留空"},
          "qtype": {"type": "string", "description": "题型，如「资料分析-增长率」「逻辑填空」，判断不了就留空"},
          "analysis": {"type": "string", "description": "解题方法/思路/易错点（可选，简要写）"}},
          "required": ["question"]}, kind="write")
def _t_add_wq(args, db):
    q = (args.get("question") or "").strip()
    if not q:
        return "没拿到题目内容。", None
    db.execute(
        "INSERT INTO wrong_questions(user_id,board,question,image,answer,qtype,points,method,skill,steps) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid(), (args.get("board") or "").strip(), q, "", (args.get("answer") or "").strip(),
         (args.get("qtype") or "").strip(), "", (args.get("analysis") or "").strip(), "", ""))
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=?", (uid(),)).fetchone()[0]
    return ("已把这道题加入错题本（当前共 %d 道），在「错题本」里能看到并继续补充答案/解析。" % n,
            {"type": "refresh", "what": "wrongq", "toast": "已加入错题本 📓"})


def _pv_remember(args, db):
    """确认弹窗里给用户看的：**原样**是这一句要被长期记住。
    记忆是要跟着他每一轮对话走的，不能让人对着「确认记住？」盲点。"""
    return (args.get("text") or "").strip()[:150]


@tool("remember_fact",
      ("把一件**关于这位用户的长期事实**记进长期记忆——之后每一轮对话都会自动带上。"
       "当用户在聊天里透露了这类稳定信息时主动调用：考哪个岗位/哪场考试、考试时间、"
       "长期的弱项与目标、他要求你以后怎么答（比如「解析写详细点」）。\n"
       "**别记这些**：① 能查出来的数字（错题多少道、连续学习多少天——那些每次用查询工具现算，"
       "记下来只会过期）；② 只在这一轮有用的话；③ 你自己的猜测。\n"
       "一次只记一件事，写成一句完整的话（最多 200 字）。系统会让用户点头确认，他不点就不会记。"),
      {"type": "object", "properties": {
          "text": {"type": "string", "description": "要长期记住的那一句话，例如「目标是四川省考，2026 年 3 月笔试」"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认后才填 true；首次调用不要填，让系统先要确认"}},
          "required": ["text"]}, kind="write", confirm=True, preview=_pv_remember)
def _t_remember(args, db):
    text = (args.get("text") or "").strip()[:200]
    if not text:
        return "没给要记住的内容。", None
    u = uid()
    if db.execute("SELECT 1 FROM ai_memories WHERE user_id=? AND text=?", (u, text)).fetchone():
        return "这件事已经记过了，没重复记：%s" % text, None
    now = datetime.now()
    db.execute("INSERT INTO ai_memories(user_id,kind,text,source) VALUES(?,?,?,?)",
               (u, "fact", text, "AI 从 %d 月 %d 日的对话里记下" % (now.month, now.day)))
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM ai_memories WHERE user_id=?", (u,)).fetchone()[0]
    return ("已记住：%s（共 %d 条长期记忆，用户随时能在「AI 记住的事」里看到并删掉）" % (text, n),
            {"type": "refresh", "what": "memories", "toast": "已记住 🧠"})


# ================================================================ 改 / 完成类（update）
@tool("update_wrong_question",
      "补充或修改错题本里某道题的答案、板块、题型、解析。先用 list_wrong_questions 拿到题目 id 再调。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "错题 id（来自 list_wrong_questions）"},
          "answer": {"type": "string", "description": "正确答案，可空"},
          "board": {"type": "string", "description": "板块，可空"},
          "qtype": {"type": "string", "description": "题型，可空"},
          "analysis": {"type": "string", "description": "解题方法/思路/易错点，可空"}},
          "required": ["id"]}, kind="update")
def _t_update_wq(args, db):
    wid = int(args.get("id") or 0)
    if not db.execute("SELECT 1 FROM wrong_questions WHERE id=? AND user_id=?", (wid, uid())).fetchone():
        return "没找到这道错题（id=%s）。" % wid, None
    sets, a = [], []
    for arg, col in (("answer", "answer"), ("board", "board"), ("qtype", "qtype"), ("analysis", "method")):
        if (args.get(arg) or "").strip():
            sets.append(col + "=?"); a.append(args[arg].strip())
    if not sets:
        return "没有要更新的字段。", None
    sets.append("updated_at=datetime('now','localtime')")
    a += [wid, uid()]
    db.execute("UPDATE wrong_questions SET %s WHERE id=? AND user_id=?" % ",".join(sets), a)
    db.commit()
    return "已更新错题（id=%d）。" % wid, {"type": "refresh", "what": "wrongq"}


@tool("star_word",
      "收藏或取消收藏「成语词语积累」里已收录的某个词。用户说「把 XX 加星标/收藏 XX」时调用。",
      {"type": "object", "properties": {
          "word": {"type": "string", "description": "已收录的词，如「毋庸置疑」"},
          "starred": {"type": "boolean", "description": "true=收藏，false=取消，默认 true"}},
          "required": ["word"]}, kind="update")
def _t_star_word(args, db):
    w = (args.get("word") or "").strip()
    if not w:
        return "没给要收藏的词。", None
    on = 1 if args.get("starred", True) else 0
    cur = db.execute("UPDATE entries SET starred=? WHERE user_id=? AND word=?", (on, uid(), w))
    db.commit()
    if not cur.rowcount:
        return "没找到收录的「%s」，可先用 add_word 收录。" % w, None
    return "已%s「%s」。" % ("收藏" if on else "取消收藏", w), {"type": "refresh", "what": "entries"}


@tool("append_to_note",
      "往「小记」里某条已有笔记追加内容。先用 list_notes 拿到笔记 id 再调。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "小记 id（来自 list_notes）"},
          "content": {"type": "string", "description": "要追加的内容"}},
          "required": ["id", "content"]}, kind="update")
def _t_append_note(args, db):
    nid = int(args.get("id") or 0)
    add = (args.get("content") or "").strip()
    if not add:
        return "没有要追加的内容。", None
    row = db.execute("SELECT content FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()
    if not row:
        return "没找到这条小记（id=%s）。" % nid, None
    new = ((row["content"] or "").rstrip() + "\n" + add).strip()
    db.execute("UPDATE notes SET content=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
               (new, nid, uid()))
    db.commit()
    return "已追加到小记（id=%d）。" % nid, {"type": "refresh", "what": "notes"}


@tool("add_daily_task",
      "给用户的「每日任务」清单新增一个每天要做的任务。用户说「加个每日任务/每天提醒我做 XX」时调用。",
      {"type": "object", "properties": {
          "text": {"type": "string", "description": "任务内容，如「刷20道判断推理」"}},
          "required": ["text"]}, kind="write")
def _t_add_task(args, db):
    t = (args.get("text") or "").strip()
    if not t:
        return "没给任务内容。", None
    db.execute("INSERT INTO task_templates(user_id,text) VALUES(?,?)", (uid(), t[:120]))
    db.commit()
    return "已加入每日任务：%s" % t[:120], {"type": "refresh", "what": "tasks"}


@tool("complete_daily_task",
      "把用户今天的某个每日任务标记为已完成（打卡）。先用 get_daily_tasks 拿到任务 id 再调。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "每日任务 id（来自 get_daily_tasks）"}},
          "required": ["id"]}, kind="update")
def _t_complete_task(args, db):
    tid = int(args.get("id") or 0)
    row = db.execute("SELECT text FROM task_templates WHERE id=? AND user_id=? AND active=1",
                     (tid, uid())).fetchone()
    if not row:
        return "没找到这个每日任务（id=%s）。" % tid, None
    db.execute("INSERT OR IGNORE INTO task_done(user_id,tpl_id,date) VALUES(?,?,?)",
               (uid(), tid, datetime.now().strftime("%Y-%m-%d")))
    db.commit()
    return "已打卡：%s ✅" % row["text"], {"type": "refresh", "what": "tasks"}


@tool("complete_plan_item",
      "把用户今日备考计划里的某一项标记为完成（完成即计入当天学习）。先用 get_plan_today 拿到 id 再调。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "计划项 id（来自 get_plan_today）"}},
          "required": ["id"]}, kind="update")
def _t_complete_plan(args, db):
    pid = int(args.get("id") or 0)
    row = db.execute("SELECT title FROM plan_items WHERE id=? AND user_id=?", (pid, uid())).fetchone()
    if not row:
        return "没找到这个计划项（id=%s）。" % pid, None
    db.execute("UPDATE plan_items SET done=1, done_at=datetime('now','localtime') WHERE id=?", (pid,))
    _mark_study(db, uid(), datetime.now().strftime("%Y-%m-%d"))
    db.commit()
    return "已完成计划项：%s ✅" % row["title"], {"type": "refresh", "what": "plan"}


@tool("star_classic",
      "收藏或取消收藏古诗文库里的某一篇。先用 search_classics 拿到 id。用户说「收藏这首诗」时调用。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "古诗文 id（来自 search_classics）"},
          "starred": {"type": "boolean", "description": "true=收藏，false=取消，默认 true"}},
          "required": ["id"]}, kind="update")
def _t_star_classic(args, db):
    cid = int(args.get("id") or 0)
    row = db.execute("SELECT title FROM classics WHERE id=?", (cid,)).fetchone()
    if not row:
        return "没找到这篇古诗文（id=%s）。" % cid, None
    if args.get("starred", True):
        db.execute("INSERT OR IGNORE INTO classic_stars(user_id,classic_id) VALUES(?,?)", (uid(), cid))
        msg = "已收藏「%s」。" % row["title"]
    else:
        db.execute("DELETE FROM classic_stars WHERE user_id=? AND classic_id=?", (uid(), cid))
        msg = "已取消收藏「%s」。" % row["title"]
    db.commit()
    return msg, {"type": "refresh", "what": "classics"}


# ================================================================ 出文件 / 投放
# 生成和投放**拆成两个工具**，理由是它们的性质不同：生成随时可以重来（不满意就再写一版），
# 投放是「东西离开这个助手、进到别的容器」的动作。合成一个的话，AI 每写一版都会往
# 资料库里堆一份，用户还得回头去删。
# 拆开还有一个好处：以后加目的地（知识库、小记…）只改投放这一端，生成端一个字不用动。

@tool("create_file",
      ("把一段内容做成文件，存进用户的「AI 产出」（库 → AI 产出）。"
       "当用户说「写一份…存成文件 / 导出成 PDF / 整理成文档」时调用。\n"
       "**正文要你自己写全**：这个工具不会替你生成内容，它只负责落盘。"
       "写完告诉用户文件存在哪、叫什么，并说明可以再投到资料库/云盘/小记。"),
      {"type": "object", "properties": {
          "title": {"type": "string", "description": "文件标题，例如「资料分析速算公式汇总」"},
          "content": {"type": "string", "description": "完整正文，Markdown（# 标题、- 列表、**加粗** 都认）"},
          "kind": {"type": "string", "enum": ["md", "txt", "pdf"],
                   "description": "md=Markdown 文档（默认）、txt=纯文本、pdf=可直接打印的 PDF"}},
          "required": ["title", "content"]}, kind="write")
def _t_create_file(args, db):
    from mods.aiout import create_output
    title = (args.get("title") or "").strip()
    content = args.get("content") or ""
    if not title or not content.strip():
        return "标题和正文都得有，才谈得上做成文件。", None
    kind = args.get("kind") if args.get("kind") in ("md", "txt", "pdf") else "md"
    oid = create_output(db, uid(), title, content, kind=kind)
    return ("已存进「AI 产出」：《%s》（%s，%d 字，id=%d）。"
            "用户可以在 库 → AI 产出 里看全文、下载，或让你投到资料库/云盘/小记。"
            % (title, kind, len(content), oid),
            {"type": "refresh", "what": "aiout", "toast": "已生成《%s》 📄" % title[:20]})


def _pv_deliver(args, db):
    """确认弹窗上要说清**哪份东西**要去**哪儿** —— 投放是东西离开这里的动作，
    只弹一句「确认投放？」等于让人盲点。"""
    r = db.execute("SELECT title FROM ai_outputs WHERE id=? AND user_id=?",
                   (int(args.get("id") or 0), uid())).fetchone()
    dest = {"material": "资料库", "drive": "云盘", "note": "小记"}.get(args.get("dest"), args.get("dest") or "?")
    return "把《%s》投到%s" % ((r["title"] if r else "（找不到这份产出）"), dest)


@tool("deliver_file",
      ("把「AI 产出」里的某份文件投到别的地方：资料库 / 云盘 / 小记。"
       "先用 list_files 拿到 id 再调（或用刚才 create_file 返回的那个 id）。"
       "**投放会让东西离开这个助手**，所以系统会先让用户点头确认。"),
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "产出 id"},
          "dest": {"type": "string", "enum": ["material", "drive", "note"],
                   "description": "material=资料库、drive=云盘、note=小记"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认后才填 true；首次调用不要填"}},
          "required": ["id", "dest"]}, kind="write", confirm=True, preview=_pv_deliver)
def _t_deliver_file(args, db):
    from mods.aiout import deliver
    oid, dest = int(args.get("id") or 0), args.get("dest")
    if dest not in ("material", "drive", "note"):
        return "只能投到 资料库/云盘/小记 三者之一。", None
    ok, msg = deliver(db, uid(), oid, dest)
    if not ok:
        return msg, None
    return msg, {"type": "refresh", "what": dest, "toast": "已投放 📤"}


@tool("list_files",
      "列出用户「AI 产出」里的文件（你生成过的文档/汇总）。要投放或让用户下载时，先用它拿 id。",
      {"type": "object", "properties": {
          "limit": {"type": "integer", "description": "最多列几条，默认 10"}}}, kind="read")
def _t_list_files(args, db):
    n = max(1, min(int(args.get("limit") or 10), 30))
    rows = db.execute("SELECT id, kind, title, size, sent, created_at FROM ai_outputs "
                      "WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid(), n)).fetchall()
    if not rows:
        return "「AI 产出」里还是空的。", None
    return json.dumps([dict(r) for r in rows], ensure_ascii=False), None


# ================================================================ 删除类（destructive，需二次确认）
# 下面三个 preview：确认弹窗要把**那条数据的原文**摆给用户看。没有它，删错题和删小记
# 只能弹一句「确认删除这条内容？」，用户不知道是哪条，只能盲点确定——删除是不可逆的，
# 这是最不该省的一步。取不到就返回空串，前端退回通用话术。
def _pv_entry(args, db):
    w = (args.get("word") or "").strip()
    r = db.execute("SELECT word, note FROM entries WHERE user_id=? AND word=?", (uid(), w)).fetchone()
    if not r:
        return ""
    return "%s%s" % (r["word"], "　" + (r["note"] or "")[:60] if r["note"] else "")


def _pv_wq(args, db):
    r = db.execute("SELECT question, board, qtype FROM wrong_questions WHERE id=? AND user_id=?",
                   (int(args.get("id") or 0), uid())).fetchone()
    if not r:
        return ""
    tag = " · ".join(x for x in (r["board"], r["qtype"]) if x)
    return "%s%s" % ((r["question"] or "")[:80], "\n" + tag if tag else "")


def _pv_note(args, db):
    r = db.execute("SELECT content, created_at FROM notes WHERE id=? AND user_id=?",
                   (int(args.get("id") or 0), uid())).fetchone()
    if not r:
        return ""
    return "%s\n记于 %s" % ((r["content"] or "")[:80], (r["created_at"] or "")[:10])


@tool("delete_entry",
      "从「成语词语积累」删除某个已收录的词（连带取消常考那边的收藏）。不可逆，需用户确认。",
      {"type": "object", "properties": {
          "word": {"type": "string", "description": "要删除的已收录词"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认删除后才填 true；首次调用不要填，让系统先要确认"}},
          "required": ["word"]}, kind="destructive", confirm=True, preview=_pv_entry)
def _t_delete_entry(args, db):
    w = (args.get("word") or "").strip()
    if not w:
        return "没给要删除的词。", None
    cur = db.execute("DELETE FROM entries WHERE user_id=? AND word=?", (uid(), w))
    db.execute("DELETE FROM ck_stars WHERE user_id=? AND board IN ('成语','实词') AND title=?", (uid(), w))
    db.commit()
    if not cur.rowcount:
        return "没找到收录的「%s」。" % w, None
    return "已从成语词语积累删除「%s」。" % w, {"type": "refresh", "what": "entries"}


@tool("delete_wrong_question",
      "从错题本删除某道题。先用 list_wrong_questions 拿到 id。不可逆，需用户确认。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "错题 id（来自 list_wrong_questions）"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认删除后才填 true；首次调用不要填，让系统先要确认"}},
          "required": ["id"]}, kind="destructive", confirm=True, preview=_pv_wq)
def _t_delete_wq(args, db):
    wid = int(args.get("id") or 0)
    row = db.execute("SELECT image FROM wrong_questions WHERE id=? AND user_id=?", (wid, uid())).fetchone()
    if not row:
        return "没找到这道错题（id=%s）。" % wid, None
    if row["image"]:
        try:
            from mods.wrongq import _remove_file
            _remove_file(uid(), row["image"])
        except Exception:
            pass
    db.execute("DELETE FROM wrong_questions WHERE id=? AND user_id=?", (wid, uid()))
    db.commit()
    return "已从错题本删除（id=%d）。" % wid, {"type": "refresh", "what": "wrongq"}


@tool("delete_note",
      "删除「小记」里的某条笔记。先用 list_notes 拿到 id。不可逆，需用户确认。",
      {"type": "object", "properties": {
          "id": {"type": "integer", "description": "小记 id（来自 list_notes）"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认删除后才填 true；首次调用不要填，让系统先要确认"}},
          "required": ["id"]}, kind="destructive", confirm=True, preview=_pv_note)
def _t_delete_note(args, db):
    nid = int(args.get("id") or 0)
    if not db.execute("SELECT 1 FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone():
        return "没找到这条小记（id=%s）。" % nid, None
    db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return "已删除小记（id=%d）。" % nid, {"type": "refresh", "what": "notes"}


def _round(msgs, tools, temperature, max_tokens, deadline, parts, tier="fast"):
    """跑一次调用：正文边出边往外吐，攒进 parts，返回完整 message（可能含 tool_calls）。

    正文这一路带一道闸：模型一旦开始吐工具调用标记（见 _TOOL_MARK），后面就全是标记了，
    从那里起一个字都不再往前端推。**必须在流式这一层挡** —— 等攒完再洗，用户早就
    看见那堆乱码了。标记可能被切在两片之间，所以尾部的 `<` 先扣住不发，下一片再判。
    """
    m, buf, open_gate = {}, "", True
    for kind, p in _ai_stream(msgs, tools=tools, temperature=temperature,
                              max_tokens=max_tokens, deadline=deadline, tier=tier):
        if kind == "content":
            if not open_gate:
                continue
            buf += p
            vis, cut = _cut_markup(buf)
            if cut:
                open_gate = False
            else:
                # 尾巴上可能是半个标记（`<｜` 被切在两片之间），扣住等下一片
                i = vis.rfind("<")
                if i >= 0 and len(vis) - i <= 24:
                    vis = vis[:i]
            buf = buf[len(vis):] if open_gate else ""
            if vis:
                parts.append(vis)
                yield "delta", vis
        elif kind == "reasoning":
            yield "reasoning", p        # 前端拿它把「思考中…」变成真的在动
        elif kind == "ping":
            yield "ping", ""            # 上游心跳：一路转到浏览器，别让隧道把连接掐了
        elif kind == "done":
            m = p
    if open_gate and buf:
        vis, _ = _cut_markup(buf)          # 扣住的尾巴：确认不是标记就补发
        if vis:
            parts.append(vis)
            yield "delta", vis
    return m


def ai_chat_agentic_stream(messages, db, max_rounds=4, temperature=0.5, max_tokens=2000,
                           budget=AI_BUDGET, tier="fast", web=False):
    """带工具调用的对话循环，流式版。产出 (kind, payload)：

        ("reasoning", 片段)          模型在想（还没开始写正文）
        ("delta",     片段)          正文增量
        ("tool",      {"name": …})   开始执行某个工具
        ("done",      {"reply", "actions", "trace"})  收尾：整段回复 + 动作 + 工具轨迹

    reply 是**这一轮吐出去的全部正文**拼起来的，跟用户屏幕上看到的一致——模型常会
    先说一句「我先查一下…」再调工具，那句话也是回答的一部分，落库时不能丢。

    trace 是这一轮调过的工具（名字、参数、结果摘要）。调用方要把它落库：
    没有它，刷新会话就看不到 AI 动过哪些数据，下一轮模型也不知道自己查过什么。
    """
    msgs = list(messages)
    actions, parts, trace = [], [], []
    hits = []                       # web_search 的完整命中，只给下面的兜底用
    # 按最后一句用户消息的意图挑工具（命中不了主题就全给，见 tool_specs_for）
    last_user = next((m.get("content") or "" for m in reversed(messages)
                      if m.get("role") == "user"), "")
    # 项目对话再并上项目资料那两个工具：挂在项目上的资料，这个项目下的每一轮都该够得着，
    # 不管用户这句话里有没有出现「资料」两个字（见 PROJECT_TOOLS）。
    keep = (PROJECT_TOOLS if cur_project() else ())
    if web:
        # 用户按了「联网」：这两个工具**必须在手上**。意图那道正则本来也会放它们过，
        # 但按钮是明示的意图，不能再交给关键词去猜——一次没命中就等于按钮没接线。
        keep = tuple(keep) + WEB_TOOLS
    specs = tool_specs_for(last_user, always=keep)
    if web:
        # 指令放在最后一条：离用户那句话越近，模型越不容易把它当耳边风。
        msgs.append({"role": "system", "content": WEB_ON_PROMPT})
        # 搜 → 读正文 → 可能再搜，四轮打不住；预算也得跟着放宽（见 AI_WEB_BUDGET）
        max_rounds = max(max_rounds, 6)
        budget = max(budget, AI_WEB_BUDGET)
    deadline = time.time() + budget
    truncated = True                # 只有「模型自己说完了」那条路会把它改回 False
    try:
        for _ in range(max_rounds):
            if time.time() >= deadline - 5:
                break               # 预算用光就别再起新一轮工具，剩下的时间留给收尾那句话
            m = yield from _round(msgs, specs, temperature, max_tokens, deadline, parts, tier)
            tcs = m.get("tool_calls")
            if not tcs:
                yield "done", {"reply": "".join(parts).strip(), "actions": actions,
                               "trace": trace, "truncated": False}
                return
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            need_confirm = False
            for tc in tcs:
                fn = tc.get("function") or {}
                try:
                    a = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    a = {}
                # label 是给用户看的人话（「查你的错题本」）——前端据此显示在「思考中」那行，
                # 不再把查询和删除一律说成「正在操作…」
                yield "tool", {"name": fn.get("name") or "", "label": tool_label(fn.get("name"))}
                result, action = exec_tool(fn.get("name"), a, db)
                if fn.get("name") == "web_search":
                    _collect_hits(hits, result)
                if action:
                    actions.append(action)
                    if action.get("type") == "confirm":
                        need_confirm = True
                # 轨迹落库用。结果只留摘要：完整的查询结果可能上千字，存下来既占地方，
                # 下一轮再喂回去也是浪费——模型要细节可以再查一次。
                trace.append({"name": fn.get("name") or "", "label": tool_label(fn.get("name")),
                              "args": a, "result": (result or "")[:400],
                              "action": (action or {}).get("type") or ""})
                msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
            if need_confirm:
                # 删除类要用户确认：停掉工具循环，让模型把「确定删除吗」问出来，
                # 别在同一轮里自己补个 _confirmed 就把东西删了——确认必须跨一次用户回合。
                truncated = False   # 这是「等你确认」，不是「没干完」，别给用户弹「继续」
                break
        # 轮数（或预算）用完还在调工具：再要一次纯文本收尾。
        # **必须明说「不许再调工具」**：光是不给 tools 不够——它照旧想调，然后把工具调用
        # 当正文吐出来（<｜｜DSML｜｜tool_calls>…），用户屏幕上只剩一堆标记，答案没了。
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n\n")
        msgs.append({"role": "system", "content":
                     "工具到此为止，**这一轮不要再调用任何工具、也不要写任何工具调用**。"
                     "就用上面已经查到的内容把话说完：给结论，并注明出处（标题 + 链接）。"
                     "信息不够就明说还缺什么、建议用户去哪儿看，不要编。"})
        before = len(parts)
        yield from _round(msgs, None, temperature, max_tokens, deadline, parts, tier)
        if len("".join(parts[before:]).strip()) < 20:
            # 收尾这一轮几乎什么也没说出来 —— 多半是它还在写工具调用，被上面那道闸挡下了。
            # 把查到的东西自己交代出去，别让用户对着一串「我再查一下」收场。
            tail = _fallback_from_hits(hits)
            if tail:
                parts.append(tail)
                yield "delta", tail
        # truncated=True 表示「轮数/预算用完了它还在调工具」——活没干完，只是被迫收尾。
        # 前端据此给一个「继续」按钮，而不是让用户对着半截总结干瞪眼。
        yield "done", {"reply": "".join(parts).strip(), "actions": actions,
                       "trace": trace, "truncated": truncated}
    except Exception as e:
        # 收尾这一下失败时**不能整轮报错**：工具可能已经真的把词收录、把小记写了，
        # 这时候回「AI 调用失败」既是假话，用户还会以为没做成而再做一遍。
        # 所以拿工具自己返回的结果拼一句话交差，动作照常带回前端。
        done = [t["content"] for t in msgs if t.get("role") == "tool" and t.get("content")]
        if not done:
            raise
        log.warning("agentic 收尾调用失败（%r），改用工具结果作答", e)
        parts.append("\n".join(done) + "\n\n（网络不稳，这句总结是直接来自操作结果的，操作本身已完成。）")
        yield "done", {"reply": "".join(parts).strip(), "actions": actions, "trace": trace}


def ai_chat_agentic(messages, db, **kw):
    """带工具调用的对话循环，非流式版。返回 (最终回复文本, [action], [工具轨迹])。

    只是把流式那条跑干——**逻辑不再有第二份**。老 WebView（拿不到 ReadableStream）
    和内部调用走这条，行为跟流式完全一致，不会出现「网页版修好了、APK 还是老样子」。
    """
    for kind, p in ai_chat_agentic_stream(messages, db, **kw):
        if kind == "done":
            return p["reply"], p["actions"], p.get("trace") or []
    return "", [], []


def _ai_agentic_or_error(messages, db, **kw):
    """带工具的对话 + 统一错误封装。
    返回 (reply, actions, trace, None) 或 (None, None, None, (json,code))。"""
    try:
        reply, actions, trace = ai_chat_agentic(messages, db, **kw)
        return reply, actions, trace, None
    except Exception as e:
        # 错误话术统一在 aiclient.error_message，别在这儿再抄一份 401/402/429 的分支：
        # 原先两份，改一处漏一处。
        return None, None, None, (jsonify({"error": aiclient.error_message(e)}), 502)
