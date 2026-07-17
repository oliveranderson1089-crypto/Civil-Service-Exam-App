"""全文搜索：跨板块找内容。


"""
import json
import os
import re

from flask import Blueprint, jsonify, request

from core import UPLOADS, get_db, log, uid
from mods.annots import _ann_sentence, _ann_where
from mods.files import INLINE_EXT, OFFICE_EXT, TEXT_EXT
from mods.notes import _get_note, _jl, _note_dict

bp = Blueprint("search", __name__)


def _snippet(text, q, span=42):
    if not text:
        return ""
    low = text.lower()
    i = low.find(q.lower())
    if i < 0:
        return (text[:90].replace("\n", " ")).strip()
    start = max(0, i - span)
    end = min(len(text), i + len(q) + span)
    s = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def _block_text(b):
    t = re.sub(r"<[^>]+>", "", b.get("text", "") or "")
    data = b.get("data") or {}
    if b.get("type") == "table":
        for row in (data.get("rows") or []):
            t += " " + " ".join(str(c) for c in row)
    return t


@bp.get("/api/notes/<int:nid>")
def note_get(nid):
    n = _get_note(nid)
    if not n:
        return jsonify({"error": "未找到"}), 404
    return jsonify(_note_dict(n))


@bp.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    ql = q.lower()
    db = get_db()
    results = []
    # 小记
    for r in db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        content = r["content"] or ""
        tags = _jl(r, "tags")
        todos = " ".join(t.get("text", "") for t in _jl(r, "todos"))
        hay = content + " " + " ".join(tags) + " " + todos
        if ql in hay.lower():
            results.append({"type": "note", "id": r["id"],
                            "title": (content[:24].strip() or "（图片/附件小记）"),
                            "snippet": _snippet(content or todos, q),
                            "tags": tags, "board": r["board"] or ""})
    # 资料库（文本类读内容搜，其它搜文件名/标题）
    for r in db.execute("SELECT * FROM materials WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        name = (r["title"] or "") + " " + (r["orig_name"] or "")
        body = ""
        if r["ext"] in TEXT_EXT or r["ext"] in (".html", ".htm"):
            try:
                p = os.path.join(UPLOADS, str(uid()), r["stored_name"])
                with open(p, encoding="utf-8", errors="ignore") as fp:
                    body = fp.read()
            except Exception:
                body = ""
        hit_body = body and ql in body.lower()
        if ql in name.lower() or hit_body:
            results.append({"type": "material", "id": r["id"],
                            "title": r["title"] or r["orig_name"], "ext": r["ext"],
                            "viewable": (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT) or (r["ext"] in TEXT_EXT),
                            "board": r["board"] or "",
                            "snippet": _snippet(body, q) if hit_body else ""})
    # 知识库文档
    nb_names = {row["id"]: row["name"] for row in
                db.execute("SELECT id,name FROM notebooks WHERE user_id=?", (uid(),)).fetchall()}
    for r in db.execute("SELECT * FROM kb_nodes WHERE user_id=? AND type='doc'", (uid(),)).fetchall():
        title = r["title"] or ""
        body = " ".join(_block_text(b) for b in _jl(r, "content"))
        hay = title + " " + body
        if ql in hay.lower():
            results.append({"type": "doc", "id": r["id"], "notebook_id": r["notebook_id"],
                            "notebook": nb_names.get(r["notebook_id"], ""),
                            "title": title or "无标题文档", "snippet": _snippet(body, q)})
    # 错题本
    for r in db.execute("SELECT * FROM wrong_questions WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        hay = " ".join(str(r[k] or "") for k in ("question", "points", "method", "skill", "steps", "note", "qtype", "board"))
        if ql in hay.lower():
            qtext = (r["question"] or "").strip()
            results.append({"type": "wrongq", "id": r["id"],
                            "title": (qtext[:26] or "（图片错题）"),
                            "board": r["board"] or r["qtype"] or "",
                            "snippet": _snippet(qtext or r["points"] or "", q)})
    # 基础知识点（各板块 · 全站共享）+ 我的补充
    for r in db.execute("SELECT * FROM board_kb").fetchall():
        body = r["content"] or ""
        if ql in body.lower() or ql in (r["board"] or "").lower():
            results.append({"type": "boardkb", "id": 0, "board": r["board"],
                            "title": (r["board"] or "") + " · 基础知识点",
                            "snippet": _snippet(body, q)})
    for r in db.execute("SELECT * FROM board_points WHERE user_id=?", (uid(),)).fetchall():
        if ql in (r["content"] or "").lower():
            results.append({"type": "boardkb", "id": 0, "board": r["board"],
                            "title": (r["board"] or "") + " · 我的补充",
                            "snippet": _snippet(r["content"] or "", q)})
    like = "%" + q + "%"
    # 每日时政
    for r in db.execute("SELECT id,title,board,pub_date,content,ai_summary FROM news_items "
                        "WHERE title LIKE ? OR content LIKE ? OR ai_summary LIKE ? "
                        "ORDER BY id DESC LIMIT 15", (like, like, like)):
        body = r["content"] or r["ai_summary"] or ""
        results.append({"type": "news", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["board"] or "时政", r["pub_date"] or ""),
                        "snippet": _snippet(body if ql in body.lower() else r["title"], q)})
    # 时政要文库（全文+AI解读）
    for r in db.execute("SELECT id,title,category,content,interpretation FROM policy_docs "
                        "WHERE title LIKE ? OR content LIKE ? OR interpretation LIKE ? LIMIT 10",
                        (like, like, like)):
        body = r["content"] or ""
        if ql not in body.lower():
            body = r["interpretation"] or r["title"]
        results.append({"type": "policydoc", "id": r["id"], "title": r["title"],
                        "board": r["category"] or "要文", "snippet": _snippet(body, q)})
    # 党的创新理论学习词典
    for r in db.execute("SELECT id,term,cat,content FROM party_dict "
                        "WHERE term LIKE ? OR content LIKE ? LIMIT 15", (like, like)):
        results.append({"type": "partydict", "id": r["id"], "title": r["term"],
                        "board": r["cat"] or "", "snippet": _snippet(r["content"] or "", q)})
    # 古诗文库
    for r in db.execute("SELECT id,title,author,category,content FROM classics "
                        "WHERE title LIKE ? OR content LIKE ? OR author LIKE ? LIMIT 15",
                        (like, like, like)):
        results.append({"type": "classic", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["category"] or "", r["author"] or ""),
                        "snippet": _snippet(r["content"] or "", q)})
    # 常识积累
    for r in db.execute("SELECT id,board,topic,title,content FROM changshi_items "
                        "WHERE title LIKE ? OR content LIKE ? LIMIT 15", (like, like)):
        results.append({"type": "changshi", "id": r["id"], "title": r["title"],
                        "board": "%s · %s" % (r["board"], r["topic"]),
                        "cs_board": r["board"], "cs_topic": r["topic"],
                        "snippet": _snippet(r["content"] or "", q)})
    # 写作素材 / 衔接表达
    for r in db.execute("SELECT id,kind,topic,content,date FROM sucai_items "
                        "WHERE topic LIKE ? OR content LIKE ? LIMIT 10", (like, like)):
        results.append({"type": "sucai", "id": r["id"], "title": (r["topic"] or r["kind"]),
                        "board": "%s · %s" % (r["kind"], r["date"] or ""), "kind": r["kind"],
                        "snippet": _snippet(r["content"] or "", q)})
    # 概括句
    try:
        for r in db.execute("SELECT id,topic,raw,sentence FROM gaikuo_items "
                            "WHERE topic LIKE ? OR sentence LIKE ? OR raw LIKE ? LIMIT 10",
                            (like, like, like)):
            results.append({"type": "gaikuo", "id": r["id"], "title": r["topic"] or "概括句",
                            "board": "概括句积累", "snippet": _snippet(r["sentence"] or r["raw"] or "", q)})
    except Exception:
        log.exception("搜索的概括句分支出错：结果里会静默少这一类")
    # 我的成语词语收录
    for r in db.execute("SELECT id,word,category,explanation FROM entries "
                        "WHERE user_id=? AND (word LIKE ? OR explanation LIKE ? OR note LIKE ?) LIMIT 10",
                        (uid(), like, like, like)):
        results.append({"type": "entry", "id": r["id"], "title": r["word"],
                        "board": r["category"] or "收录", "snippet": _snippet(r["explanation"] or "", q)})
    # 草稿本（笔迹不识别，只能按本子名搜）
    for r in db.execute("SELECT id,title,pages,updated_at FROM drafts WHERE user_id=? AND title LIKE ? "
                        "ORDER BY updated_at DESC LIMIT 10", (uid(), like)):
        results.append({"type": "draft", "id": r["id"], "title": r["title"] or "未命名草稿",
                        "board": "草稿本 · %d 页" % (r["pages"] or 1),
                        "snippet": "最近更新 " + (r["updated_at"] or "")[:16]})
    # 范文（题干 / 参考答案）
    for r in db.execute("SELECT e.id, e.type_name, e.stem, e.answer, p.topic, p.title "
                        "FROM essays e LEFT JOIN essay_papers p ON p.id=e.paper_id "
                        "WHERE e.stem LIKE ? OR e.answer LIKE ? OR p.topic LIKE ? OR p.title LIKE ? LIMIT 10",
                        (like, like, like, like)):
        body = r["answer"] or ""
        results.append({"type": "essay", "id": r["id"],
                        "title": "%s · %s" % (r["title"] or r["topic"] or "范文", r["type_name"] or ""),
                        "board": "范文推荐 · AI 仿真卷（非真题）",
                        "snippet": _snippet(body if ql in body.lower() else (r["stem"] or ""), q)})
    # 应用文上位词（场景规范表述）
    for r in db.execute("SELECT id,scene,phrases,doctype,note,example FROM gongwen_items "
                        "WHERE scene LIKE ? OR phrases LIKE ? OR doctype LIKE ? OR note LIKE ? OR example LIKE ? "
                        "LIMIT 10", (like, like, like, like, like)):
        results.append({"type": "gongwen", "id": r["id"], "title": r["scene"] or "应用文表述",
                        "board": "应用文上位词 · " + (r["doctype"] or ""), "term": r["scene"] or "",
                        "snippet": _snippet(r["phrases"] or r["note"] or r["example"] or "", q)})
    # 上位词（常考·逻辑填空）
    for r in db.execute("SELECT id,hyper,subs,note FROM hyper_items "
                        "WHERE hyper LIKE ? OR subs LIKE ? OR note LIKE ? OR example LIKE ? LIMIT 10",
                        (like, like, like, like)):
        results.append({"type": "changkao", "id": r["id"], "title": r["hyper"] or "上位词",
                        "board": "常考 · 上位词", "ck_board": "上位词",
                        "snippet": _snippet(r["subs"] or r["note"] or "", q)})
    # 习语金句
    for r in db.execute("SELECT id,quote,note,category,apply FROM xiyu_items "
                        "WHERE quote LIKE ? OR note LIKE ? OR apply LIKE ? OR keyword LIKE ? LIMIT 10",
                        (like, like, like, like)):
        results.append({"type": "xiyu", "id": r["id"], "title": (r["quote"] or "")[:30],
                        "board": "习语金句 · " + (r["category"] or ""),
                        "snippet": _snippet(r["note"] or r["apply"] or "", q)})
    # 常考（高频成语/实词/提法…）
    for r in db.execute("SELECT id,board,title,content,note FROM changkao_items "
                        "WHERE title LIKE ? OR content LIKE ? OR note LIKE ? LIMIT 15", (like, like, like)):
        results.append({"type": "changkao", "id": r["id"], "title": r["title"] or "常考",
                        "board": "常考 · " + (r["board"] or ""), "ck_board": r["board"] or "",
                        "snippet": _snippet(r["content"] or r["note"] or "", q)})
    # 理论基础（马原/毛概/中特/习思想）
    for r in db.execute("SELECT id,board,topic,title,content FROM theory_items "
                        "WHERE title LIKE ? OR content LIKE ? OR topic LIKE ? LIMIT 15", (like, like, like)):
        results.append({"type": "theory", "id": r["id"], "title": r["title"] or r["topic"] or "理论",
                        "board": "理论基础 · " + (r["board"] or ""), "th_board": r["board"] or "",
                        "snippet": _snippet(r["content"] or "", q)})
    # 经典著作（毛选等）
    for r in db.execute("SELECT id,book,title,content,interpretation FROM works "
                        "WHERE title LIKE ? OR content LIKE ? OR interpretation LIKE ? LIMIT 10",
                        (like, like, like)):
        body = r["content"] or ""
        results.append({"type": "work", "id": r["id"], "title": r["title"] or "篇目",
                        "board": "经典著作 · " + (r["book"] or ""),
                        "snippet": _snippet(body if ql in body.lower() else (r["interpretation"] or ""), q)})
    # 手写批注：搜「我在哪儿圈过这句话」。锚里存着压着的原文（PDF 的取自 textLayer），
    # 所以这里搜的是**你标过的内容**，不只是文件名。同一处只出一条（一句话上可能划了好几笔）。
    seen_ann = set()
    for r in db.execute("SELECT id,target,anchor_type,anchor FROM annotations "
                        "WHERE user_id=? AND anchor LIKE ? ORDER BY id DESC LIMIT 200",
                        (uid(), like)):
        try:
            a = json.loads(r["anchor"] or "{}")
        except Exception:
            continue
        quote = (a.get("quote") or "").strip()
        if not quote or ql not in quote.lower():
            continue
        sent = _ann_sentence(a) or quote        # 同一段上的好几笔＝同一处，按句子去重（见 _ann_sentence）
        key = (r["target"], sent)
        if key in seen_ann:
            continue
        seen_ann.add(key)
        where, mat = _ann_where(db, uid(), r["target"])
        if a.get("page"):
            where += " · 第 %d 页" % a["page"]
        results.append({"type": "annot", "id": r["id"], "title": sent[:40],
                        "board": where, "target": r["target"], "mat": mat,
                        "snippet": _snippet((a.get("prefix") or "") + quote + (a.get("suffix") or ""), q)})
        if len(seen_ann) >= 12:
            break
    return jsonify({"results": results, "q": q})
