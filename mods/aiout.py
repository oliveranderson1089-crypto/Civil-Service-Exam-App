"""AI 产出：助手生成的东西先落在这里，再由用户决定投到哪。

为什么单开一个容器，而不是让 AI 直接往资料库/云盘里写：
生成和投放是两件事。生成随时可能不满意（重来一遍就行），投放是**会被别人看到**的
动作。混在一起的话，AI 每写一版都往资料库里堆一份，用户还得回头去删。

**它是中转站，不是第二个云盘**：默认只留 RETAIN_DAYS 天，用户主动「归档」才免清理。
不守住这个定位，半年后这里会堆满谁也不记得的东西，跟云盘互相打架。

投放一律复用各容器**自己的**入库助手（资料库 finish_material_upload、
云盘 _finish_upload）：去重、配额、目录这些规矩归它们管，这里再写一遍迟早走样。
"""
import io
import os
import re
import tempfile

from flask import Blueprint, jsonify, request, send_file

from core import get_db, log, uid

bp = Blueprint("aiout", __name__)

RETAIN_DAYS = 30            # 没归档的产出留多久
KINDS = ("md", "txt", "pdf")
TITLE_MAX = 80
BODY_MAX = 200000           # 单份产出的正文上限（一份长文档撑死几万字）


def _sweep(db):
    """清掉过期且没归档的产出。跟着列表接口走，不另起定时器 ——
    这东西一天被看几次，用不着一个专门的 timer。"""
    try:
        db.execute("DELETE FROM ai_outputs WHERE kept=0 AND user_id=? "
                   "AND created_at < datetime('now','localtime',?)",
                   (uid(), "-%d day" % RETAIN_DAYS))
        db.commit()
    except Exception:
        log.debug("AI 产出清理失败（不影响使用）", exc_info=True)


def create_output(db, user_id, title, body, kind="md", chat_id=None, msg_id=None):
    """落一份产出，返回它的 id。工具层（mods/agent.py）和对话汇总都走这里。"""
    kind = kind if kind in KINDS else "md"
    title = (title or "未命名").strip()[:TITLE_MAX] or "未命名"
    body = (body or "")[:BODY_MAX]
    cur = db.execute(
        "INSERT INTO ai_outputs(user_id,chat_id,msg_id,kind,title,body,size) VALUES(?,?,?,?,?,?,?)",
        (user_id, chat_id, msg_id, kind, title, body, len(body)))
    db.commit()
    return cur.lastrowid


def _row(r):
    return {"id": r["id"], "kind": r["kind"], "title": r["title"], "size": r["size"],
            "kept": bool(r["kept"]), "sent": r["sent"] or "", "chat_id": r["chat_id"],
            "created_at": r["created_at"]}


@bp.get("/api/aiout")
def aiout_list():
    db = get_db()
    _sweep(db)
    rows = db.execute("SELECT * FROM ai_outputs WHERE user_id=? ORDER BY id DESC LIMIT 100",
                      (uid(),)).fetchall()
    return jsonify({"items": [_row(r) for r in rows], "retain_days": RETAIN_DAYS})


@bp.get("/api/aiout/<int:oid>")
def aiout_get(oid):
    r = get_db().execute("SELECT * FROM ai_outputs WHERE id=? AND user_id=?",
                         (oid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    return jsonify(dict(_row(r), body=r["body"] or ""))


@bp.put("/api/aiout/<int:oid>")
def aiout_update(oid):
    data = request.get_json(silent=True) or {}
    db = get_db()
    if not db.execute("SELECT 1 FROM ai_outputs WHERE id=? AND user_id=?", (oid, uid())).fetchone():
        return jsonify({"error": "未找到"}), 404
    if "title" in data:
        t = (data.get("title") or "").strip()[:TITLE_MAX]
        if not t:
            return jsonify({"error": "标题不能为空"}), 400
        db.execute("UPDATE ai_outputs SET title=? WHERE id=?", (t, oid))
    if "kept" in data:
        # 归档 = 免于 30 天清理。它不搬动任何东西，只是「我还要用这个」
        db.execute("UPDATE ai_outputs SET kept=? WHERE id=?", (1 if data.get("kept") else 0, oid))
    db.commit()
    r = db.execute("SELECT * FROM ai_outputs WHERE id=?", (oid,)).fetchone()
    return jsonify(_row(r))


@bp.delete("/api/aiout/<int:oid>")
def aiout_del(oid):
    db = get_db()
    db.execute("DELETE FROM ai_outputs WHERE id=? AND user_id=?", (oid, uid()))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- 出文件
_MD_H = re.compile(r"^(#{1,4})\s+(.*)$")
_MD_LI = re.compile(r"^\s*([-*·]|\d+[.、])\s+(.*)$")
_MD_STRONG = re.compile(r"\*\*(.+?)\*\*")


def _esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_pdf(title, body):
    """把一份 Markdown 产出渲染成 PDF（返回 bytes）。

    只认标题、列表、加粗、引用这几样 —— AI 写出来的就这几样，为完整的 Markdown
    引一个渲染库不值当。字体走 ensure_pdf_font()，中文不会变成方框。
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from mods.pdfkit import ensure_pdf_font

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=title or "AI 产出")
    f = ensure_pdf_font()
    st_t = ParagraphStyle("t", fontName=f, fontSize=19, leading=26, spaceAfter=10)
    st_h = [ParagraphStyle("h%d" % i, fontName=f, fontSize=sz, leading=sz + 7,
                           spaceBefore=9, spaceAfter=4)
            for i, sz in enumerate((16, 14, 12.5, 11.5), 1)]
    st_p = ParagraphStyle("p", fontName=f, fontSize=10.5, leading=17, spaceAfter=4)
    st_li = ParagraphStyle("li", fontName=f, fontSize=10.5, leading=17, leftIndent=12, spaceAfter=2)
    st_q = ParagraphStyle("q", fontName=f, fontSize=10.5, leading=17, leftIndent=12,
                          textColor=colors.HexColor("#555555"), spaceAfter=4)

    def inline(t):
        return _MD_STRONG.sub(r"<b>\1</b>", _esc(t))

    story = [Paragraph(inline(title or "AI 产出"), st_t)]
    for raw in (body or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            story.append(Spacer(1, 5))
            continue
        m = _MD_H.match(line)
        if m:
            story.append(Paragraph(inline(m.group(2)), st_h[min(len(m.group(1)), 4) - 1]))
            continue
        m = _MD_LI.match(line)
        if m:
            story.append(Paragraph("• " + inline(m.group(2)), st_li))
            continue
        if line.lstrip().startswith(">"):
            story.append(Paragraph(inline(line.lstrip()[1:].strip()), st_q))
            continue
        story.append(Paragraph(inline(line), st_p))
    doc.build(story)
    return buf.getvalue()


def output_bytes(r):
    """一份产出的文件内容 + 文件名。pdf 现渲染（不落盘：产出随时会被清掉，
    留一份 pdf 在盘上只是又一样要跟着清的东西）。"""
    title = r["title"] or "AI 产出"
    safe = re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", title)[:60] or "AI 产出"
    if r["kind"] == "pdf":
        return md_to_pdf(title, r["body"] or ""), safe + ".pdf", "application/pdf"
    ext = ".txt" if r["kind"] == "txt" else ".md"
    return (r["body"] or "").encode("utf-8"), safe + ext, "text/plain; charset=utf-8"


@bp.get("/api/aiout/<int:oid>/download")
def aiout_download(oid):
    r = get_db().execute("SELECT * FROM ai_outputs WHERE id=? AND user_id=?",
                         (oid, uid())).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    try:
        data, name, mime = output_bytes(r)
    except Exception as e:
        log.warning("AI 产出出文件失败：%r", e)
        return jsonify({"error": "生成文件失败：%s" % e}), 500
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=name)


DESTS = ("material", "drive", "note")


def deliver(db, user_id, oid, dest, board="", folder=""):
    """把一份产出投到别的容器里，返回 (成功?, 给人看的一句话, 落库那一行或 None)。

    HTTP 接口和 AI 工具**共用这一条**：投放这件事有配额、有去重、有目录，
    抄成两份迟早出现「网页上投得进去、让 AI 投就报错」。

    资料库/云盘一律走各自的入库助手，规矩归它们管；小记是纯文本，没必要绕文件。
    """
    r = db.execute("SELECT * FROM ai_outputs WHERE id=? AND user_id=?", (oid, user_id)).fetchone()
    if not r:
        return False, "找不到这份产出（id=%s）。" % oid, None
    if dest not in DESTS:
        return False, "不支持的目的地：%s" % dest, None

    if dest == "note":
        db.execute("INSERT INTO notes(user_id,content) VALUES(?,?)",
                   (user_id, ("# " + (r["title"] or "") + "\n\n" + (r["body"] or ""))[:BODY_MAX]))
        db.commit()
        return True, _mark(db, oid, r, "小记"), None

    try:
        payload, name, mime = output_bytes(r)
    except Exception as e:
        log.warning("AI 产出出文件失败：%r", e)
        return False, "生成文件失败：%s" % e, None
    fd, tmp = tempfile.mkstemp(prefix="aiout_")
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    try:
        if dest == "material":
            from mods.materials import finish_material_upload
            row, err = finish_material_upload(db, tmp, name, board, r["title"], mime)
        else:
            from mods.social import _finish_upload
            row, err = _finish_upload(db, folder, name, tmp, mime)
    except Exception as e:
        log.warning("AI 产出投放失败：%r", e)
        return False, "投放失败：%s" % e, None
    finally:
        # 入库助手成功时会把临时文件搬走；失败或异常时它还在，别留一地垃圾
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                log.debug("临时文件没删掉", exc_info=True)
    if err:
        # err 是 (json响应, 状态码)：配额不够这类。把里面那句话原样带出来
        try:
            return False, err[0].get_json().get("error") or "投放失败", None
        except Exception:
            return False, "投放失败", None
    return True, _mark(db, oid, r, "资料库" if dest == "material" else "云盘"), row


def _mark(db, oid, r, where):
    """记一笔「投到过哪儿」，并顺手归档 —— 都投出去了，显然还想留着。"""
    sent = "、".join(x for x in [(r["sent"] or ""), where] if x)
    db.execute("UPDATE ai_outputs SET sent=?, kept=1 WHERE id=?", (sent[:120], oid))
    db.commit()
    return "已把《%s》投到%s（并顺手归了档，不会被自动清理）。" % (r["title"] or "", where)


def mark_sent(db, oid, where):
    """记一笔「投到过哪儿」并顺手归档。聊天转发在 mods/social.py 里，也走这一条。"""
    r = db.execute("SELECT * FROM ai_outputs WHERE id=?", (oid,)).fetchone()
    return _mark(db, oid, r, where) if r else ""


@bp.post("/api/aiout/<int:oid>/send")
def aiout_send(oid):
    data = request.get_json(silent=True) or {}
    dest = data.get("dest")
    if dest not in DESTS:
        return jsonify({"error": "不支持的目的地"}), 400
    ok, msg, _row = deliver(get_db(), uid(), oid, dest,
                      board=(data.get("board") or ""), folder=(data.get("folder") or ""))
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "where": {"material": "资料库", "drive": "云盘",
                                          "note": "小记"}[dest], "msg": msg})

# ---------------------------------------------------------------- 共享给队友
def _picked_mates(db, me, raw):
    """请求里的收件人 → 确实是我队友的那些。不是队友的一律丢掉（防越权）。"""
    from mods.materials import teammates
    mates = {m["id"] for m in teammates(db, me)}
    out = []
    for x in (raw or []):
        try:
            x = int(x)
        except (TypeError, ValueError):
            continue
        if x in mates and x not in out:
            out.append(x)
    return out


@bp.get("/api/aiout/<int:oid>/team")
def aiout_team_get(oid):
    """能共享给谁：我的队友。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM ai_outputs WHERE id=? AND user_id=?", (oid, uid())).fetchone():
        return jsonify({"error": "未找到"}), 404
    from mods.materials import teammates
    return jsonify({"members": [{"id": m["id"], "username": m["username"], "shared": False}
                                for m in teammates(db, uid())]})


@bp.post("/api/aiout/<int:oid>/team")
def aiout_team_set(oid):
    """共享给队友 = 先把这份产出投进**自己的**资料库，再把那一行共享出去。

    不另造一套共享表：这一页是中转站，30 天就清，别人来这儿看等于看一个随时会消失的
    东西。「让队友长期看得到」在这个应用里只有一种实现 —— 资料库的 material_shares，
    所以这里走 deliver(dest='material') 再挂共享，配额、去重、权限全归资料库管。

    每点一次都会新投一份进资料库（不像资料库那边是「整份覆盖」）：产出本来就是
    一次性的东西，改了再共享是常事，硬去认「上次投的是哪一份」只会认错。
    """
    db, me = get_db(), uid()
    to = _picked_mates(db, me, (request.get_json(silent=True) or {}).get("to"))
    if not to:
        return jsonify({"error": "选一个队友再共享"}), 400
    ok, msg, row = deliver(db, me, oid, "material")
    if not ok:
        return jsonify({"error": msg}), 400
    for t in to:
        db.execute("INSERT OR IGNORE INTO material_shares(material_id,owner_id,to_user) "
                   "VALUES(?,?,?)", (row["id"], me, t))
    db.commit()
    return jsonify({"ok": True, "n": len(to), "material_id": row["id"], "msg": msg})
