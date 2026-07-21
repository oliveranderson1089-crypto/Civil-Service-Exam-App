"""全局 AI 会话中心：跨页面的对话历史。


"""

from flask import Blueprint, jsonify, request

from core import get_db, uid
from mods.agent import _ai_agentic_or_error
from mods.agent_tools import TOOL_REGISTRY, exec_tool
from mods.aichat import _user_stats

bp = Blueprint("aisession", __name__)


@bp.get("/api/aichat/home")
def aichat_home():
    db = get_db()
    db.execute("DELETE FROM ai_chats WHERE user_id=? AND created_at < datetime('now','localtime','-1 hour') "
               "AND NOT EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=ai_chats.id)", (uid(),))
    db.commit()
    chats = db.execute(
        "SELECT c.id, c.title, c.updated_at, c.project_id, c.starred, p.name pname FROM ai_chats c "
        "LEFT JOIN ai_projects p ON p.id=c.project_id "
        "WHERE c.user_id=? AND EXISTS(SELECT 1 FROM ai_msgs m WHERE m.chat_id=c.id) "
        "ORDER BY c.starred DESC, c.updated_at DESC LIMIT 50", (uid(),)).fetchall()
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
    msgs = db.execute("SELECT role, content FROM ai_msgs WHERE chat_id=? ORDER BY id", (cid,)).fetchall()
    return jsonify({"id": c["id"], "title": c["title"], "project_id": c["project_id"],
                    "msgs": [dict(r) for r in msgs]})


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
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/api/aichat/chats/<int:cid>")
def aichat_del(cid):
    db = get_db()
    db.execute("DELETE FROM ai_msgs WHERE chat_id IN (SELECT id FROM ai_chats WHERE id=? AND user_id=?)", (cid, uid()))
    db.execute("DELETE FROM ai_chats WHERE id=? AND user_id=?", (cid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/aichat/chats/<int:cid>/send")
def aichat_send(cid):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "请输入内容"}), 400
    db = get_db()
    c = db.execute("SELECT * FROM ai_chats WHERE id=? AND user_id=?", (cid, uid())).fetchone()
    if not c:
        return jsonify({"error": "会话不存在"}), 404
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
    stats = _user_stats()
    if stats:
        sys_prompt += "\n\n" + stats
    hist = db.execute("SELECT role, content FROM ai_msgs WHERE chat_id=? ORDER BY id DESC LIMIT 20",
                      (cid,)).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(hist)]
    msgs.append({"role": "user", "content": content})
    reply, actions, err = _ai_agentic_or_error(
        [{"role": "system", "content": sys_prompt}] + msgs, db, temperature=0.6, max_tokens=2000)
    if err:
        return err
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "user", content))
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "assistant", reply))
    title = c["title"]
    if not title:
        title = content[:24]
        db.execute("UPDATE ai_chats SET title=? WHERE id=?", (title, cid))
    db.execute("UPDATE ai_chats SET updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    db.commit()
    return jsonify({"reply": reply, "title": title, "actions": actions})


@bp.post("/api/aichat/chats/<int:cid>/confirm")
def aichat_confirm(cid):
    """用户在前端点了「确认删除」后走这里：确定性地执行那次待确认的破坏性操作。

    不走「再发一句『确定』让模型自己重调」——那不可靠。前端把 AI 之前回的
    confirm 动作 {tool,args} 原样带回来，这里补 _confirmed 直接执行，只放行
    确实注册为 confirm=True 的删除类工具（防止拿它绕过去调别的）。"""
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
    # 把「确认 → 已执行」记进会话历史，让上下文连贯（下轮 AI 知道已经删了）
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "user", "确认删除"))
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)", (cid, "assistant", result))
    db.execute("UPDATE ai_chats SET updated_at=datetime('now','localtime') WHERE id=?", (cid,))
    db.commit()
    return jsonify({"reply": result, "actions": [action] if action else []})


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
