"""常考：高频考点合集（成语 / 实词 / 上位词 / 古诗文 / 每日古诗积累 / 常识 / 提法）。

按真题考频排序，比自己零散收录的更该背。
「每日古诗积累」是唯一一块**按天长出来**的：内容由「今日复习 · 古诗」每天新出的卡自动汇入
（记流水的地方在 mods/review.py 的 _gushi_log），这儿只负责按天读出来。
"""
import json
import re

from flask import Blueprint, jsonify, request

from core import get_db, log, lookup, uid
from mods.ai import _ai_call_or_error
from mods.classics import _ensure_classic_freq

bp = Blueprint("changkao", __name__)


CK_BOARDS = [
    {"key": "成语", "name": "高频成语", "icon": "quote", "desc": "老师讲义 · 按真题考频排序"},
    {"key": "实词", "name": "实词搭配", "icon": "edit", "desc": "老师讲义 · 常见动宾搭配"},
    {"key": "上位词", "name": "上位词", "icon": "layers", "desc": "概括词提示 · 下位词归类"},
    {"key": "古诗文", "name": "高频古诗文", "icon": "book", "desc": "按考频排序的名篇名句"},
    # 唯一一块「按天长出来」的：内容来自「今日复习 · 古诗」每天新出的卡，自动汇入（见 mods/review.py 的 _gushi_log）
    {"key": "古诗积累", "name": "每日古诗积累", "icon": "clock", "desc": "今日复习的古诗 · 按天归档"},
    {"key": "常识", "name": "高频常识", "icon": "bulb", "desc": "常识判断反复出现的考点"},
    {"key": "提法", "name": "高频提法", "icon": "feather", "desc": "时政新提法 · 申论高频表述"},
]


@bp.get("/api/changkao/boards")
def changkao_boards():
    db = get_db()
    counts = {r["board"]: r["c"] for r in
              db.execute("SELECT board, COUNT(*) c FROM changkao_items GROUP BY board")}
    counts["古诗文"] = db.execute("SELECT COUNT(*) FROM classics WHERE freq>=100").fetchone()[0]
    counts["上位词"] = db.execute("SELECT COUNT(*) FROM hyper_items").fetchone()[0]
    # 古诗积累是**每人一份**（背到哪天算哪天），别跟前面几块的全局条数混着数
    counts["古诗积累"] = db.execute("SELECT COUNT(*) FROM gushi_log WHERE user_id=?",
                                (uid(),)).fetchone()[0]
    return jsonify({"boards": [dict(b, count=counts.get(b["key"], 0)) for b in CK_BOARDS]})


@bp.get("/api/changkao/items")
def changkao_items():
    board = (request.args.get("board") or "成语").strip()
    db = get_db()
    if board == "古诗文":
        _ensure_classic_freq(db)
        rows = db.execute("SELECT id, title, author, dynasty, content FROM classics "
                          "WHERE freq>=100 ORDER BY freq DESC, id LIMIT 300").fetchall()
        return jsonify({"board": board, "kind": "classic", "items": [
            {"id": r["id"], "title": r["title"],
             "content": (r["content"] or "").split("\n")[0][:60],
             "note": ((r["dynasty"] or "") + " · " + (r["author"] or "")).strip(" ·")} for r in rows]})
    if board == "古诗积累":
        # 按「进复习的那天」倒序：最近背的排最前，前端按 day 分隔成一天一段。
        # id 用**卡的 id**（跟 review 那边的 kind='gushi' 同一套），收藏/取回都对得上。
        rows = db.execute(
            "SELECT g.id, g.line, g.topic, g.theme, g.common, g.apply, "
            "l.added_on, c.id cid, c.title, c.author, c.dynasty "
            "FROM gushi_log l JOIN gushi_cards g ON g.id=l.card_id "
            "JOIN classics c ON c.id=g.classic_id WHERE l.user_id=? "
            "ORDER BY l.added_on DESC, l.card_id DESC", (uid(),)).fetchall()
        return jsonify({"board": board, "kind": "gushilog", "items": [
            {"id": r["id"], "cid": r["cid"], "day": r["added_on"] or "",
             "title": "《%s》" % (r["title"] or ""), "content": r["line"] or "",
             "note": " · ".join(x for x in [r["dynasty"] or "", r["author"] or "",
                                            r["topic"] or ""] if x),
             "common": r["common"] or "", "apply": r["apply"] or "",
             "theme": r["theme"] or ""} for r in rows]})
    if board == "上位词":
        rows = db.execute("SELECT id, hyper, subs, note FROM hyper_items ORDER BY id DESC LIMIT 300").fetchall()
        return jsonify({"board": board, "kind": "hyper", "items": [
            {"id": r["id"], "title": r["hyper"], "content": r["subs"], "note": r["note"]} for r in rows]})
    # 成语/实词来自老师讲义，插入顺序就是考频从高到低的顺序
    rows = db.execute("SELECT id, title, content, note, freq, meaning FROM changkao_items WHERE board=? "
                      "ORDER BY id LIMIT 1000", (board,)).fetchall()
    return jsonify({"board": board, "kind": "text", "items": [dict(r) for r in rows]})


# ⚠️ 别叫 CK_BOARDS —— 那个名字已经被上面的板块元数据（字典列表）占了，
#    重名会把它整个盖掉，changkao_boards 里的 b["key"] 就会拿字符串去取下标。
CK_STAR_BOARDS = ["成语", "实词", "上位词", "古诗文", "常识", "提法", "古诗积累"]
# 成语/实词收藏时，同步收进「言语理解 → 成语词语积累」，并落到对应分类里
CK_TO_ENTRY = {"成语": "成语", "实词": "词语"}


def _ck_one(db, board, iid):
    """按 (板块, id) 取回那一条 —— 七个模块散在四张表里，这里统一取。"""
    if board == "古诗文":
        r = db.execute("SELECT id, title, author, dynasty, content FROM classics WHERE id=?", (iid,)).fetchone()
        if not r:
            return None
        return {"title": r["title"], "content": (r["content"] or "").split("\n")[0][:60],
                "note": ((r["dynasty"] or "") + " · " + (r["author"] or "")).strip(" ·")}
    if board == "古诗积累":
        r = db.execute("SELECT g.line, g.topic, c.title, c.author, c.dynasty FROM gushi_cards g "
                       "JOIN classics c ON c.id=g.classic_id WHERE g.id=?", (iid,)).fetchone()
        if not r:
            return None
        return {"title": "《%s》" % (r["title"] or ""), "content": r["line"] or "",
                "note": " · ".join(x for x in [r["dynasty"] or "", r["author"] or "",
                                               r["topic"] or ""] if x)}
    if board == "上位词":
        r = db.execute("SELECT hyper, subs, note FROM hyper_items WHERE id=?", (iid,)).fetchone()
        return {"title": r["hyper"], "content": r["subs"], "note": r["note"]} if r else None
    r = db.execute("SELECT title, content, note FROM changkao_items WHERE id=? AND board=?",
                   (iid, board)).fetchone()
    return {"title": r["title"], "content": r["content"], "note": r["note"]} if r else None


@bp.post("/api/changkao/star")
def changkao_star():
    """收藏 / 取消收藏。成语和实词**同时**收进「成语词语积累」的对应分类里
       —— 收藏的目的就是拿去背，散在两处等于没收。"""
    d = request.get_json(silent=True) or {}
    board = (d.get("board") or "").strip()
    iid = int(d.get("id") or 0)
    if board not in CK_STAR_BOARDS or not iid:
        return jsonify({"error": "参数错误"}), 400
    db = get_db()
    have = db.execute("SELECT 1 FROM ck_stars WHERE user_id=? AND board=? AND item_id=?",
                      (uid(), board, iid)).fetchone()
    if have:
        db.execute("DELETE FROM ck_stars WHERE user_id=? AND board=? AND item_id=?", (uid(), board, iid))
        # 成语/实词：**同步从「成语词语积累」里删掉**（两边是同一份收藏，只删一边等于没删）
        removed = 0
        if board in CK_TO_ENTRY:
            it0 = _ck_one(db, board, iid)
            if it0:
                cur = db.execute("DELETE FROM entries WHERE user_id=? AND word=?",
                                 (uid(), it0["title"]))
                removed = cur.rowcount or 0
        db.commit()
        return jsonify({"starred": False, "removed_entry": removed})
    it = _ck_one(db, board, iid)
    if not it:
        return jsonify({"error": "这一条不存在"}), 404
    db.execute("INSERT OR REPLACE INTO ck_stars(user_id,board,item_id,title,content,note) "
               "VALUES(?,?,?,?,?,?)",
               (uid(), board, iid, it["title"], it["content"], it["note"]))
    to_entry = False
    cat = CK_TO_ENTRY.get(board)
    if cat:
        dup = db.execute("SELECT 1 FROM entries WHERE user_id=? AND word=?", (uid(), it["title"])).fetchone()
        if not dup:
            info = lookup(it["title"]) or {}
            db.execute(
                "INSERT INTO entries(user_id,word,pinyin,category,explanation,derivation,example,note,source) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (uid(), it["title"], info.get("pinyin") or "", cat,
                 info.get("explanation") or it["content"] or "",
                 info.get("derivation") or "", info.get("example") or "",
                 it["note"] or "", "常考收藏"))
            to_entry = True
    db.commit()
    return jsonify({"starred": True, "to_entry": to_entry, "category": cat or ""})


@bp.get("/api/changkao/stars")
def changkao_stars():
    """我收藏的（按板块分组）。只要 ids 时用 ?ids=1，页面上标星用。"""
    db = get_db()
    rows = db.execute("SELECT * FROM ck_stars WHERE user_id=? ORDER BY board, created_at DESC",
                      (uid(),)).fetchall()
    if request.args.get("ids"):
        return jsonify({"ids": ["%s:%d" % (r["board"], r["item_id"]) for r in rows]})
    by = {}
    for r in rows:
        by.setdefault(r["board"], []).append(dict(r))
    return jsonify({"total": len(rows),
                    "boards": [{"board": b, "items": by[b]} for b in CK_STAR_BOARDS if b in by]})


def _real_example(db, word):
    """在**真实语料**里找含这个词的句子：人民日报等时政原文、时政要文、习语金句。
       找到了就是真出处 —— 比 AI 编一句强得多（AI 编的句子读着像那么回事，但不是真的）。"""
    like = "%" + word + "%"
    srcs = [
        ("SELECT content AS t, title AS s, source AS src FROM news_items WHERE content LIKE ? LIMIT 3",
         "news"),
        ("SELECT content AS t, title AS s, '' AS src FROM policy_docs WHERE content LIKE ? LIMIT 2",
         "policy"),
        ("SELECT quote AS t, category AS s, source_url AS src FROM xiyu_items WHERE quote LIKE ? LIMIT 2",
         "xiyu"),
    ]
    for sql, kind in srcs:
        try:
            rows = db.execute(sql, (like,)).fetchall()
        except Exception:
            continue
        for r in rows:
            text = (r["t"] or "").replace("\n", "")
            # 把含这个词的**那一句**切出来（前后到句号为止），太长的截断
            for sent in re.split(r"(?<=[。！？；])", text):
                if word in sent and 12 <= len(sent) <= 120:
                    if kind == "news":
                        src = (r["src"] or "时政报道") + "《" + (r["s"] or "")[:22] + "》"
                    elif kind == "policy":
                        src = "时政要文《" + (r["s"] or "")[:22] + "》"
                    else:
                        src = "习语金句"
                    return sent.strip(), src
    return None, None


@bp.get("/api/changkao/<int:cid>/example")
def changkao_example(cid):
    """例句：真语料优先，AI 仿写兜底（会标明来源，不糊弄）。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["example"] and not request.args.get("force"):
        return jsonify({"example": r["example"], "src": r["example_src"] or "", "cached": True})

    word = r["title"]
    ex, src = _real_example(db, word)
    if not ex:
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是公考语文老师。例句要像《人民日报》《政府工作报告》"
                                           "那样的规范书面语（时政/公文语境），一句话，20~45 字。"
                                           "严格输出 JSON。"},
             {"role": "user", "content":
              "给「%s」（%s）写一个例句。\n"
              "要求：\n"
              "1. **时政/公文语境**（乡村振兴、基层治理、科技创新这类），像人民日报社论的句子。\n"
              "2. 用法必须准确（褒贬、搭配对象、能不能用于否定句，都要对）。\n"
              "3. 20~45 字，一句话。\n\n"
              '只输出 JSON：{"example":""}' % (word, (r["content"] or "")[:60])}],
            temperature=0.5, max_tokens=300, timeout=120, json_mode=True)
        if err:
            return err
        try:
            ex = (json.loads(rep).get("example") or "").strip()
        except Exception:
            return jsonify({"error": "AI 返回格式异常"}), 502
        if not ex or word not in ex:
            return jsonify({"error": "没造出合格的例句，请重试"}), 502
        # ⚠️ 老实标注：这是 AI 仿写的，不是真的从人民日报摘的
        src = "AI 仿写（人民日报文风）"

    db.execute("UPDATE changkao_items SET example=?, example_src=? WHERE id=?", (ex, src, cid))
    db.commit()
    return jsonify({"example": ex, "src": src})


@bp.get("/api/changkao/<int:cid>/confuse")
def changkao_confuse(cid):
    """相似辨析：逻辑填空考的就是「这几个近义词该用哪个」。
       给出 2~3 个易混词，逐个对比：**词义侧重 / 感情色彩 / 搭配对象 / 语体**，
       并给一道「填空自测」（把这几个词摆一起，看你选不选得对）。
       易混词**优先从我们自己的成语库里挑**（这样辨析完这几个词都在你的复习范围内）。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["confuse"] and not request.args.get("force"):
        try:
            return jsonify(dict(json.loads(r["confuse"]), cached=True))
        except Exception:
            log.debug("confuse 缓存不是合法 JSON，重新生成", exc_info=True)

    word = r["title"]
    # 库里的候选（同板块、考频高的）—— 让 AI 优先从这里面挑，辨析完的词都在复习范围内
    pool = [x[0] for x in db.execute(
        "SELECT title FROM changkao_items WHERE board=? AND title!=? "
        "ORDER BY COALESCE(freq,0) DESC LIMIT 300", (r["board"], word))]

    prompt = (
        "考生在背「%s」（%s）。请做一份**易混词辨析**。\n\n"
        "【选谁来对比】挑 2~3 个**最容易和它混**的词。**优先从下面这个词库里挑**"
        "（这样辨析完的词都在他的复习范围内）；库里实在没有合适的，才可以用库外的词。\n"
        "词库：%s\n\n"
        "【每个对比词要说清四件事】\n"
        "· focus：**词义侧重**在哪不一样（这是最关键的）\n"
        "· color：感情色彩（褒义/贬义/中性），有没有区别\n"
        "· collocation：**搭配对象**不一样在哪（能修饰什么、不能修饰什么）\n"
        "· wrong：一个**用错的例子**——把它误用在该用「%s」的地方，说清为什么不行\n\n"
        "【还要给】\n"
        "· key：一句话的**辨析口诀**（考场上 3 秒能想起来的那种）\n"
        "· quiz：一道填空自测 —— stem（一句话，中间一个空 ______）、"
        "options（把这几个词都列上，形如 \"A. …\"）、answer（正确选项字母）、"
        "why（为什么是它，其他为什么不行）\n\n"
        "只输出 JSON：\n"
        '{"key":"","items":[{"word":"","focus":"","color":"","collocation":"","wrong":""}],'
        '"quiz":{"stem":"","options":["A. …","B. …","C. …"],"answer":"A","why":""}}'
        % (word, (r["content"] or "")[:60], "、".join(pool[:150]), word))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考言语理解老师。辨析要说到**用哪个**的层面，"
                                       "别只复述释义。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    items = [x for x in (d.get("items") or []) if (x.get("word") or "").strip()][:3]
    if not items:
        return jsonify({"error": "没找到易混词"}), 502
    quiz = d.get("quiz") or {}
    # 自测题也要过一遍格式关：选项和答案对得上，否则不给（宁可不给，也不给一道错题）
    opts = quiz.get("options") or []
    ans = (quiz.get("answer") or "").strip().upper()[:1]
    if not (quiz.get("stem") and 2 <= len(opts) <= 5 and ans and ans in "ABCDE"[:len(opts)]):
        quiz = None

    # 库里有的对比词，带上 id —— 前端可以直接点过去看它的释义/典故
    ids = {}
    for x in items:
        row = db.execute("SELECT id FROM changkao_items WHERE board=? AND title=?",
                         (r["board"], x["word"])).fetchone()
        if row:
            ids[x["word"]] = row["id"]
        x["in_lib"] = bool(row)
        x["id"] = row["id"] if row else 0

    out = {"word": word, "board": r["board"], "key": (d.get("key") or "").strip(),
           "items": items, "quiz": quiz}
    db.execute("UPDATE changkao_items SET confuse=? WHERE id=?",
               (json.dumps(out, ensure_ascii=False), cid))
    db.commit()
    return jsonify(out)


@bp.get("/api/changkao/<int:cid>/story")
def changkao_story(cid):
    """成语/实词的典故：出处原文、故事、本义→引申义怎么来的、易错点。
       看懂来历自然就记住了，比死背释义牢。AI 讲一次就缓存进 changkao_items.story。"""
    db = get_db()
    r = db.execute("SELECT * FROM changkao_items WHERE id=?", (cid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["story"]:
        return jsonify({"id": cid, "title": r["title"], "board": r["board"],
                        "content": r["content"], "note": r["note"],
                        "freq": r["freq"], "story": json.loads(r["story"])})
    word, mean = r["title"] or "", (r["content"] or "")[:120]
    is_idiom = (r["board"] or "") == "成语"
    prompt = (
        "讲清「%s」的来历，让考生理解了再记，而不是死背释义。释义：%s\n\n"
        "给这几项：\n"
        "· origin：出处（哪本书、哪个人、什么年代；有原文就把**原句**引出来，注明篇目）\n"
        "· story：%s（80~160 字，有人物有情节，讲得让人记得住）\n"
        "· evolve：本义是什么 → 怎么引申成今天这个意思的（这一步最关键，理解了就不会用错）\n"
        "· usage：公考里怎么考它——常和哪些词辨析、什么语境用、褒贬中性、易错点\n\n"
        '只输出 JSON：{"origin":"","story":"","evolve":"","usage":""}'
        % (word, mean,
           "典故 / 历史故事" if is_idiom else "这个词的来源与用法演变（没有典故就讲它的构词与语感来源）"))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是语文与公考言语老师，讲典故有据可查、不编造出处，语言生动。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1600, timeout=180, json_mode=True)
    if err:
        return err
    try:
        st = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    if not (st.get("story") or st.get("origin")):
        return jsonify({"error": "没能讲出典故，请重试"}), 502
    db.execute("UPDATE changkao_items SET story=? WHERE id=?", (json.dumps(st, ensure_ascii=False), cid))
    db.commit()
    return jsonify({"id": cid, "title": r["title"], "board": r["board"],
                    "content": r["content"], "note": r["note"], "freq": r["freq"], "story": st})


@bp.get("/api/hyper/<int:hid>")
def hyper_detail(hid):
    """上位词详解：每个下位词的**典故 / 出处 / 背景**。第一次点开时让 AI 讲一遍并缓存，
       之后直接读库——像古诗文那样点开就能看原文与赏析，理解了才记得住。"""
    db = get_db()
    r = db.execute("SELECT * FROM hyper_items WHERE id=?", (hid,)).fetchone()
    if not r:
        return jsonify({"error": "词条不存在"}), 404
    if r["story"]:
        return jsonify({"id": hid, "hyper": r["hyper"], "subs": r["subs"], "note": r["note"],
                        "story": json.loads(r["story"])})
    subs = [x.strip() for x in re.split(r"[、,，/]", r["subs"] or "") if x.strip()][:10]
    if not subs:
        return jsonify({"error": "这条没有下位词"}), 400
    prompt = (
        "上位词「%s」下面这些下位词，逐个讲清楚它的**来历与背景**，"
        "让考生理解了再记，而不是死背。\n下位词：%s\n\n"
        "每条给：\n"
        "· origin：出处 / 起源（哪个朝代、哪个地方、由什么演变而来，有史实就写史实）\n"
        "· story：典故或历史背景故事（60~120 字，讲得生动一点，有人物有情节最好；"
        "确实没有典故的，就讲它的形成过程或代表人物/代表作）\n"
        "· point：公考里怎么考它（常识题的考点，或逻辑填空里它作为「%s」这个概括词时的用法）\n\n"
        '只输出 JSON：{"items":[{"name":"","origin":"","story":"","point":""}]}'
        % (r["hyper"], "、".join(subs), r["hyper"]))
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考常识与文化通识老师，讲典故有史实、不编造，语言生动。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=3000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        items = [x for x in (json.loads(rep).get("items") or []) if x.get("name")]
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502
    if not items:
        return jsonify({"error": "没能讲出典故，请重试"}), 502
    db.execute("UPDATE hyper_items SET story=? WHERE id=?", (json.dumps(items, ensure_ascii=False), hid))
    db.commit()
    return jsonify({"id": hid, "hyper": r["hyper"], "subs": r["subs"], "note": r["note"], "story": items})
