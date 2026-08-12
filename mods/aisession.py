"""全局 AI 会话中心：跨页面的对话历史。


"""

import json
import re

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

import aiclient
from core import CFG, get_db, log, open_db, uid
from mods.agent import _ai_agentic_or_error, ai_chat_agentic_stream
from mods.agent_tools import TOOL_REGISTRY, exec_tool, tool_label
from mods.ai import vision_chat, vision_configured
from mods.aichat import _user_stats
from mods.attach import ai_img_path

bp = Blueprint("aisession", __name__)


@bp.get("/api/aichat/home")
def aichat_home():
    db = get_db()
    db.execute("DELETE FROM ai_chats WHERE user_id=? AND created_at < datetime('now','localtime','-1 hour') "
               "AND NOT EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=ai_chats.id)", (uid(),))
    db.commit()
    # 搜索：标题和正文一起搜。原先 LIMIT 50 一刀切、也不能搜 —— 聊得多了旧对话就找不回来。
    q = (request.args.get("q") or "").strip()
    try:
        # 既挡 ?page=x（ValueError），也挡 ?page=99999999999999999999 —— 后者 int() 是过得去的，
        # 到 SQLite 的 OFFSET 才炸 OverflowError。两种都不该把会话列表打成 500
        #（前端只会显示一句「请求失败」，看不出发生了什么）。
        page = max(0, min(int(request.args.get("page") or 0), 10000))
    except ValueError:
        page = 0
    args = [uid()]
    cond = ""
    if q:
        kw = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
        cond = (" AND (c.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM ai_msgs m2 "
                "WHERE m2.chat_id=c.id AND m2.content LIKE ? ESCAPE '\\'))")
        args += [kw, kw]
    chats = db.execute(
        "SELECT c.id, c.title, c.updated_at, c.project_id, c.starred, p.name pname FROM ai_chats c "
        "LEFT JOIN ai_projects p ON p.id=c.project_id "
        "WHERE c.user_id=? AND EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=c.id)" + cond +
        " ORDER BY c.starred DESC, c.updated_at DESC LIMIT 50 OFFSET ?",
        args + [page * 50]).fetchall()
    projects = db.execute(
        "SELECT p.id, p.name, p.instructions,"
        "(SELECT COUNT(*) FROM ai_chats c WHERE c.project_id=p.id) cnt "
        "FROM ai_projects p WHERE p.user_id=? ORDER BY p.id DESC", (uid(),)).fetchall()
    return jsonify({"chats": [dict(r) for r in chats], "projects": [dict(r) for r in projects]})


@bp.post("/api/aichat/chats")
def aichat_new():
    data = request.get_json(silent=True) or {}
    pid = data.get("project_id")
    db = get_db()
    cur = db.execute("INSERT INTO ai_chats(user_id,project_id,title) VALUES(?,?,?)",
                     (uid(), pid, ""))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@bp.get("/api/aichat/chats/<int:cid>")
def aichat_get(cid):
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "未找到"}), 404
    rows = db.execute("SELECT id, role, content, COALESCE(kind,'text') kind, meta, attach FROM ai_msgs "
                      "WHERE chat_id=? ORDER BY id", (cid,)).fetchall()
    msgs = []
    for r in rows:
        m = {"id": r["id"], "role": r["role"], "content": r["content"], "kind": r["kind"]}
        if r["kind"] == "tool":
            try:
                m["trace"] = json.loads(r["meta"] or "[]")
            except Exception:
                m["trace"] = []
        # 附件回传：前端要拿它画缩略图（原文 text 不回，白占带宽——那是给模型看的）
        if r["attach"]:
            try:
                m["atts"] = [{"name": a.get("name") or "", "image": a.get("image") or ""}
                             for a in (json.loads(r["attach"]) or [])]
            except Exception:
                m["atts"] = []
        msgs.append(m)
    return jsonify({"id": c["id"], "title": c["title"], "project_id": c["project_id"],
                    "tier": _tier(c), "msgs": msgs})


@bp.put("/api/aichat/chats/<int:cid>")
def aichat_update(cid):
    data = request.get_json(silent=True) or {}
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "未找到"}), 404
    if "title" in data:
        t = (data.get("title") or "").strip()[:40]
        if t:
            db.execute("UPDATE ai_chats SET title=? WHERE id=?", (t, cid))
    if "project_id" in data:
        pid = data.get("project_id")
        db.execute("UPDATE ai_chats SET project_id=? WHERE id=?", (pid, cid))
    if "starred" in data:
        db.execute("UPDATE ai_chats SET starred=? WHERE id=?", (1 if data.get("starred") else 0, cid))
    if "tier" in data:
        db.execute("UPDATE ai_chats SET tier=? WHERE id=?",
                   ("pro" if data.get("tier") == "pro" else "fast", cid))
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/aichat/chats/<int:cid>/msgs/<int:mid>")
def aichat_msg_del(cid, mid):
    """删掉一条消息。删用户那句时，把它之后的整轮（工具轨迹 + 回答）一起带走 ——
    留着一个没有问题的回答，下一轮上下文会很怪。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone():
        return jsonify({"error": "会话不存在"}), 404
    r = db.execute("SELECT * FROM ai_msgs WHERE id=? AND chat_id=?", (mid, cid)).fetchone()
    if not r:
        return jsonify({"error": "消息不存在"}), 404
    if r["role"] == "user":
        nxt = db.execute("SELECT MIN(id) FROM ai_msgs WHERE chat_id=? AND id>? AND role='user'",
                         (cid, mid)).fetchone()[0]
        if nxt:
            db.execute("DELETE FROM ai_msgs WHERE chat_id=? AND id>=? AND id<?", (cid, mid, nxt))
        else:
            db.execute("DELETE FROM ai_msgs WHERE chat_id=? AND id>=?", (cid, mid))
    else:
        db.execute("DELETE FROM ai_msgs WHERE id=?", (mid,))
    db.commit()
    return jsonify({"ok": True})


def _rewind(db, cid, mid):
    """把会话回退到「某条用户消息即将被重新提问」的状态：删掉它和它之后的一切。
    返回那句话的 (content, attach)。"""
    r = db.execute("SELECT * FROM ai_msgs WHERE id=? AND chat_id=? AND role='user'",
                   (mid, cid)).fetchone()
    if not r:
        return None, None
    atts = []
    try:
        atts = json.loads(r["attach"] or "[]")
    except Exception:
        atts = []
    db.execute("DELETE FROM ai_msgs WHERE chat_id=? AND id>=?", (cid, mid))
    db.commit()
    return r["content"] or "", atts


@bp.post("/api/aichat/chats/<int:cid>/retry")
def aichat_retry(cid):
    """重答 / 改问：把最后一轮（或指定那一轮）回退掉，用同一个或新的问题重新生成。

    前端拿到 content 后走正常的 /stream 重发一次 —— 生成这件事只有一条路（见 _build），
    这里只负责「把历史退回去」，不复制一份对话逻辑。
    """
    data = request.get_json(silent=True) or {}
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    mid = int(data.get("msg_id") or 0)
    if not mid:      # 不指定就退最后一轮
        mid = db.execute("SELECT MAX(id) FROM ai_msgs WHERE chat_id=? AND role='user'",
                         (cid,)).fetchone()[0] or 0
    content, atts = _rewind(db, cid, mid)
    if content is None:
        return jsonify({"error": "没有可重答的内容"}), 400
    new = (data.get("content") or "").strip()
    return jsonify({"content": new or content, "attachments": atts})


@bp.post("/api/aichat/chats/<int:cid>/branch")
def aichat_branch(cid):
    """从某条消息处分叉：复制这条之前的历史到一个新会话，原对话原样留着。

    比在同一条会话里存树省事得多，用户看到的效果一样：想换个问法比一比，
    两条对话并排在列表里，都能继续往下聊。
    """
    data = request.get_json(silent=True) or {}
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    mid = int(data.get("msg_id") or 0)
    rows = db.execute("SELECT role,content,kind,attach,meta FROM ai_msgs WHERE chat_id=?%s ORDER BY id"
                      % (" AND id<?" if mid else ""),
                      (cid, mid) if mid else (cid,)).fetchall()
    cur = db.execute("INSERT INTO ai_chats(user_id,project_id,title,tier) VALUES(?,?,?,?)",
                     (uid(), c["project_id"], (c["title"] or "对话")[:32] + " · 分支", _tier(c)))
    nid = cur.lastrowid
    for r in rows:
        db.execute("INSERT INTO ai_msgs(chat_id,role,content,kind,attach,meta) VALUES(?,?,?,?,?,?)",
                   (nid, r["role"], r["content"], r["kind"], r["attach"], r["meta"]))
    db.commit()
    return jsonify({"id": nid}), 201


@bp.delete("/api/aichat/chats/<int:cid>")
def aichat_del(cid):
    db = get_db()
    db.execute("DELETE FROM ai_msgs WHERE chat_id IN (SELECT id FROM ai_chats WHERE id=? AND user_id=?)", (cid, uid()))
    db.execute("DELETE FROM ai_chats WHERE id=? AND user_id=?", (cid, uid()))
    db.commit()
    return jsonify({"ok": True})


ATT_LIMIT = 8000        # 单轮注入的附件全文上限（字符）
CTX_BUDGET = 24000      # 上下文预算（字符口径，见 _fits）。DeepSeek 上下文远大于此，
                        # 这个数是「给历史留多少」的自律线：留太多既慢又贵，还容易
                        # 把真正相关的东西挤到模型注意力之外。
CTX_KEEP = 6            # 无论预算怎么算，最近这几条原文一定保留


def _size(s):
    """粗估这段文本占多少上下文。中文一个字≈1 token，英文≈4 字符 1 token；
    这里统一按字符数算，宁可高估——高估只是少放几条历史，低估会把请求撑爆。"""
    return len(s or "")


def _att_text(raw, limit=ATT_LIMIT):
    """把一条消息的 attach（JSON 列）摊成给模型看的附件正文。取不到就空串。"""
    try:
        atts = json.loads(raw or "[]")
    except Exception:
        return ""
    out, left = [], limit
    for a in atts if isinstance(atts, list) else []:
        t = (a.get("text") or "")[:max(0, left)]
        if not t:
            continue
        left -= len(t)
        out.append("【附件：%s】\n%s" % (a.get("name") or "文件", t))
    return "\n\n".join(out)


MEM_LIMIT = 20          # 一次最多带多少条记忆（够用了，多了反而喧宾夺主）


def _mem_grams(s):
    """中文没有空格，切成二字片段来比对；标点顺手扔掉。"""
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", (s or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _memories(db, u, q=""):
    """这个人的长期记忆，拼成给模型的一段。顺带记一次 hits（好让用户看到哪条真在起作用）。

    没超过 MEM_LIMIT 条就全带上——长期记忆本来就大多「跟这轮无关但一直成立」
    （「我考四川省考」不会因为这句没提就不成立），能全带就别挑。
    超了才需要取舍：先看跟这轮问话沾不沾边，再看新旧。原先是死板的
    `ORDER BY id DESC LIMIT 20`，记满之后一条天天用得上的老记忆会被新记忆挤出去，
    而且永远回不来。
    **不能按 hits 排**：hits 是「每轮给带进去的记忆都 +1」，本质是年龄，
    照它排等于把最老的二十条钉死在上下文里，新记的一条永远进不去。
    """
    rows = db.execute("SELECT id, text FROM ai_memories WHERE user_id=? ORDER BY id DESC",
                      (u,)).fetchall()
    if not rows:
        return ""
    if len(rows) > MEM_LIMIT:
        qg = _mem_grams(q)
        rows = sorted(rows, key=lambda r: (-len(_mem_grams(r["text"]) & qg), -r["id"]))[:MEM_LIMIT]
        rows.sort(key=lambda r: -r["id"])   # 挑完排回「新的在前」，每轮顺序才稳定
    try:
        db.execute("UPDATE ai_memories SET hits=hits+1 WHERE id IN (%s)"
                   % ",".join("?" * len(rows)), [r["id"] for r in rows])
        db.commit()
    except Exception:
        log.info("记忆计数失败（不影响对话）", exc_info=True)
    return ("\n\n【关于这位用户（长期记忆，他随时可以删）】\n"
            + "\n".join("· " + (r["text"] or "") for r in rows))


def _project_files(db, pid):
    """项目挂的参考资料。整段注入而不做检索：一个项目撑死挂几份，
    真到了要检索的量级再说——先能用，别为想象中的规模上索引。"""
    rows = db.execute("SELECT name, text FROM ai_project_files WHERE project_id=? ORDER BY id",
                      (pid,)).fetchall()
    if not rows:
        return ""
    out, left = [], 12000
    for r in rows:
        t = (r["text"] or "")[:max(0, left)]
        if not t:
            break
        left -= len(t)
        out.append("【项目资料：%s】\n%s" % (r["name"] or "资料", t))
    return ("\n\n" + "\n\n".join(out)) if out else ""


def _trace_brief(raw):
    """把一行工具轨迹压成给模型看的一句话（我上一轮调了什么、拿到了什么）。"""
    try:
        steps = json.loads(raw or "[]")
    except Exception:
        return ""
    out = []
    for s in steps if isinstance(steps, list) else []:
        out.append("· %s(%s) → %s" % (s.get("name") or "", _j_args(s.get("args")),
                                      (s.get("result") or "")[:160]))
    return ("（我上一轮已经查过/做过这些，别重复调用）\n" + "\n".join(out)) if out else ""


def _j_args(a):
    if not isinstance(a, dict):
        return ""
    return ", ".join("%s=%s" % (k, str(v)[:30]) for k, v in a.items() if k != "_confirmed")


def _build(cid, content, atts=None):
    """把一次提问拼成完整的 messages。返回 (db, 会话行, messages)，会话不存在则全 None。

    /send 和 /stream 共用这一份：提示词有一千多字、还带项目指令和用户概况，
    抄成两份迟早走样成「网页版的 AI 会用工具、APK 里的不会」。

    atts 是本轮新传的附件 [{name,text}]：**不拼进 content**（content 是要落库、要当标题、
    要显示给用户看的那一句），只在这一轮的 messages 里展开。历史里更早的附件只展开最近一条，
    再往前的退化成一行文件名——否则一篇 PDF 会在之后每一轮里重发一次。
    """
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return None, None, None
    sys_prompt = ("你是「公考助手」里的 AI 学习助理，服务正在备考公务员的用户。回答简洁、准确、条理清晰，用简体中文。\n"
                  "【排版要求】用 Markdown 让回答层次分明、重点突出：\n"
                  "· 用 `##`/`###` 小标题分段，用有序/无序列表列要点，别写成一大坨。\n"
                  "· **把关键结论、术语、重点内容加粗**（`**这样**`）—— 不只是加粗标题；比如给古诗词就把**整首诗**"
                  "或关键名句加粗突出，讲知识点就把**核心结论和易错点**加粗。\n"
                  "· 需要时用 `>` 引用来突出原文/诗句，用表格对比。\n"
                  "你能**真的操作这个应用**（通过给你的工具）：用户让你收录成语/词语就用 add_word 真的加进去、"
                  "让你打开某个功能就用 open_feature 打开、让你记笔记就用 create_note。别只是嘴上说做了 —— 要调用工具真做。做完再简短告诉用户结果。\n"
                  "【先查再答】你还有一整套**查询工具**能看见用户的真实数据：问「我错题/收录/小记里有什么」用 "
                  "list_wrong_questions / list_words / list_notes；问「今天复习什么/今天的任务/我的计划」用 "
                  "get_today_review / get_daily_tasks / get_plan_today；问「我的进度/正确率/坚持多少天」用 "
                  "get_study_stats / get_plan_progress / get_user_overview；找素材/古诗文/常识/时政用 "
                  "search_sucai / search_classics / search_changshi / get_daily_news；不确定东西在哪就用 "
                  "global_search。**凡是涉及用户个人数据的问题，一律先调查询工具拿到真实数字/内容再回答，绝不凭印象编。**\n"
                  "【动手改与删】你也能替用户改数据：补错题答案/解析用 update_wrong_question、收藏词/古诗文用 "
                  "star_word / star_classic、追加小记用 append_to_note、加每日任务用 add_daily_task、打卡任务/"
                  "完成计划用 complete_daily_task / complete_plan_item。这些改/删工具大多要 id —— 先用对应的"
                  "查询工具（list_wrong_questions / list_notes / get_daily_tasks / get_plan_today / search_classics）"
                  "拿到 id 再调。\n"
                  "【记住这个人】用户透露了**长期有效**的事——考哪个岗位/哪场考试、考试时间、长期的弱项与"
                  "目标、他要你以后怎么答（「解析写详细点」）——就用 remember_fact 记下来，以后每轮自动带上。"
                  "但**能查出来的数字不要记**（错题多少道、坚持多少天：那些每次用查询工具现算，记下来只会过期），"
                  "已经在【关于这位用户】里的也别重复记。系统会让用户点头确认，他不点就不会记。\n"
                  "【删除要确认】删除类（delete_entry / delete_wrong_question / delete_note）不可逆：除非用户这句话已"
                  "明确说了要删，否则**先不带 _confirmed 调用**——系统会让你确认，你就向用户复述「要删除的是 XX，确定吗？」"
                  "并停下等回答；等用户明确回「确定/删」，下一轮再带 _confirmed=true 调用真正删除。\n"
                  "【错题识别】当用户发来一段内容（常常是截图 OCR 出来的文字）时，判断它是不是一道完整的题目：\n"
                  "· 如果**确实是一道完整题目**（有题干，通常还有 A/B/C/D 选项），就用 add_wrong_question 把它加入错题本，"
                  "并顺手判断板块/题型、能定的话给出答案与简要解析；加完简短告诉用户已收录。\n"
                  "· 如果**拿不准这是不是题目**、或内容残缺（只有半道题、只是知识点/材料），**不要**调用工具，"
                  "而是用一句话反问用户：「这看起来像是……，需要我把它加入错题本吗？」等用户确认再决定。")
    if c["project_id"]:
        p = db.execute("SELECT * FROM ai_projects WHERE id=?", (c["project_id"],)).fetchone()
        if p and (p["instructions"] or "").strip():
            sys_prompt += "\n\n【本项目要求】" + p["instructions"].strip()
        sys_prompt += _project_files(db, c["project_id"])
    stats = _user_stats()
    if stats:
        sys_prompt += "\n\n" + stats
    sys_prompt += _memories(db, uid(), content)
    # kind='error' 的那几句是「本次回答失败」的占位，给用户留着看的，别回喂给模型。
    # 拉 80 条是**候选**，真正放多少由下面的预算决定 —— 原先是死板的 LIMIT 20：
    # 20 条闲聊才两千字，20 条里夹一篇附件就上万字，一边聊到第 21 轮就忘了开头，
    # 一边那篇全文每轮重发一次，钱和上下文两头亏。
    hist = db.execute("SELECT role, content, attach, kind, meta FROM ai_msgs WHERE chat_id=? "
                      "AND COALESCE(kind,'text')<>'error' ORDER BY id DESC LIMIT 80",
                      (cid,)).fetchall()
    msgs, att_left, used, dropped = [], 1, 0, 0
    for i, r in enumerate(hist):  # hist 是倒序的，所以先遇到的就是最近的那条
        if r["kind"] == "tool":
            # 工具轨迹回喂给模型：让它知道自己上一轮查过什么，别把同一个查询再调一遍
            body = _trace_brief(r["meta"])
            if not body:
                continue
            msgs.append({"role": "assistant", "content": body})
            used += _size(body)
            continue
        body = r["content"] or ""
        if r["attach"]:
            if att_left > 0:
                t = _att_text(r["attach"])
                if t:
                    body = t + "\n\n" + body
                    att_left -= 1
            else:
                body = "（此前上传过附件，内容不再重复附上）\n" + body
        # 预算用完就停：最近 CTX_KEEP 条无论如何都要带上（不然连刚说的话都接不上）
        if i >= CTX_KEEP and used + _size(body) > CTX_BUDGET:
            dropped = len(hist) - i
            break
        used += _size(body)
        msgs.append({"role": r["role"], "content": body})
    msgs.reverse()
    if dropped:
        # 不调 AI 做摘要（那要多花一次钱、还得等）——给一句结构化的交代就够模型知道
        # 「前面还聊过别的，需要的话可以问我」。真要回看，用户自己往上翻会话就行。
        msgs.insert(0, {"role": "user", "content":
                        "（这场对话更早还有 %d 条消息，因篇幅未附上；"
                        "如果我提到之前说过的事而你没有印象，直接问我。）" % dropped})
    cur = content
    if atts:
        t = _att_text(json.dumps(atts, ensure_ascii=False))
        if t:
            cur = t + "\n\n" + (content or "请阅读以上附件内容并帮我分析/讲解。")
    msgs.append({"role": "user", "content": cur})
    return db, c, [{"role": "system", "content": sys_prompt}] + msgs


def _persist(db, cid, c, content, reply, atts=None, kind="", trace=None):
    """落库：用户这句 +（工具轨迹）+ AI 那句，顺带给还没标题的会话起个名。

    返回 {"title", "user_mid", "msg_id"}。**两个 id 必须带回前端**：前端本地那份
    aiMsgs 是自己 push 的、没有 id，「改问题」和「分支」拿 m.id 就是 undefined，
    退化成 msg_id=0 → 服务端按「最后一轮」处理 —— 改第一个问题会把后面几轮
    一起删掉，还不吭声。

    content 是**用户屏幕上看到的那一句**（附件只留文件名），附件全文单独进 attach 列。
    kind='error' 标记「这句是失败占位」，重建上下文时会跳过它。
    trace 是这一轮的工具调用轨迹，单独存一行 kind='tool'：既给界面回放，也回喂给模型。
    """
    cur = db.execute("INSERT INTO ai_msgs(chat_id,role,content,attach) VALUES(?,?,?,?)",
                     (cid, "user", content, json.dumps(atts, ensure_ascii=False) if atts else None))
    user_mid = cur.lastrowid
    if trace:
        db.execute("INSERT INTO ai_msgs(chat_id,role,content,kind,meta) VALUES(?,?,?,?,?)",
                   (cid, "assistant", "", "tool", json.dumps(trace, ensure_ascii=False)))
    cur = db.execute("INSERT INTO ai_msgs(chat_id,role,content,kind) VALUES(?,?,?,?)",
                     (cid, "assistant", reply, kind or "text"))
    asst_mid = cur.lastrowid
    title = c["title"]
    if not title:
        title = (content or "新对话")[:24]
        db.execute("UPDATE ai_chats SET title=? WHERE id=?", (title, cid))
    db.execute("UPDATE ai_chats SET updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    db.commit()
    return {"title": title, "user_mid": user_mid, "msg_id": asst_mid}


def _tier(c):
    """这个会话用哪个档位。pro=深度（推理模型，慢但想得清楚），默认 fast。
    以前这里是写死的 fast —— 分析一道判断推理和回一句「好的」用的是同一个模型。"""
    try:
        return "pro" if (c["tier"] or "fast") == "pro" else "fast"
    except (IndexError, KeyError):
        return "fast"


def _req_atts(data):
    """请求里带的附件：[{name,text}]，挡掉畸形和超大的。"""
    raw = data.get("attachments")
    if not isinstance(raw, list):
        return []
    out = []
    for a in raw[:6]:
        if not isinstance(a, dict):
            continue
        img = str(a.get("image") or "")[:120]
        if (a.get("text") or "").strip() or img:
            out.append({"name": str(a.get("name") or "文件")[:80],
                        "text": (a.get("text") or "")[:ATT_LIMIT], "image": img})
    return out


def _vision_answer(atts, content):
    """本轮带了图片 → 把**原图**交给视觉模型，而不是只拿抽出来的文字问。

    图形推理、资料分析的图表，文字抽取那一步就把版面和图形丢了 —— 行测两个大板块
    恰恰全在图里。代价是这一轮用不了工具（视觉接口不带 function calling），
    问图的时候通常也不需要工具，够用。

    返回 (reply, None) 或 (None, 错误响应)。视觉没配 / 图没了就返回 (None, None)
    让调用方退回普通文本路径。
    """
    paths = [p for p in (ai_img_path(a.get("image")) for a in atts if a.get("image")) if p]
    if not paths or not vision_configured():
        return None, None
    # 抽出来的文字一并给过去：模型看图 + 看 OCR，比只给其中一样准
    ocr = "\n\n".join("【%s 的文字识别结果，仅供参考】\n%s" % (a.get("name") or "图片", a["text"])
                      for a in atts if a.get("text"))
    q = (content or "看看这道题，讲讲怎么做。")
    prompt = ("你是「公考助手」里的 AI 学习助理，服务备考公务员的用户。用简体中文、Markdown 作答，"
              "把**关键结论和易错点加粗**。这是用户发来的题目图片（可能是图形推理、资料分析图表或"
              "试卷截图）：请先看清图本身（图形的形状、数量、位置、对称性；图表的坐标和数值），"
              "再作答。\n\n用户的问题：" + q + ("\n\n" + ocr if ocr else ""))
    try:
        reply = vision_chat(prompt, paths[:3], prefer="pro", temperature=0.3, max_tokens=2000)
    except Exception as e:
        log.warning("视觉问答失败：%r", e)
        return None, (jsonify({"error": aiclient.error_message(e)}), 502)
    return (reply or "").strip(), None


@bp.post("/api/aichat/chats/<int:cid>/send")
def aichat_send(cid):
    """非流式：整段回复一次性返回。老 WebView（没有 ReadableStream）走这条。"""
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    atts = _req_atts(data)
    if not content and not atts:
        return jsonify({"error": "请输入内容"}), 400
    db, c, full = _build(cid, content, atts)
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    # 带图的这一轮走视觉模型（看得见图形和图表，代价是这轮没有工具）
    vreply, verr = _vision_answer(atts, content)
    if verr:
        return verr
    if vreply:
        saved = _persist(db, cid, c, content, vreply, atts)
        return jsonify({"reply": vreply, "actions": [], "trace": [], **saved})
    reply, actions, trace, err = _ai_agentic_or_error(full, db, temperature=0.6, max_tokens=2000,
                                                      tier=_tier(c))
    if err:
        return err
    saved = _persist(db, cid, c, content, reply, atts, trace=trace)
    return jsonify({"reply": reply, "actions": actions, "trace": trace, **saved})


@bp.post("/api/aichat/chats/<int:cid>/stream")
def aichat_stream(cid):
    """流式：边生成边推，前端一两秒内就见字。

    用 POST + SSE 而不是 EventSource：EventSource 只能 GET，问题文本可以很长
    （截图 OCR 出来的整道题），塞 query string 会被各段代理截断。前端用
    fetch + ReadableStream 读，读不动的老 WebView 自己退回上面的 /send。

    落库放在生成器末尾：响应头早发出去了，这里再出错也改不了状态码，
    所以错误一律走 event:error 推给前端，别指望 HTTP 状态。
    """
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    atts = _req_atts(data)
    if not content and not atts:
        return jsonify({"error": "请输入内容"}), 400
    _, c, full = _build(cid, content, atts)
    if not c:
        return jsonify({"error": "会话不存在"}), 404

    def sse(kind, obj):
        return "event: %s\ndata: %s\n\n" % (kind, json.dumps(obj, ensure_ascii=False))

    def gen():
        # 自己开一条连接，**并且顶掉 g 上那条**：响应体是边算边发的，跑到一半时视图函数
        # 早返回了，g 上那条已经随应用上下文 teardown 关掉，再用就是
        # "Cannot operate on a closed database."。
        # 光把新连接传给 ai_chat_agentic_stream 不够——工具底下的 core.lookup()、
        # current_user() 这些是自己去 get_db() 的，几十处，一个个改不现实也迟早漏。
        db = g._db = open_db()
        buf, saved = [], False
        try:
            # 带图：走视觉模型。它不是流式的，所以一次性把整段推出去（前端照常收 done）
            vreply, verr = _vision_answer(atts, content)
            if verr or vreply:
                if verr:
                    yield sse("error", {"error": verr[0].get_json().get("error", "看图失败")})
                    return
                yield sse("delta", vreply)
                yield sse("done", {"reply": vreply, "actions": [], "trace": [], "truncated": False,
                                   **_persist(db, cid, c, content, vreply, atts)})
                saved = True
                return
            for kind, p in ai_chat_agentic_stream(full, db, temperature=0.6, max_tokens=2000,
                                                  tier=_tier(c)):
                if kind == "delta":
                    buf.append(p)
                if kind == "done":
                    p.update(_persist(db, cid, c, content, p["reply"], atts,
                                      trace=p.get("trace")))
                    saved = True
                yield sse(kind, p)
        except Exception as e:
            log.warning("AI 流式对话失败：%r", e)
            # 一个字都没吐出来就失败时，连**用户自己问的那句**也没落库过（落库在
            # done 分支）。用户看到一句报错，回头再进这个会话，自己问过什么都没了，
            # 只能重打一遍。所以这里把这一轮补齐：问题照留，答案写清楚是怎么失败的。
            if not saved:
                # 已经吐出去的半截答案要一起留下——用户屏幕上看见了，刷新后就该还在。
                half = "".join(buf).strip()
                try:
                    # kind='error'：这句留给用户看，但不进下一轮上下文（模型会当成自己答过的话）
                    _persist(db, cid, c, content,
                             (half + "\n\n" if half else "")
                             + "（本次回答失败：%s）" % aiclient.error_message(e),
                             atts, kind="error")
                    saved = True
                except Exception:
                    log.warning("AI 对话失败后补存问题失败", exc_info=True)
            yield sse("error", {"error": aiclient.error_message(e)})
        finally:
            # 手机切后台、隧道抖一下，客户端就不读了 —— 这里会被 GeneratorExit 打断，
            # 上面的 done 分支根本走不到。可工具的副作用（词已入库）是**已经发生**的事实，
            # 这一轮要是不落库，用户回头看只见自己问了、AI 没答，再问一遍就重复收录。
            if not saved and buf:
                try:
                    _persist(db, cid, c, content,
                             "".join(buf).strip() + "\n\n（连接中断，回答可能不完整）", atts)
                except Exception:
                    log.warning("AI 对话中断后补存失败", exc_info=True)
            db.close()
            g._db = None      # teardown 会再 close 一次，别让它拿着已关的连接

    resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"   # 别让中间代理攒着不发，那就白流式了
    return resp


@bp.post("/api/aichat/chats/<int:cid>/title")
def aichat_title(cid):
    """给会话起个像样的名字。

    原先标题是把用户第一句话切前 24 字（碰上附件那种就更难看）。这里让模型概括一句。
    **单独一个接口、由前端在回答显示完之后再调**：起名是次要的，不能拖慢回答。
    失败就保持原样，不报错——名字不好看是小事，别为它打断用户。
    """
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    rows = db.execute("SELECT role, content FROM ai_msgs WHERE chat_id=? AND COALESCE(kind,'text')='text' "
                      "ORDER BY id LIMIT 2", (cid,)).fetchall()
    if not rows:
        return jsonify({"title": c["title"] or ""})
    talk = "\n".join("%s：%s" % ("我" if r["role"] == "user" else "助手", (r["content"] or "")[:300])
                     for r in rows)
    try:
        title = (aiclient.chat(
            [{"role": "system", "content": "给下面这段对话起个标题，只回标题本身：不超过 12 个汉字，"
                                           "不要引号、不要标点、不要「关于」这类废话。"},
             {"role": "user", "content": talk}],
            tier="fast", temperature=0.3, max_tokens=32, cfg=CFG) or "").strip()
    except Exception as e:
        log.info("会话起名失败（不影响使用）：%r", e)
        return jsonify({"title": c["title"] or ""})
    title = title.replace("\n", " ").strip("　 「」\"'.。")[:24]
    if not title:
        return jsonify({"title": c["title"] or ""})
    db.execute("UPDATE ai_chats SET title=? WHERE id=?", (title, cid))
    db.commit()
    return jsonify({"title": title})


@bp.post("/api/aichat/chats/<int:cid>/confirm")
def aichat_confirm(cid):
    """用户在前端点了确认后走这里：确定性地执行那次待确认的操作
    （删数据，或把一件事写进长期记忆）。

    不走「再发一句『确定』让模型自己重调」——那不可靠。前端把 AI 之前回的
    confirm 动作 {tool,args} 原样带回来，这里补 _confirmed 直接执行，只放行
    确实注册为 confirm=True 的工具（防止拿它绕过去调别的）。"""
    data = request.get_json(silent=True) or {}
    tool = (data.get("tool") or "").strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    db = get_db()
    c = db.execute("SELECT id FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
    t = TOOL_REGISTRY.get(tool)
    if not t or not t.get("confirm"):
        return jsonify({"error": "该操作无需确认或不存在"}), 400
    result, action = exec_tool(tool, dict(args, _confirmed=True), db)
    # 把「确认 → 已执行」记进会话历史，让上下文连贯（下轮 AI 知道已经删了/已经记下了）。
    # 这句按工具来，不能写死成「确认删除」——记忆也走这条确认路径。
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)",
               (cid, "user", "确认" + tool_label(tool)))
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "assistant", result))
    db.execute("UPDATE ai_chats SET updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    db.commit()
    return jsonify({"reply": result, "actions": [action] if action else []})


@bp.get("/api/aichat/memories")
def aimem_list():
    rows = get_db().execute(
        "SELECT id, kind, text, source, hits, created_at FROM ai_memories "
        "WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    return jsonify({"memories": [dict(r) for r in rows]})


@bp.post("/api/aichat/memories")
def aimem_add():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()[:200]
    if not text:
        return jsonify({"error": "请输入要记住的内容"}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM ai_memories WHERE user_id=? AND text=?", (uid(), text)).fetchone():
        return jsonify({"ok": True, "dup": True})       # 记过了就别再记一条一模一样的
    cur = db.execute("INSERT INTO ai_memories(user_id,kind,text,source) VALUES(?,?,?,?)",
                     (uid(), (data.get("kind") or "fact")[:10], text,
                      (data.get("source") or "手动添加")[:60]))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.delete("/api/aichat/memories/<int:mid>")
def aimem_del(mid):
    db = get_db()
    db.execute("DELETE FROM ai_memories WHERE id=? AND user_id=?", (mid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/api/aichat/opener")
def aichat_opener():
    """打开助手时的主动开场：基于今天的复习和错题给一句判断 + 几个可点的起手式。

    **不调模型**——开场白要立刻出现，为它等两秒就本末倒置了；这些数字本来就在库里。
    """
    db = get_db()
    u = uid()
    if not u:
        return jsonify({"greet": "", "chips": []})
    try:
        due = db.execute("SELECT COUNT(*) FROM review_state WHERE user_id=? AND next_due<=date('now','localtime')",
                         (u,)).fetchone()[0]
    except Exception:
        due = 0
    try:
        wq = db.execute("SELECT COUNT(*) FROM wrong_questions WHERE user_id=? "
                        "AND created_at>=datetime('now','localtime','-3 day')", (u,)).fetchone()[0]
    except Exception:
        wq = 0
    h = int(__import__("datetime").datetime.now().strftime("%H"))
    hello = "早上好" if h < 11 else ("下午好" if h < 18 else "晚上好")
    bits = []
    if due:
        bits.append("今天还有 %d 条要复习" % due)
    if wq:
        bits.append("最近三天新添了 %d 道错题" % wq)
    greet = "👋 %s%s" % (hello, "，" + "；".join(bits) if bits else "，今天想从哪开始？")
    chips = []
    if due:
        chips.append("过一遍今天要复习的")
    if wq:
        chips.append("讲讲我最近错的题")
    chips += ["我的备考进度怎么样", "出几道题练练"]
    return jsonify({"greet": greet, "chips": chips[:4]})


@bp.get("/api/aichat/projects/<int:pid>/files")
def aipf_list(pid):
    rows = get_db().execute(
        "SELECT id, name, LENGTH(text) size, created_at FROM ai_project_files "
        "WHERE project_id=? AND user_id=? ORDER BY id", (pid, uid())).fetchall()
    return jsonify({"files": [dict(r) for r in rows]})


@bp.post("/api/aichat/projects/<int:pid>/files")
def aipf_add(pid):
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "没有内容"}), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM ai_projects WHERE id=? AND user_id=?", (pid, uid())).fetchone():
        return jsonify({"error": "项目不存在"}), 404
    cur = db.execute("INSERT INTO ai_project_files(project_id,user_id,name,text) VALUES(?,?,?,?)",
                     (pid, uid(), (data.get("name") or "资料")[:80], text[:60000]))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.delete("/api/aichat/projects/<int:pid>/files/<int:fid>")
def aipf_del(pid, fid):
    db = get_db()
    db.execute("DELETE FROM ai_project_files WHERE id=? AND project_id=? AND user_id=?",
               (fid, pid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/aichat/projects")
def aiproj_new():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "请输入项目名"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO ai_projects(user_id,name,instructions) VALUES(?,?,?)",
                     (uid(), name, (data.get("instructions") or "").strip()))
    db.commit()
    return jsonify({"id": cur.lastrowid, "name": name}), 201


@bp.delete("/api/aichat/projects/<int:pid>")
def aiproj_del(pid):
    db = get_db()
    db.execute("UPDATE ai_chats SET project_id=NULL WHERE project_id=? AND user_id=?", (pid, uid()))
    db.execute("DELETE FROM ai_projects WHERE id=? AND user_id=?", (pid, uid()))
    db.commit()
    return jsonify({"ok": True})
