"""AI 工具调用：让 AI 真能操作应用（而不只是嘴上说做了）。

原来 AI 只会「嘴上说」帮你做了（比如说「已把成语加入收录」其实没写库）。
给它 function calling：服务端能直接做的（加收录…）就执行；只能前端做的（跳到某功能）
记成一个 action 交回前端执行。这样 AI 说「已加入」就是真的加了。
"""
import json
import time
from datetime import datetime

from flask import jsonify

import aiclient
from core import CFG, CJK_RE, _mark_study, log, lookup, to_pinyin, uid
from mods.agent_tools import exec_tool, tool, tool_specs
from mods.ai import _ai_call_or_error


# 对话是**用户盯着屏幕等**的场景，超时口径跟离线脚本（出题/批改，动辄一两分钟）不同：
# 实测这条路径一次调用 1~3 秒（带全部工具、20 条历史也一样）。所以慢不是「模型在想」，
# 是这条 TCP 已经死了——代理/路由一抖，连接静默失效，read 只会干等到超时。
# 走流式之后这个数的含义变了：它是**两个 token 之间**能等多久，不是整次调用的上限。
# 连接一死，几十秒内就报出来；模型写得再长也不会被它误杀。
AI_TIMEOUT = 40
AI_RETRIES = 2
# 一次对话的总预算。工具循环最多 5 次调用，不封顶的话最坏叠成十分钟：
# 手机端早在 Cloudflare 隧道的 100 秒上限处就 524 断了，服务端还在空转占线程。
AI_BUDGET = 100


def _ai_stream(messages, tools=None, temperature=0.4, max_tokens=1600, deadline=None):
    """一次流式调用，把 aiclient 的事件原样传出来。

    走 aiclient 而不是自己拼 URL：模型名解析、官方改名时的探活自愈，跟全站一套。

    deadline 是这一整轮对话的截止时刻（time.time() 口径）：越到后面留给单次调用的
    时间越短，免得最后一次调用把总预算撑爆。
    """
    timeout = AI_TIMEOUT
    if deadline is not None:
        # 除以「尝试次数」而不是直接拿剩余时间当超时：timeout 是**每次尝试**的，
        # 带 2 次重试就是三份，不摊开的话总预算会被一次调用撑到三倍。
        timeout = max(5, min(timeout, (deadline - time.time()) / (AI_RETRIES + 1)))
    return aiclient.stream(messages, tier="fast", temperature=temperature,
                           max_tokens=max_tokens, timeout=timeout, cfg=CFG,
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
      "把一个成语/词语/词组加入用户的「成语词语积累」收录。当用户说「收录/加入/记下这个词」时调用。",
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


# ================================================================ 删除类（destructive，需二次确认）
@tool("delete_entry",
      "从「成语词语积累」删除某个已收录的词（连带取消常考那边的收藏）。不可逆，需用户确认。",
      {"type": "object", "properties": {
          "word": {"type": "string", "description": "要删除的已收录词"},
          "_confirmed": {"type": "boolean",
                         "description": "仅在用户已明确确认删除后才填 true；首次调用不要填，让系统先要确认"}},
          "required": ["word"]}, kind="destructive", confirm=True)
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
          "required": ["id"]}, kind="destructive", confirm=True)
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
          "required": ["id"]}, kind="destructive", confirm=True)
def _t_delete_note(args, db):
    nid = int(args.get("id") or 0)
    if not db.execute("SELECT 1 FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone():
        return "没找到这条小记（id=%s）。" % nid, None
    db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid()))
    db.commit()
    return "已删除小记（id=%d）。" % nid, {"type": "refresh", "what": "notes"}


def _round(msgs, tools, temperature, max_tokens, deadline, parts):
    """跑一次调用：正文边出边往外吐，攒进 parts，返回完整 message（可能含 tool_calls）。"""
    m = {}
    for kind, p in _ai_stream(msgs, tools=tools, temperature=temperature,
                              max_tokens=max_tokens, deadline=deadline):
        if kind == "content":
            parts.append(p)
            yield "delta", p
        elif kind == "reasoning":
            yield "reasoning", p        # 前端拿它把「思考中…」变成真的在动
        elif kind == "done":
            m = p
    return m


def ai_chat_agentic_stream(messages, db, max_rounds=4, temperature=0.5, max_tokens=2000,
                           budget=AI_BUDGET):
    """带工具调用的对话循环，流式版。产出 (kind, payload)：

        ("reasoning", 片段)          模型在想（还没开始写正文）
        ("delta",     片段)          正文增量
        ("tool",      {"name": …})   开始执行某个工具
        ("done",      {"reply", "actions"})  收尾：整段回复 + 前端要执行的动作

    reply 是**这一轮吐出去的全部正文**拼起来的，跟用户屏幕上看到的一致——模型常会
    先说一句「我先查一下…」再调工具，那句话也是回答的一部分，落库时不能丢。
    """
    msgs = list(messages)
    actions, parts = [], []
    deadline = time.time() + budget
    try:
        for _ in range(max_rounds):
            if time.time() >= deadline - 5:
                break               # 预算用光就别再起新一轮工具，剩下的时间留给收尾那句话
            m = yield from _round(msgs, tool_specs(), temperature, max_tokens, deadline, parts)
            tcs = m.get("tool_calls")
            if not tcs:
                yield "done", {"reply": "".join(parts).strip(), "actions": actions}
                return
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            need_confirm = False
            for tc in tcs:
                fn = tc.get("function") or {}
                try:
                    a = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    a = {}
                yield "tool", {"name": fn.get("name") or ""}
                result, action = exec_tool(fn.get("name"), a, db)
                if action:
                    actions.append(action)
                    if action.get("type") == "confirm":
                        need_confirm = True
                msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
            if need_confirm:
                # 删除类要用户确认：停掉工具循环，让模型把「确定删除吗」问出来，
                # 别在同一轮里自己补个 _confirmed 就把东西删了——确认必须跨一次用户回合。
                break
        # 轮数（或预算）用完还在调工具：再要一次纯文本收尾
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n\n")
        yield from _round(msgs, None, temperature, max_tokens, deadline, parts)
        yield "done", {"reply": "".join(parts).strip(), "actions": actions}
    except Exception as e:
        # 收尾这一下失败时**不能整轮报错**：工具可能已经真的把词收录、把小记写了，
        # 这时候回「AI 调用失败」既是假话，用户还会以为没做成而再做一遍。
        # 所以拿工具自己返回的结果拼一句话交差，动作照常带回前端。
        done = [t["content"] for t in msgs if t.get("role") == "tool" and t.get("content")]
        if not done:
            raise
        log.warning("agentic 收尾调用失败（%r），改用工具结果作答", e)
        parts.append("\n".join(done) + "\n\n（网络不稳，这句总结是直接来自操作结果的，操作本身已完成。）")
        yield "done", {"reply": "".join(parts).strip(), "actions": actions}


def ai_chat_agentic(messages, db, **kw):
    """带工具调用的对话循环，非流式版。返回 (最终回复文本, [前端要执行的 action])。

    只是把流式那条跑干——**逻辑不再有第二份**。老 WebView（拿不到 ReadableStream）
    和内部调用走这条，行为跟流式完全一致，不会出现「网页版修好了、APK 还是老样子」。
    """
    for kind, p in ai_chat_agentic_stream(messages, db, **kw):
        if kind == "done":
            return p["reply"], p["actions"]
    return "", []


def _ai_agentic_or_error(messages, db, **kw):
    """带工具的对话 + 统一错误封装。返回 (reply, actions, None) 或 (None, None, (json,code))。"""
    try:
        reply, actions = ai_chat_agentic(messages, db, **kw)
        return reply, actions, None
    except Exception as e:
        # 错误话术统一在 aiclient.error_message，别在这儿再抄一份 401/402/429 的分支：
        # 原先两份，改一处漏一处。
        return None, None, (jsonify({"error": aiclient.error_message(e)}), 502)
