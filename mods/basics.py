"""各板块基础知识点。

三个入口，两套资料：

  优路 · 系统精讲(youlu)   讲义式，章/节/考点三级，讲解 + 例题 + 解析
  三色笔记 · 速记(sanse)   浓缩框架，红蓝绿三色标重点（{{r|…}} 标记由前端上色）
  考点对照(compare)        同一考点下先优路详解、后三色速记，靠 basic_topics 串起来

资料由 ingest_basics.py 从云盘 PDF 解析进 basic_nodes / basic_blocks，
这里只读不写。老的 board_kb（AI 梳理）和 board_points（我的补充）原样保留 ——
它们是用户自己攒下的，不能因为换了资料源就没了。
"""
import json
import os
import re
import subprocess

from flask import Blueprint, jsonify, request, send_file

from core import ALL_BOARDS, SECTIONS, UPLOADS, get_db, log, uid
from mods import realref
from mods.ai import _ai_call_or_error

bp = Blueprint("basics", __name__)


_BOARD_SEC = {b: s["name"] for s in SECTIONS for b in s["boards"]}
SOURCE_META = {
    "youlu": {"name": "优路 · 系统精讲", "icon": "book",
              "desc": "机构讲义：考点讲解 + 例题精析"},
    "sanse": {"name": "三色笔记 · 速记", "icon": "target",
              "desc": "浓缩框架：三色标重点，适合快速过"},
    "shequ": {"name": "社区速记 · 考点清单", "icon": "compass",
              "desc": "公告点名的范围：社工初级 + 社区建设 + 基层治理 + 党建 + 法律常识 + 时政"},
}


def _node_row(r, kids=0, blocks=0):
    return {"id": r["id"], "title": r["title"], "level": r["level"],
            "parent_id": r["parent_id"], "page": r["page_from"],
            "topic_id": r["topic_id"], "kids": kids, "blocks": blocks}


@bp.get("/api/basics/entries")
def basics_entries():
    """每个板块有哪几套资料可用 —— 前端拿它决定板块页摆几张卡片。"""
    db = get_db()
    out = {}
    # 只数**叶子**，不数分组节点：优路/三色的树是「章 → 考点」两层，level 2 就是叶子；
    # 社区线是「书 → 章/节 → 考点」三层，把 309 个章节也算进去的话，
    # 板块页上的考点数会凭空多出一成，而那些章节点开是分组、不是内容。
    for r in db.execute(
            "SELECT n.board, n.source, COUNT(*) c FROM basic_nodes n "
            "WHERE n.level>=2 AND NOT EXISTS("
            "  SELECT 1 FROM basic_nodes k WHERE k.parent_id=n.id) "
            "GROUP BY n.board, n.source"):
        out.setdefault(r["board"], {})[r["source"]] = r["c"]
    for r in db.execute("SELECT board, COUNT(*) c FROM basic_topics GROUP BY board"):
        out.setdefault(r["board"], {})["compare"] = r["c"]
    return jsonify({"boards": out, "meta": SOURCE_META})


@bp.get("/api/basics/tree")
def basics_tree():
    """一套资料的目录树（只给结构，正文按需拉）。"""
    board = (request.args.get("board") or "").strip()
    source = (request.args.get("source") or "").strip()
    if board not in ALL_BOARDS or source not in SOURCE_META:
        return jsonify({"error": "参数无效"}), 400
    db = get_db()
    rows = db.execute(
        "SELECT id,title,level,parent_id,page_from,topic_id FROM basic_nodes "
        "WHERE board=? AND source=? ORDER BY sort", (board, source)).fetchall()
    nblk = {r["node_id"]: r["c"] for r in db.execute(
        "SELECT b.node_id, COUNT(*) c FROM basic_blocks b JOIN basic_nodes n "
        "ON b.node_id=n.id WHERE n.board=? AND n.source=? GROUP BY b.node_id",
        (board, source))}
    kids = {}
    for r in rows:
        if r["parent_id"]:
            kids[r["parent_id"]] = kids.get(r["parent_id"], 0) + 1
    src = db.execute("SELECT title FROM basic_sources WHERE source=? AND board=?",
                     (source, board)).fetchone()
    return jsonify({"board": board, "source": source,
                    "title": src["title"] if src else "",
                    "meta": SOURCE_META[source],
                    "nodes": [_node_row(r, kids.get(r["id"], 0), nblk.get(r["id"], 0))
                              for r in rows]})


def _practice(db, topic_id):
    """这个考点能练多少道真题。

    考点记的是 qtype 列表（见 basic_topics.qtypes_json），不是逐题标签 —— 一个考点
    常对应几个题型（「排列组合与概率问题」← 排列组合 + 概率），一起出才像一节课后练习。

    口径**一律走 realref**，不在这儿另写一份：它管的是「哪些题能发给人做」
    （原卷带答案 or AI 解析过了双模型核验）和「板块 → 卷面模块」的映射
    （政治理论在卷面上不是独立模块，题混在常识判断里）。这里自己拼一份的下场是
    数字和 /api/real/quiz 真取到的题对不上 —— 界面说 0 道、点进去却有题，或反过来。
    """
    if not topic_id:
        return None
    t = db.execute("SELECT board,name,qtypes_json FROM basic_topics WHERE id=?",
                   (topic_id,)).fetchone()
    if not t:
        return None
    try:
        qts = [x for x in json.loads(t["qtypes_json"] or "[]") if x]
    except (ValueError, TypeError):
        qts = []
    if not qts:
        return None
    module = realref.BOARD_MODULE.get(t["board"], t["board"])
    n = db.execute(
        "SELECT COUNT(*) c FROM real_questions q LEFT JOIN real_explains e ON e.qid=q.id "
        "WHERE q.module=? AND %s AND %s IN (%s)"
        % (realref.servable("q", "e"), realref.qtype_expr("q", "e"), ",".join("?" * len(qts))),
        [module] + qts).fetchone()["c"]
    return {"topic_id": topic_id, "name": t["name"], "module": module,
            "qtypes": qts, "count": n} if n else None


def _blocks(db, node_id):
    # page/page_to 是这一块**自己**跨的页范围，不是节点的页 —— 图形推理的例题
    # 常横跨好几页，前端要按范围给「看原书」，只给一页会指到别的小节去
    return [{"kind": r["kind"], "md": r["content_md"], "page": r["page"],
             "page_to": r["page_to"] or r["page"]}
            for r in db.execute(
                "SELECT kind,content_md,page,page_to FROM basic_blocks WHERE node_id=? "
                "ORDER BY sort", (node_id,))]


@bp.get("/api/basics/node/<int:nid>")
def basics_node(nid):
    """一个考点的正文。带上面包屑和同级的上一个/下一个，方便一路读下去。"""
    db = get_db()
    n = db.execute("SELECT * FROM basic_nodes WHERE id=?", (nid,)).fetchone()
    if not n:
        return jsonify({"error": "考点不存在"}), 404
    path, cur = [], n
    while cur["parent_id"]:
        cur = db.execute("SELECT * FROM basic_nodes WHERE id=?", (cur["parent_id"],)).fetchone()
        if not cur:
            break
        path.insert(0, {"id": cur["id"], "title": cur["title"]})
    sib = db.execute(
        "SELECT id,title FROM basic_nodes WHERE source_id=? AND level=? ORDER BY sort",
        (n["source_id"], n["level"])).fetchall()
    i = next((k for k, r in enumerate(sib) if r["id"] == nid), -1)
    return jsonify({
        "id": nid, "title": n["title"], "board": n["board"], "source": n["source"],
        "source_id": n["source_id"], "level": n["level"], "page": n["page_from"],
        "topic_id": n["topic_id"],
        "path": path, "blocks": _blocks(db, nid),
        "practice": _practice(db, n["topic_id"]),
        "prev": dict(sib[i - 1]) if i > 0 else None,
        "next": dict(sib[i + 1]) if 0 <= i < len(sib) - 1 else None})


@bp.get("/api/basics/sweep")
def basics_sweep():
    """整章速览：一个章节下所有考点连正文一次给全。

    和 /node 的分工：那个是「一个考点一屏、读完点下一个」，适合精读；这个是
    「一章摊开、一屏扫到底」，对的是速记资料原本的用法 —— 那些笔记本来就是
    印成「考点名｜要点串」一行一条的，考前扫的就是这个节奏，一条条点开反而慢。

    只往下取两层（章 → 考点 → 考点的子条目），再深的层级在这批资料里没出现过；
    真出现了也不该在速览里摊开，那是精读该干的事。
    """
    db = get_db()
    nid = request.args.get("nid", type=int)
    n = db.execute("SELECT * FROM basic_nodes WHERE id=?", (nid,)).fetchone() if nid else None
    if not n:
        return jsonify({"error": "章节不存在"}), 404
    kids = db.execute("SELECT * FROM basic_nodes WHERE parent_id=? ORDER BY sort",
                      (nid,)).fetchall()
    items = []
    for k in kids:
        sub = db.execute("SELECT * FROM basic_nodes WHERE parent_id=? ORDER BY sort",
                         (k["id"],)).fetchall()
        items.append({"id": k["id"], "title": k["title"], "page": k["page_from"],
                      "blocks": _blocks(db, k["id"]),
                      "kids": [{"id": x["id"], "title": x["title"],
                                "blocks": _blocks(db, x["id"])} for x in sub]})
    book = db.execute("SELECT title FROM basic_sources WHERE id=?", (n["source_id"],)).fetchone()
    return jsonify({"id": nid, "title": n["title"], "board": n["board"],
                    "source_id": n["source_id"], "book": book["title"] if book else "",
                    "blocks": _blocks(db, nid), "items": items})


@bp.get("/api/basics/compare")
def basics_compare():
    """对照视图：一个板块下所有已对齐的考点；带 topic_id 时给两边正文。"""
    board = (request.args.get("board") or "").strip()
    if board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    db = get_db()
    tid = request.args.get("topic_id", type=int)
    if not tid:
        rows = db.execute(
            "SELECT t.id, t.name, "
            "  SUM(m.source='youlu') ny, SUM(m.source='sanse') ns "
            "FROM basic_topics t LEFT JOIN basic_map m ON m.topic_id=t.id "
            "WHERE t.board=? GROUP BY t.id, t.name ORDER BY t.sort, t.id", (board,)).fetchall()
        return jsonify({"board": board, "topics": [
            {"id": r["id"], "name": r["name"], "youlu": r["ny"] or 0, "sanse": r["ns"] or 0}
            for r in rows]})
    t = db.execute("SELECT * FROM basic_topics WHERE id=? AND board=?", (tid, board)).fetchone()
    if not t:
        return jsonify({"error": "考点不存在"}), 404
    # 走 basic_map：一个考点两边各挂几条是常态（三色把「主旨概括」拆成 7 条思维）
    sides = {}
    for r in db.execute(
            "SELECT n.id,n.title,n.source,n.source_id,n.page_from FROM basic_map m "
            "JOIN basic_nodes n ON n.nkey=m.nkey AND n.source=m.source "
            "WHERE m.topic_id=? ORDER BY m.source, n.sort", (tid,)):
        sides.setdefault(r["source"], []).append(
            {"id": r["id"], "title": r["title"], "page": r["page_from"],
             "source_id": r["source_id"], "blocks": _blocks(db, r["id"])})
    return jsonify({"board": board, "topic": {"id": tid, "name": t["name"]},
                    "practice": _practice(db, tid),
                    "youlu": sides.get("youlu", []), "sanse": sides.get("sanse", [])})


@bp.get("/api/basics/page")
def basics_page():
    """原书某一页渲染成图，**按需生成、生成后缓存**。

    为什么要有这个：讲义里图形推理的图、数量/资料的分式和竖式，纯文本救不回来
    （「A/B 或 A/(1+r)」在 pdftotext 里就是几行错位的字符）。预渲染 698 页要
    两百多兆、还多数用不上；按需渲染一页 ~40ms，第二次直接走缓存文件。
    """
    sid = request.args.get("source_id", type=int)
    page = request.args.get("page", type=int)
    if not sid or not page or page < 1:
        return jsonify({"error": "参数无效"}), 400
    src = get_db().execute("SELECT stored_name,pages FROM basic_sources WHERE id=?",
                           (sid,)).fetchone()
    if not src or page > (src["pages"] or 0):
        return jsonify({"error": "页不存在"}), 404
    cache = os.path.join(UPLOADS, "basicfig")
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, "%d-%d.png" % (sid, page))
    if not os.path.exists(out):
        pdf = None
        root = os.path.join(UPLOADS, "drive")
        for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            p = os.path.join(root, d, src["stored_name"] or "")
            if src["stored_name"] and os.path.exists(p):
                pdf = p
                break
        if not pdf:
            return jsonify({"error": "原书文件不在了"}), 404
        try:
            subprocess.run(["pdftoppm", "-png", "-r", "130", "-f", str(page),
                            "-l", str(page), "-singlefile", pdf, out[:-4]],
                           check=True, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("basics 渲染原书页失败 sid=%s page=%s: %s", sid, page, e)
            return jsonify({"error": "渲染失败"}), 500
    return send_file(out, mimetype="image/png", max_age=86400)


# ---------------------------------------------------------------- 原书页 → Markdown
# 标题规则那套正则住在 mods/tomd.py（文件转 Markdown 的设施层）：原书页和整册转换
# 要的是**同一套口径**，两处各写一份的话，「1. 算不算标题」迟早在两边走样。
# 判据本身没变：只认部分/篇 → 章/节 → 第 N 条 → 一、 → （一），
# `1.` 和 `（1）` 一律只作分段 —— 照着教材排版定的「短的算小标题」，
# 套到党章知识点上就成了「12. 立国之本」是标题、「10. 基本路线：…」是正文。
from mods.tomd import (_PG_ANY_HEAD, _PG_ART, _PG_CHAP, _PG_CN, _PG_END, _PG_JUNK,  # noqa: E402
                       _PG_NUM, _PG_PAREN, _PG_PART, _PG_SUB, _PG_TERM)


def page_markdown(text):
    """原书一页的文本 → Markdown。

    为什么要有这个：「原书这一页」原先只给一张**图片** —— 看得见、搜不着、
    复制不了、手机上还得放大。而每一页的文字本来就存在 basic_raw 里，
    只是从没拿出来过。图片仍然留着（图形推理的图、竖式分式只有图救得回来），
    这里多给一个文字版。

    三件必须先做的事，缺一样排出来就是一地碎行：

      ① **标题跨行要接回去。** 居中的大标题被 pdftotext 按视觉行切开
         （`第一部分 公共管理与社会工作基` / `础知识`）。
      ② **段落的软换行要合并。** 这批书每行之间都空一行，逐行渲染的话
         一段话会碎成四五段。
      ③ **一行一条的写法要分开。** 扫描件笔记是「考点名：要点串」一行一条，
         按软换行规则会把整页糊成一大段 —— 和 ② 正好相反的需求，
         所以「短名词 + 冒号 + 长内容」单独作为分段信号。
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln.strip() and not _PG_JUNK.match(ln)]

    merged, i = [], 0
    while i < len(lines):
        cur = lines[i]
        if (_PG_PART.match(cur) or _PG_CHAP.match(cur)) and not _PG_END.search(cur):
            while (i + 1 < len(lines) and len(lines[i + 1].strip()) <= 12
                   and not _PG_ANY_HEAD.match(lines[i + 1])):
                i += 1
                cur += lines[i].strip()
        merged.append(cur)
        i += 1

    out, para = [], []

    def flush():
        """收一段。**「名词：内容」的加粗统一在这里做**，不在各个分支里各做各的 ——
        「政治职能：」和「经济职能：」在原书里一个占整行、一个和内容同行，
        走的是不同分支，分头加粗的结果就是同一页里一个粗一个不粗。"""
        if not para:
            return
        txt = "".join(para)
        if not txt.startswith("**"):
            mt = _PG_TERM.match(txt)
            if mt:
                txt = "**%s：**%s" % (mt.group(1).strip(), mt.group(2).strip())
        out.append(txt)
        para.clear()

    for ln in merged:
        t = ln.strip()
        if _PG_PART.match(t):
            flush()
            out.append("## " + t)
            continue
        m = _PG_CHAP.match(t)
        if m:
            flush()
            out.append("### %s %s" % (m.group(1).replace(" ", ""), m.group(2).strip()))
            continue
        m = _PG_ART.match(t)                       # 法规原文：条即一节
        if m:
            flush()
            # 法条是「第 N 条」后面**直接跟正文**，不像章节那样标题独占一行。
            # 整行当标题的话，标题会拖着半句正文、而且在行尾被截断
            # （`#### 第九条 地方党委领导本地区信访工作，贯彻落实党中央关于信访工作的方`）。
            # 所以条号单独成小标题，正文进 para 走正常的续行合并。
            out.append("#### " + m.group(1).replace(" ", ""))
            body = m.group(2).strip()
            if body:
                para.append(body)
            continue
        m = _PG_CN.match(t)
        if m:
            flush()
            out.append("#### %s%s" % (m.group(1).replace(" ", ""), m.group(2).strip()))
            continue
        m = _PG_SUB.match(t)
        if m:
            # 「（一）公共管理的主体」是小标题；法条里的「（一）研究分析全国信访形势；」
            # 是分项，短的算标题、长的算分项段落
            body = m.group(2).strip()
            flush()
            if len(body) <= 20:
                out.append("**（%s）%s**" % (m.group(1), body))
            else:
                # 法条里的分项是长句，常常还要跨行 —— 进 para 才能和续行合并，
                # 直接写进 out 的话「…事关党和国家工作大局、」和它的下半句会成两段
                para.append("（%s）%s" % (m.group(1), body))
            continue
        m = _PG_PAREN.match(t)
        if m:
            body = m.group(2).strip()
            # 「（1）军事保卫；（2）外交；…」是一句话里的并列枚举，原书排成了阶梯状
            # 的好几行。判据只用一条：**上一段还没收尾，这句话就还没说完**。
            if para and not re.search(r"[。！？!?]\s*$", para[-1]):
                para.append("（%s）%s" % (m.group(1), body))
                if re.search(r"[。！？!?]\s*$", body):
                    flush()
                continue
            flush()
            para.append("（%s）%s" % (m.group(1), body))
            if len(body) <= 24:                     # 「（1）含义」是小标题式的，别把正文粘上来
                flush()
            continue
        m = _PG_NUM.match(t)
        if m:                                       # 序号条目：每条独立成段，不分标题正文
            flush()
            body = m.group(2).strip()
            para.append("%s. %s" % (m.group(1), body))
            # 短条目（「1. 政府职能」这种小标题式的）当场收尾，否则下一行的
            # 「（1）含义」会认为「这句话还没说完」而并进来，粘成一长条
            if len(body) <= 24:
                flush()
            continue
        if _PG_TERM.match(t):                       # 「考点名：要点串」一行一条
            flush()
            para.append(t)
            continue
        para.append(t)
        if _PG_END.search(t) and len(t) > 24:
            flush()
    flush()
    return "\n\n".join(x for x in out if x.strip())


@bp.get("/api/basics/pagetext")
def basics_pagetext():
    """原书某一页的**文字版**（Markdown）。图片那份仍在 /api/basics/page。"""
    db = get_db()
    sid = request.args.get("source_id", type=int)
    page = request.args.get("page", type=int)
    if not sid or not page or page < 1:
        return jsonify({"error": "参数无效"}), 400
    r = db.execute("SELECT text FROM basic_raw WHERE source_id=? AND page=?",
                   (sid, page)).fetchone()
    if r is None:
        return jsonify({"error": "这一页没有存原文"}), 404
    md = page_markdown(r["text"])
    return jsonify({"source_id": sid, "page": page, "md": md,
                    "empty": not md.strip()})


@bp.get("/api/boardkb")
def boardkb_get():
    board = (request.args.get("board") or "").strip()
    if board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    db = get_db()
    ai = db.execute("SELECT content FROM board_kb WHERE board=?", (board,)).fetchone()
    pts = db.execute("SELECT id,content,created_at FROM board_points WHERE user_id=? AND board=? ORDER BY id DESC",
                     (uid(), board)).fetchall()
    return jsonify({"board": board, "ai": ai["content"] if ai else "",
                    "points": [{"id": r["id"], "content": r["content"], "created_at": r["created_at"]} for r in pts]})


@bp.post("/api/boardkb/generate")
def boardkb_generate():
    data = request.get_json(silent=True) or {}
    board = (data.get("board") or "").strip()
    if board not in ALL_BOARDS:
        return jsonify({"error": "板块无效"}), 400
    cached = get_db().execute("SELECT content FROM board_kb WHERE board=?", (board,)).fetchone()
    if cached and not data.get("force"):
        return jsonify({"content": cached["content"], "cached": True})
    sec = _BOARD_SEC.get(board, "行测")
    prompt = (
        "你是资深公务员考试辅导老师。请为「%s · %s」板块系统梳理"
        "「基础知识 + 方法技巧」，面向基础薄弱的考生，用简体中文、Markdown 输出，"
        "分这几节，内容要具体可操作：\n"
        "## 一、这个板块考什么\n## 二、必备基础知识（概念/公式/常识要点）\n"
        "## 三、核心方法与解题技巧\n## 四、常见题型与应对思路\n"
        "## 五、易错点与提分建议\n"
        "要求：每节都要写完整、写到位，覆盖该板块主要考点，不要中途省略或截断。" % (sec, board))
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考辅导老师，讲解系统、具体、条理清晰，用简体中文 Markdown。务必输出完整、不要截断。"},
         {"role": "user", "content": prompt}], temperature=0.5, max_tokens=8000)
    if err:
        return err
    db = get_db()
    db.execute("INSERT OR REPLACE INTO board_kb(board,content) VALUES(?,?)", (board, reply))
    db.commit()
    return jsonify({"content": reply, "cached": False})


@bp.post("/api/boardkb/point")
def boardkb_add_point():
    data = request.get_json(silent=True) or {}
    board = (data.get("board") or "").strip()
    content = (data.get("content") or "").strip()
    if board not in ALL_BOARDS or not content:
        return jsonify({"error": "请填写内容"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO board_points(user_id,board,content) VALUES(?,?,?)", (uid(), board, content))
    db.commit()
    return jsonify({"id": cur.lastrowid, "content": content}), 201


@bp.delete("/api/boardkb/point/<int:pid>")
def boardkb_del_point(pid):
    get_db().execute("DELETE FROM board_points WHERE id=? AND user_id=?", (pid, uid()))
    get_db().commit()
    return jsonify({"ok": True})
