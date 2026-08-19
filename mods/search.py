"""全文搜索：跨板块找内容。

匹配分两轮（见 api_search）：
  1) 精确轮——整串当子串找，命中什么就是什么，和以前的行为一模一样；
  2) 模糊轮——只在精确轮颗粒无收时才跑。把查询切成词（中文 2-gram），
     要求过半的词命中，按命中数排序。凭印象搜「社区知识14页必背」这种
     记岔了名字的查询，靠这一轮捞回来，前端会标明「相近内容」。
"""
import json
import math
import os
import re

from flask import Blueprint, jsonify, request

from core import UPLOADS, get_db, log, uid
from mods.annots import _ann_sentence, _ann_where
from mods.files import INLINE_EXT, OFFICE_EXT, TEXT_EXT
from mods.notes import _jl

bp = Blueprint("search", __name__)

FUZZY_MAX = 24          # 模糊轮最多回多少条，多了全是噪声
TERM_MAX = 24           # 最多切多少个词：一次 SQL 的绑定参数＝词数×列数×2，
                        # 粘一整段进来就会撞上 SQLite 的参数/表达式深度上限


def _terms(q):
    """把查询切成检索词。

    中文没有空格可切，所以汉字块出 2-gram（「知识14页」→ 知识、识1…不跨类），
    字母/数字块整体成词（「14」不拆成 1、4），标点丢掉。
    """
    out = []
    for seg in re.split(r"\s+", q):
        for m in re.finditer(r"[a-zA-Z0-9]+|[一-龥]+", seg):
            s = m.group()
            if s[0].isascii():
                out.append(s.lower())
            elif len(s) <= 2:
                out.append(s)
            else:
                out += [s[i:i + 2] for i in range(len(s) - 1)]
    return list(dict.fromkeys(out))


class _M:
    """一次搜索的匹配口径：SQL 侧和 Python 侧共用同一套词，免得两边判得不一样。"""

    def __init__(self, q, fuzzy=False):
        self.q = q
        self.ql = q.lower()
        self.fuzzy = fuzzy
        self.terms = (_terms(q)[:TERM_MAX] or [self.ql]) if fuzzy else [self.ql]
        # 过半的词命中才算数：只中一个「页」会把整个库捞出来
        self.need = max(2, math.ceil(len(self.terms) * 0.5)) if fuzzy else 1
        self.need = min(self.need, len(self.terms))

    def expr(self, cols):
        """一段 SQL 表达式，值＝命中的词数。可以直接进 WHERE，也可以进 ORDER BY。"""
        # IFNULL 不能省：NULL LIKE … 得到 NULL，多个词相加时会把整行的命中数
        # 变成 NULL，于是空着一列的记录在模糊轮里全体消失。
        one = "(" + " OR ".join("IFNULL(%s,'') LIKE ?" % c for c in cols) + ")"
        return " + ".join([one] * len(self.terms)), \
               ["%" + t + "%" for t in self.terms for _ in cols]

    def clause(self, cols, where="", params=(), order="id DESC", limit=15):
        """拼出 WHERE…ORDER BY…LIMIT。相关度优先，同分再按各板块原来的次序。"""
        e, p = self.expr(cols)
        sql = " WHERE " + (where + " AND " if where else "") + "%s >= %d" % (e, self.need)
        sql += " ORDER BY %s DESC" % e + (", " + order if order else "")
        sql += " LIMIT %d" % limit
        return sql, list(params) + p + p

    def score(self, *texts):
        """0＝不算命中；否则是命中词数的占比，模糊轮拿它排序。"""
        hay = " ".join(t or "" for t in texts).lower()
        hits = sum(1 for t in self.terms if t in hay)
        return hits / len(self.terms) if hits >= self.need else 0.0

    def find(self, low):
        """在（已小写的）文本里定位第一个命中处，返回 (位置, 长度)。"""
        i = low.find(self.ql)
        if i >= 0:
            return i, len(self.ql)
        for t in self.terms:
            j = low.find(t)
            if j >= 0:
                return j, len(t)
        return -1, 0


def _snippet(text, m, span=42):
    if not text:
        return ""
    i, n = m.find(text.lower())
    if i < 0:
        return (text[:90].replace("\n", " ")).strip()
    start = max(0, i - span)
    end = min(len(text), i + n + span)
    s = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def _block_text(b):
    t = re.sub(r"<[^>]+>", "", b.get("text", "") or "")
    data = b.get("data") or {}
    if b.get("type") == "table":
        for row in (data.get("rows") or []):
            t += " " + " ".join(str(c) for c in row)
    return t


def _collect(db, m):
    """按一种匹配口径跑一遍全库。精确轮和模糊轮共用，差别只在 m 里。"""
    results = []

    def add(score, item):
        if score:
            item["_s"] = score
            results.append(item)

    # 小记
    for r in db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        content = r["content"] or ""
        tags = _jl(r, "tags")
        todos = " ".join(t.get("text", "") for t in _jl(r, "todos"))
        add(m.score(content, " ".join(tags), todos),
            {"type": "note", "id": r["id"],
             "title": (content[:24].strip() or "（图片/附件小记）"),
             "snippet": _snippet(content or todos, m),
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
        s_name, s_body = m.score(name), (m.score(body) if body else 0.0)
        add(max(s_name, s_body),
            {"type": "material", "id": r["id"],
             "title": r["title"] or r["orig_name"], "ext": r["ext"],
             "viewable": (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT) or (r["ext"] in TEXT_EXT),
             "board": r["board"] or "",
             "snippet": _snippet(body, m) if s_body else ""})
    # 知识库文档
    nb_names = {row["id"]: row["name"] for row in
                db.execute("SELECT id,name FROM notebooks WHERE user_id=?", (uid(),)).fetchall()}
    for r in db.execute("SELECT * FROM kb_nodes WHERE user_id=? AND type='doc'", (uid(),)).fetchall():
        title = r["title"] or ""
        body = " ".join(_block_text(b) for b in _jl(r, "content"))
        add(m.score(title, body),
            {"type": "doc", "id": r["id"], "notebook_id": r["notebook_id"],
             "notebook": nb_names.get(r["notebook_id"], ""),
             "title": title or "无标题文档", "snippet": _snippet(body, m)})
    # 错题本
    for r in db.execute("SELECT * FROM wrong_questions WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall():
        hay = [str(r[k] or "") for k in ("question", "points", "method", "skill", "steps", "note", "qtype", "board")]
        qtext = (r["question"] or "").strip()
        add(m.score(*hay),
            {"type": "wrongq", "id": r["id"],
             "title": (qtext[:26] or "（图片错题）"),
             "board": r["board"] or r["qtype"] or "",
             "snippet": _snippet(qtext or r["points"] or "", m)})
    # 基础知识点（各板块 · 全站共享）+ 我的补充
    for r in db.execute("SELECT * FROM board_kb").fetchall():
        body = r["content"] or ""
        add(m.score(body, r["board"] or ""),
            {"type": "boardkb", "id": 0, "board": r["board"],
             "title": (r["board"] or "") + " · 基础知识点",
             "snippet": _snippet(body, m)})
    for r in db.execute("SELECT * FROM board_points WHERE user_id=?", (uid(),)).fetchall():
        add(m.score(r["content"] or ""),
            {"type": "boardkb", "id": 0, "board": r["board"],
             "title": (r["board"] or "") + " · 我的补充",
             "snippet": _snippet(r["content"] or "", m)})
    # 每日时政
    w, p = m.clause(["title", "content", "ai_summary"], limit=15)
    for r in db.execute("SELECT id,title,board,pub_date,content,ai_summary FROM news_items" + w, p):
        body = r["content"] or r["ai_summary"] or ""
        add(m.score(r["title"] or "", body),
            {"type": "news", "id": r["id"], "title": r["title"],
             "board": "%s · %s" % (r["board"] or "时政", r["pub_date"] or ""),
             "snippet": _snippet(body if m.score(body) else r["title"], m)})
    # 时政要文库（全文+AI解读）
    w, p = m.clause(["title", "content", "interpretation"], limit=10)
    for r in db.execute("SELECT id,title,category,content,interpretation FROM policy_docs" + w, p):
        body = r["content"] or ""
        if not m.score(body):
            body = r["interpretation"] or r["title"]
        add(m.score(r["title"] or "", r["content"] or "", r["interpretation"] or ""),
            {"type": "policydoc", "id": r["id"], "title": r["title"],
             "board": r["category"] or "要文", "snippet": _snippet(body, m)})
    # 党的创新理论学习词典
    w, p = m.clause(["term", "content"], limit=15)
    for r in db.execute("SELECT id,term,cat,content FROM party_dict" + w, p):
        add(m.score(r["term"] or "", r["content"] or ""),
            {"type": "partydict", "id": r["id"], "title": r["term"],
             "board": r["cat"] or "", "snippet": _snippet(r["content"] or "", m)})
    # 古诗文库
    w, p = m.clause(["title", "content", "author"], limit=15)
    for r in db.execute("SELECT id,title,author,category,content FROM classics" + w, p):
        add(m.score(r["title"] or "", r["content"] or "", r["author"] or ""),
            {"type": "classic", "id": r["id"], "title": r["title"],
             "board": "%s · %s" % (r["category"] or "", r["author"] or ""),
             "snippet": _snippet(r["content"] or "", m)})
    # 常识积累
    w, p = m.clause(["title", "content"], limit=15)
    for r in db.execute("SELECT id,board,topic,title,content FROM changshi_items" + w, p):
        add(m.score(r["title"] or "", r["content"] or ""),
            {"type": "changshi", "id": r["id"], "title": r["title"],
             "board": "%s · %s" % (r["board"], r["topic"]),
             "cs_board": r["board"], "cs_topic": r["topic"],
             "snippet": _snippet(r["content"] or "", m)})
    # 写作素材 / 衔接表达
    w, p = m.clause(["topic", "content"], limit=10)
    for r in db.execute("SELECT id,kind,topic,content,date FROM sucai_items" + w, p):
        add(m.score(r["topic"] or "", r["content"] or ""),
            {"type": "sucai", "id": r["id"], "title": (r["topic"] or r["kind"]),
             "board": "%s · %s" % (r["kind"], r["date"] or ""), "kind": r["kind"],
             "snippet": _snippet(r["content"] or "", m)})
    # 概括句
    try:
        w, p = m.clause(["topic", "sentence", "raw"], limit=10)
        for r in db.execute("SELECT id,topic,raw,sentence FROM gaikuo_items" + w, p):
            add(m.score(r["topic"] or "", r["sentence"] or "", r["raw"] or ""),
                {"type": "gaikuo", "id": r["id"], "title": r["topic"] or "概括句",
                 "board": "概括句积累", "snippet": _snippet(r["sentence"] or r["raw"] or "", m)})
    except Exception:
        log.exception("搜索的概括句分支出错：结果里会静默少这一类")
    # 我的成语词语收录
    w, p = m.clause(["word", "explanation", "note"], where="user_id=?", params=(uid(),), limit=10)
    for r in db.execute("SELECT id,word,category,explanation,note FROM entries" + w, p):
        add(m.score(r["word"] or "", r["explanation"] or "", r["note"] or ""),
            {"type": "entry", "id": r["id"], "title": r["word"],
             "board": r["category"] or "收录", "snippet": _snippet(r["explanation"] or "", m)})
    # 草稿本（笔迹不识别，只能按本子名搜）
    w, p = m.clause(["title"], where="user_id=?", params=(uid(),), order="updated_at DESC", limit=10)
    for r in db.execute("SELECT id,title,pages,updated_at FROM drafts" + w, p):
        add(m.score(r["title"] or ""),
            {"type": "draft", "id": r["id"], "title": r["title"] or "未命名草稿",
             "board": "草稿本 · %d 页" % (r["pages"] or 1),
             "snippet": "最近更新 " + (r["updated_at"] or "")[:16]})
    # 范文（题干 / 参考答案）
    w, p = m.clause(["e.stem", "e.answer", "p.topic", "p.title"], order="e.id DESC", limit=10)
    for r in db.execute("SELECT e.id, e.type_name, e.stem, e.answer, p.topic, p.title "
                        "FROM essays e LEFT JOIN essay_papers p ON p.id=e.paper_id" + w, p):
        body = r["answer"] or ""
        add(m.score(r["stem"] or "", body, r["topic"] or "", r["title"] or ""),
            {"type": "essay", "id": r["id"],
             "title": "%s · %s" % (r["title"] or r["topic"] or "范文", r["type_name"] or ""),
             "board": "范文推荐 · AI 仿真卷（非真题）",
             "snippet": _snippet(body if m.score(body) else (r["stem"] or ""), m)})
    # 应用文上位词（场景规范表述）
    w, p = m.clause(["scene", "phrases", "doctype", "note", "example"], limit=10)
    for r in db.execute("SELECT id,scene,phrases,doctype,note,example FROM gongwen_items" + w, p):
        add(m.score(r["scene"] or "", r["phrases"] or "", r["doctype"] or "", r["note"] or "", r["example"] or ""),
            {"type": "gongwen", "id": r["id"], "title": r["scene"] or "应用文表述",
             "board": "应用文上位词 · " + (r["doctype"] or ""), "term": r["scene"] or "",
             "snippet": _snippet(r["phrases"] or r["note"] or r["example"] or "", m)})
    # 应用文素材库（错例 / 表述 / 骨架…按 kind 分）。
    # 错例的可搜内容在 text 那个 JSON 里（{"bad":…,"good":…}），所以 LIKE 直接扫它——
    # 搜「一是」要能搜到「这么写是错的」，这正是错例最该被搜到的时机。
    w, p = m.clause(["title", "text", "note", "doctype"], order="freq DESC, id", limit=12)
    for r in db.execute("SELECT id,kind,doctype,part,title,text,note,freq FROM yy_items" + w, p):
        body = r["text"] or ""
        s = m.score(r["title"] or "", body, r["note"] or "", r["doctype"] or "")
        if r["kind"] == "错例":
            try:
                d = json.loads(body or "{}")
                body = "✗ %s ／ ✓ %s" % (d.get("bad", ""), d.get("good", ""))
            except Exception:
                pass
        add(s, {"type": "yy", "id": r["id"],
                "title": (r["title"] or r["kind"] or "应用文素材")[:40],
                "board": "应用文·%s · %s" % (
                    r["kind"] or "", " ".join(x for x in [r["doctype"], r["part"]] if x)),
                "snippet": _snippet(body or r["note"] or "", m)})
    # 上位词（常考·逻辑填空）
    w, p = m.clause(["hyper", "subs", "note", "example"], limit=10)
    for r in db.execute("SELECT id,hyper,subs,note,example FROM hyper_items" + w, p):
        add(m.score(r["hyper"] or "", r["subs"] or "", r["note"] or "", r["example"] or ""),
            {"type": "changkao", "id": r["id"], "title": r["hyper"] or "上位词",
             "board": "常考 · 上位词", "ck_board": "上位词",
             "snippet": _snippet(r["subs"] or r["note"] or "", m)})
    # 习语金句
    w, p = m.clause(["quote", "note", "apply", "keyword"], limit=10)
    for r in db.execute("SELECT id,quote,note,category,apply,keyword FROM xiyu_items" + w, p):
        add(m.score(r["quote"] or "", r["note"] or "", r["apply"] or "", r["keyword"] or ""),
            {"type": "xiyu", "id": r["id"], "title": (r["quote"] or "")[:30],
             "board": "习语金句 · " + (r["category"] or ""),
             "snippet": _snippet(r["note"] or r["apply"] or "", m)})
    # 常考（高频成语/实词/提法…）
    w, p = m.clause(["title", "content", "note"], limit=15)
    for r in db.execute("SELECT id,board,title,content,note FROM changkao_items" + w, p):
        add(m.score(r["title"] or "", r["content"] or "", r["note"] or ""),
            {"type": "changkao", "id": r["id"], "title": r["title"] or "常考",
             "board": "常考 · " + (r["board"] or ""), "ck_board": r["board"] or "",
             "snippet": _snippet(r["content"] or r["note"] or "", m)})
    # 理论基础（马原/毛概/中特/习思想）
    w, p = m.clause(["title", "content", "topic"], limit=15)
    for r in db.execute("SELECT id,board,topic,title,content FROM theory_items" + w, p):
        add(m.score(r["title"] or "", r["content"] or "", r["topic"] or ""),
            {"type": "theory", "id": r["id"], "title": r["title"] or r["topic"] or "理论",
             "board": "理论基础 · " + (r["board"] or ""), "th_board": r["board"] or "",
             "snippet": _snippet(r["content"] or "", m)})
    # 经典著作（毛选等）
    w, p = m.clause(["title", "content", "interpretation"], limit=10)
    for r in db.execute("SELECT id,book,title,content,interpretation FROM works" + w, p):
        body = r["content"] or ""
        add(m.score(r["title"] or "", body, r["interpretation"] or ""),
            {"type": "work", "id": r["id"], "title": r["title"] or "篇目",
             "board": "经典著作 · " + (r["book"] or ""),
             "snippet": _snippet(body if m.score(body) else (r["interpretation"] or ""), m)})
    # 手写批注：搜「我在哪儿圈过这句话」。锚里存着压着的原文（PDF 的取自 textLayer），
    # 所以这里搜的是**你标过的内容**，不只是文件名。同一处只出一条（一句话上可能划了好几笔）。
    seen_ann = set()
    w, p = m.clause(["anchor"], where="user_id=?", params=(uid(),), limit=200)
    for r in db.execute("SELECT id,target,anchor_type,anchor FROM annotations" + w, p):
        try:
            a = json.loads(r["anchor"] or "{}")
        except Exception:
            continue
        quote = (a.get("quote") or "").strip()
        s = m.score(quote)
        if not quote or not s:
            continue
        sent = _ann_sentence(a) or quote        # 同一段上的好几笔＝同一处，按句子去重（见 _ann_sentence）
        key = (r["target"], sent)
        if key in seen_ann:
            continue
        seen_ann.add(key)
        where, mat = _ann_where(db, uid(), r["target"])
        if a.get("page"):
            where += " · 第 %d 页" % a["page"]
        add(s, {"type": "annot", "id": r["id"], "title": sent[:40],
                "board": where, "target": r["target"], "mat": mat,
                "snippet": _snippet((a.get("prefix") or "") + quote + (a.get("suffix") or ""), m)})
        if len(seen_ann) >= 12:
            break
    return results


@bp.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    db = get_db()
    m = _M(q)
    results = _collect(db, m)
    fuzzy = False
    if not results:
        # 一条都没有 ≠ 库里没有：名字记岔了、词序反了、多打了个字都会落到这儿。
        # 换成分词口径再来一遍，按相关度排，前端标「相近内容」。
        m = _M(q, fuzzy=True)
        results = sorted(_collect(db, m), key=lambda r: -r["_s"])[:FUZZY_MAX]
        fuzzy = bool(results)
    for r in results:
        r.pop("_s", None)
    return jsonify({"results": results, "q": q, "fuzzy": fuzzy,
                    "terms": m.terms if fuzzy else []})
