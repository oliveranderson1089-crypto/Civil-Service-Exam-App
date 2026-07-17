"""AI 工具调用：让 AI 真能操作应用（而不只是嘴上说做了）。

原来 AI 只会「嘴上说」帮你做了（比如说「已把成语加入收录」其实没写库）。
给它 function calling：服务端能直接做的（加收录…）就执行；只能前端做的（跳到某功能）
记成一个 action 交回前端执行。这样 AI 说「已加入」就是真的加了。
"""
import json
import urllib.error
import urllib.request

from flask import jsonify

from core import CJK_RE, lookup, to_pinyin, uid
from mods.ai import _ai_call_or_error, _ai_conf


def _ai_raw(messages, tools=None, temperature=0.4, max_tokens=1600, timeout=120):
    """底层调用，返回完整 message 对象（可能含 tool_calls）。"""
    conf = _ai_conf()
    if not conf["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    b = conf["base"]
    url = b if b.endswith("/chat/completions") else (
        b + "/chat/completions" if b.endswith("/v1") else b + "/v1/chat/completions")
    payload = {"model": conf["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + conf["key"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]


# 应用里能让 AI 帮你打开的功能（名字 → 前端的 openXxx 函数）
AI_FEATURES = {
    "成语词语积累": "openIdiom", "每日时政": "openNews", "每日新闻视频": "openVideos",
    "人民时评范文": "openFanwen", "今日复习": "openReview", "常识积累": "openChangshi",
    "错题本": "openWrongq", "小记": "openNotes", "资料库": "openMaterials",
    "古诗文名句": "openClassics", "时政要文库": "openPolicyDocs", "任务清单": "openTasks",
    "党的创新理论学习词典": "openPartyDict", "常考": "openChangkao",
}

AI_TOOLS = [
    {"type": "function", "function": {
        "name": "add_word",
        "description": "把一个成语/词语/词组加入用户的「成语词语积累」收录。当用户说「收录/加入/记下这个词」时调用。",
        "parameters": {"type": "object", "properties": {
            "word": {"type": "string", "description": "要收录的成语或词语本身，如「佶屈聱牙」"},
            "note": {"type": "string", "description": "可选备注"}},
            "required": ["word"]}}},
    {"type": "function", "function": {
        "name": "open_feature",
        "description": "帮用户打开应用里的某个功能页面，省得他自己在菜单里找。当用户说「打开/去/进入某功能」时调用。",
        "parameters": {"type": "object", "properties": {
            "feature": {"type": "string", "enum": list(AI_FEATURES.keys()),
                        "description": "功能名"}},
            "required": ["feature"]}}},
    {"type": "function", "function": {
        "name": "create_note",
        "description": "帮用户在「小记」里记一条笔记。当用户说「帮我记下/记一条/存到小记」时调用。",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "要记的内容"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "可选标签"}},
            "required": ["content"]}}},
    {"type": "function", "function": {
        "name": "add_wrong_question",
        "description": ("把一道**完整的**题目加入用户的「错题本」。当用户发来的（或截图 OCR 出来的）内容"
                        "确实是一道完整题目——有题干、通常还有选项——时调用。只有能确定是完整题目才调用；"
                        "若拿不准这是不是题目、或题目残缺不全，**不要调用**，而是用文字反问用户确认。"),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "完整题干（含选项 A/B/C/D，若有）。尽量保留原文。"},
            "answer": {"type": "string", "description": "正确答案（如 C；不确定就留空）"},
            "board": {"type": "string", "description": "所属板块，如「行测·资料分析」「行测·言语理解」「常识判断」，判断不了就留空"},
            "qtype": {"type": "string", "description": "题型，如「资料分析-增长率」「逻辑填空」，判断不了就留空"},
            "analysis": {"type": "string", "description": "解题方法/思路/易错点（可选，简要写）"}},
            "required": ["question"]}}},
]


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


def _ai_exec_tool(name, args, db):
    """执行一个工具。返回 (给模型看的结果文本, 给前端的 action 或 None)。"""
    if name == "add_word":
        word = (args.get("word") or "").strip()
        if not word:
            return "没有指定要收录的词。", None
        has_exp = _ai_add_entry(db, word, (args.get("note") or "").strip())
        n = db.execute("SELECT COUNT(*) FROM entries WHERE user_id=?", (uid(),)).fetchone()[0]
        tail = "（已附上释义）" if has_exp else "（暂未查到释义，先收录）"
        return ("已把「%s」加入成语词语积累%s，在 行测→言语理解与表达→成语词语积累 里能看到，当前共 %d 条。"
                % (word, tail, n)), {"type": "refresh", "what": "entries"}
    if name == "open_feature":
        f = (args.get("feature") or "").strip()
        fn = AI_FEATURES.get(f)
        if not fn:
            return "没有这个功能：" + f, None
        return "已为用户打开「%s」。" % f, {"type": "navigate", "fn": fn, "label": f}
    if name == "create_note":
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
    if name == "add_wrong_question":
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
                {"type": "refresh", "what": "wrongq"})
    return "未知工具：" + str(name), None


def ai_chat_agentic(messages, db, max_rounds=4, temperature=0.5, max_tokens=2000):
    """带工具调用的对话循环。返回 (最终回复文本, [前端要执行的 action])。"""
    msgs = list(messages)
    actions = []
    for _ in range(max_rounds):
        m = _ai_raw(msgs, tools=AI_TOOLS, temperature=temperature, max_tokens=max_tokens)
        tcs = m.get("tool_calls")
        if not tcs:
            return (m.get("content") or "").strip(), actions
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            result, action = _ai_exec_tool(fn.get("name"), a, db)
            if action:
                actions.append(action)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
    # 轮数用完还在调工具：再要一次纯文本收尾
    m = _ai_raw(msgs, temperature=temperature, max_tokens=max_tokens)
    return (m.get("content") or "").strip(), actions


def _ai_agentic_or_error(messages, db, **kw):
    """带工具的对话 + 统一错误封装。返回 (reply, actions, None) 或 (None, None, (json,code))。"""
    try:
        reply, actions = ai_chat_agentic(messages, db, **kw)
        return reply, actions, None
    except urllib.error.HTTPError as e:
        msg = "AI 服务返回错误 %d" % e.code
        if e.code == 401:
            msg = "API Key 无效或未授权，请在后台重新填写"
        elif e.code == 402:
            msg = "账户余额不足，请到 DeepSeek 充值"
        elif e.code == 429:
            msg = "请求过于频繁，请稍后再试"
        return None, None, (jsonify({"error": msg}), 502)
    except urllib.error.URLError as e:
        return None, None, (jsonify({"error": "连不上 AI 服务：" + str(e.reason)}), 502)
    except Exception as e:
        return None, None, (jsonify({"error": "AI 调用失败：" + str(e)}), 502)
