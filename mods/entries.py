"""成语 / 词语积累：按用户隔离的收录本。


"""

from flask import Blueprint, jsonify, request

from core import get_db, lookup, row_to_dict, uid
from mods.agent import _gen_ai_explanation
from mods.changkao import CK_TO_ENTRY

bp = Blueprint("entries", __name__)


@bp.get("/api/lookup")
def api_lookup():
    return jsonify(lookup(request.args.get("word", "")))


@bp.post("/api/lookup/ai")
def api_lookup_ai():
    """词典未收录时用 AI 解释，写入全局 ci_ai 缓存（此后 lookup 可直接命中）。"""
    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入词语"}), 400
    db = get_db()
    cached = db.execute("SELECT * FROM ci_ai WHERE word=?", (word,)).fetchone()
    if cached and not data.get("force"):
        ck = cached.keys()
        return jsonify({"word": word, "pinyin": cached["pinyin"], "category": cached["category"],
                        "explanation": cached["explanation"] or "",
                        "derivation": (cached["derivation"] if "derivation" in ck else "") or "",
                        "example": (cached["example"] if "example" in ck else "") or "",
                        "found": True, "cached": True})
    gen = _gen_ai_explanation(db, word, data.get("category") or "")
    cat, py = gen["category"], gen["pinyin"]
    exp, der, exa = gen["explanation"], gen["derivation"], gen["example"]
    # 重新生成(force)时，同步刷新该用户已收录的同名词条（保留其笔记），
    # 让「重新生成」对已收录条目真正生效，覆盖历史未规范化的旧解释。
    if data.get("force"):
        db.execute("UPDATE entries SET pinyin=?, category=?, explanation=?, derivation=?, example=? "
                   "WHERE user_id=? AND word=?", (py, cat, exp, der, exa, uid(), word))
        db.commit()
    return jsonify({"word": word, "pinyin": py, "category": cat, "explanation": exp,
                    "derivation": der, "example": exa, "found": True, "cached": False})


@bp.post("/api/entries")
def api_add():
    data = request.get_json(force=True, silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入成语或词语"}), 400
    info = lookup(word)
    for k in ("pinyin", "category", "explanation", "derivation", "example"):
        if data.get(k) is not None and str(data.get(k)).strip() != "":
            info[k] = data[k]
    note = (data.get("note") or "").strip()
    db = get_db()
    cur = db.execute(
        "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), word, info["pinyin"], info["category"], info["explanation"],
         info["derivation"], info["example"], note, info["source"]))
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(row)), 201


@bp.get("/api/entries")
def api_list():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    starred = request.args.get("starred")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", 5))
    except ValueError:
        page_size = 5
    page_size = max(1, min(page_size, 100))

    where = "WHERE user_id=?"
    args = [uid()]
    if q:
        where += " AND (word LIKE ? OR pinyin LIKE ? OR explanation LIKE ? OR note LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if category in ("成语", "词语", "词组"):
        where += " AND category=?"
        args.append(category)
    if starred == "1":
        where += " AND starred=1"

    total = db.execute(f"SELECT COUNT(*) c FROM entries {where}", args).fetchone()["c"]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT * FROM entries {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [page_size, offset]).fetchall()
    items = [row_to_dict(r) for r in rows]
    stats = db.execute(
        "SELECT COUNT(*) total, SUM(category='成语') idiom, SUM(category='词语') ci,"
        " SUM(starred=1) starred FROM entries WHERE user_id=?", (uid(),)).fetchone()
    return jsonify({
        "items": items, "page": page, "page_size": page_size, "pages": pages, "total": total,
        "stats": {"total": stats["total"] or 0, "idiom": stats["idiom"] or 0,
                  "ci": stats["ci"] or 0, "starred": stats["starred"] or 0},
    })


@bp.put("/api/entries/<int:eid>")
def api_update(eid):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id=? AND user_id=?", (eid, uid())).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    fields = ["word", "pinyin", "category", "explanation", "derivation",
              "example", "note", "starred"]
    updates, args = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f}=?")
            args.append(int(bool(data[f])) if f == "starred" else data[f])
    if updates:
        args += [eid, uid()]
        db.execute(f"UPDATE entries SET {', '.join(updates)} WHERE id=? AND user_id=?", args)
        db.commit()
    row = db.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    return jsonify(row_to_dict(row))


@bp.delete("/api/entries/<int:eid>")
def api_delete(eid):
    """从「成语词语积累」删词 → **同步取消常考那边的 ★**。
       两边是同一份收藏，只删一边等于没删（下次打开常考还是实心星，再点一下又加回来）。"""
    db = get_db()
    r = db.execute("SELECT word FROM entries WHERE id=? AND user_id=?", (eid, uid())).fetchone()
    db.execute("DELETE FROM entries WHERE id=? AND user_id=?", (eid, uid()))
    unstarred = 0
    if r:
        cur = db.execute(
            "DELETE FROM ck_stars WHERE user_id=? AND board IN ('成语','实词') AND title=?",
            (uid(), r["word"]))
        unstarred = cur.rowcount or 0
    db.commit()
    return jsonify({"ok": True, "unstarred": unstarred})


@bp.post("/api/entries/sync")
def entries_sync():
    """对账：把两边补齐（谁有谁没有都补上），并报告补了多少。
       历史数据是两边各存各的，直接开双向同步会「有的对得上、有的对不上」，所以给个对账入口。"""
    db = get_db()
    ents = {r["word"] for r in db.execute(
        "SELECT word FROM entries WHERE user_id=? AND category IN ('成语','词语')", (uid(),))}
    stars = {r["title"]: r for r in db.execute(
        "SELECT * FROM ck_stars WHERE user_id=? AND board IN ('成语','实词')", (uid(),))}
    add_star, add_entry = 0, 0
    # entries 里有、常考没标星 → 去常考里找到这个词，补上星
    for w in ents - set(stars):
        row = db.execute("SELECT id, board, title, content, note FROM changkao_items "
                         "WHERE board IN ('成语','实词') AND title=?", (w,)).fetchone()
        if row:
            db.execute("INSERT OR REPLACE INTO ck_stars(user_id,board,item_id,title,content,note) "
                       "VALUES(?,?,?,?,?,?)",
                       (uid(), row["board"], row["id"], row["title"], row["content"], row["note"]))
            add_star += 1
    # 常考标了星、entries 里没有 → 补进成语词语积累
    for w, r in stars.items():
        if w in ents:
            continue
        cat = CK_TO_ENTRY.get(r["board"])
        if not cat:
            continue
        info = lookup(w) or {}
        db.execute(
            "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (uid(), w, info.get("pinyin") or "", cat,
             info.get("explanation") or r["content"] or "", info.get("derivation") or "",
             info.get("example") or "", r["note"] or "", "常考收藏"))
        add_entry += 1
    db.commit()
    return jsonify({"add_star": add_star, "add_entry": add_entry})
