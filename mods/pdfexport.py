"""PDF 导出：积累本导出成 PDF（含默写版）。"""
import io
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from core import _truthy, get_db, uid
from mods.pdfkit import ensure_pdf_font

bp = Blueprint("pdfexport", __name__)


def build_pdf(entries, opts):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="公考·成语词语积累")
    f = ensure_pdf_font()
    st_title = ParagraphStyle("t", fontName=f, fontSize=20, leading=26, alignment=1, spaceAfter=2)
    st_sub = ParagraphStyle("s", fontName=f, fontSize=10, leading=14, alignment=1,
                            textColor=colors.grey, spaceAfter=10)
    st_word = ParagraphStyle("w", fontName=f, fontSize=15, leading=20)
    st_py = ParagraphStyle("py", fontName=f, fontSize=11, leading=20,
                           textColor=colors.HexColor("#1a6fb5"), alignment=2)
    st_label = ParagraphStyle("lb", fontName=f, fontSize=10.5, leading=16,
                              textColor=colors.HexColor("#444444"))
    st_blank = ParagraphStyle("bk", fontName=f, fontSize=10.5, leading=22,
                              textColor=colors.HexColor("#bbbbbb"))
    story = [Paragraph("公考·选词填空　成语 / 词语积累", st_title),
             Paragraph(datetime.now().strftime("导出于 %Y-%m-%d %H:%M") +
                       f"　共 {len(entries)} 条" +
                       ("　【默写版】" if opts.get("mode") == "recite" else ""), st_sub)]
    recite = opts.get("mode") == "recite"
    inc_der, inc_exa, inc_note = opts.get("derivation", True), opts.get("example", True), opts.get("note", True)
    for i, e in enumerate(entries, 1):
        word = (e.get("word") or "").replace("\n", " ")
        head = Table([[Paragraph(f'<b>{i}. {word}</b>', st_word),
                       Paragraph(e.get("pinyin") or "", st_py)]], colWidths=[None, 55 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story.append(head)

        def field(label, value):
            value = (value or "").strip().replace("\n", " ")
            if value:
                story.append(Paragraph(f'<font color="#888888">{label}</font>　{value}', st_label))
        if recite:
            story.append(Paragraph("释义：______________________________________________", st_blank))
        else:
            field("释义", e.get("explanation"))
            if inc_der:
                field("出处", e.get("derivation"))
            if inc_exa:
                field("例句", e.get("example"))
        if inc_note and e.get("note"):
            field("笔记", e.get("note"))
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#dddddd")))
        story.append(Spacer(1, 6))
    doc.build(story)
    buf.seek(0)
    return buf



@bp.route("/api/export", methods=["GET", "POST"])
def api_export():
    if request.method == "GET":
        a = request.args
        data = {"mode": a.get("mode", "study"), "category": a.get("category", ""),
                "starred": _truthy(a.get("starred"), False), "derivation": _truthy(a.get("der")),
                "example": _truthy(a.get("exa")), "note": _truthy(a.get("note"))}
        ids_s = a.get("ids", "")
        if ids_s:
            data["ids"] = [int(x) for x in ids_s.split(",") if x.strip().isdigit()]
    else:
        data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    ids = data.get("ids")
    if ids:
        qmarks = ",".join("?" * len(ids))
        rows = db.execute(
            f"SELECT * FROM entries WHERE id IN ({qmarks}) AND user_id=? ORDER BY id DESC",
            ids + [uid()]).fetchall()
    else:
        sql = "SELECT * FROM entries WHERE user_id=?"
        args = [uid()]
        cat = (data.get("category") or "").strip()
        if cat in ("成语", "词语"):
            sql += " AND category=?"
            args.append(cat)
        if data.get("starred"):
            sql += " AND starred=1"
        sql += " ORDER BY id DESC"
        rows = db.execute(sql, args).fetchall()
    entries = [dict(r) for r in rows]
    if not entries:
        return jsonify({"error": "没有可导出的内容"}), 400
    opts = {"mode": data.get("mode", "study"), "derivation": data.get("derivation", True),
            "example": data.get("example", True), "note": data.get("note", True)}
    pdf = build_pdf(entries, opts)
    fname = "公考积累_%s%s.pdf" % (datetime.now().strftime("%Y%m%d_%H%M"),
                                 "_默写版" if opts["mode"] == "recite" else "")
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=fname)
