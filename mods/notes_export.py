"""小记导出：把一条条小记导成能带走的文件。

六种格式，用途各不相同，不是同一件事换皮：
  · md   —— 带走去别的笔记软件（Obsidian/语雀/Notion 都吃 Markdown）
  · txt  —— 打印、贴进聊天框，把 Markdown 记号剥干净
  · html —— 一个文件双击就能看，**图片以 base64 内嵌**，不依赖本服务
  · pdf  —— 打印/存档，版式固定
  · json —— 备份和迁移，字段原样，机器读
  · zip  —— 唯一带得走**附件原件**的格式：md + json + images/ + files/

筛选口径必须和界面上看到的一致（板块 / 标签 / 搜索词），否则「导出当前这些」
会名不副实 —— 搜索那一条前端是自己过滤的（loadFeed），这里照抄同一套判断。
"""
import base64
import io
import json
import os
import re
import zipfile
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from core import UPLOADS, _truthy, get_db, log, uid
from mods.notes import _note_dict

bp = Blueprint("notes_export", __name__)

FMTS = ("md", "txt", "html", "pdf", "json", "zip")
WEB_IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


# ---------------- 取数 ----------------

def _collect(f):
    """按筛选条件取出要导的小记（永远只在自己名下找）。"""
    db = get_db()
    sql = "SELECT * FROM notes WHERE user_id=?"
    args = [uid()]
    ids = [int(x) for x in (f.get("ids") or []) if str(x).strip().lstrip("-").isdigit()]
    if ids:
        sql += " AND id IN (%s)" % ",".join("?" * len(ids))
        args += ids
    board = (f.get("board") or "").strip()
    if board:
        sql += " AND board=?"
        args.append(board)
    sql += " ORDER BY id DESC"
    items = [_note_dict(r) for r in db.execute(sql, args).fetchall()]
    tag = (f.get("tag") or "").strip()
    if tag:
        items = [n for n in items if tag in n["tags"]]
    q = (f.get("q") or "").strip()
    if q:      # 和 notes.js loadFeed 里那段前端过滤同一口径：正文 / 标签 / 待办
        items = [n for n in items
                 if q in (n["content"] or "")
                 or any(q in t for t in n["tags"])
                 or any(q in (t.get("text") or "") for t in n["todos"])]
    if f.get("order") == "asc":
        items.reverse()
    return items


def _img_path(n, i):
    return os.path.join(UPLOADS, str(uid()), n["img_files"][i])


def _att_path(a):
    return os.path.join(UPLOADS, str(uid()), a.get("file", ""))


def _img_rel(n, i):
    """包内图片路径。库里存的是 note_<uuid>.png，解开一看全是乱码名、对不上哪条小记，
    所以按「小记编号-序号」重排。**md 和 zip 必须用同一份口径** —— 各写一次的那一版，
    单文件 md 引用的是库里的存储名、zip 里放的是重排名，照着 md 去包里找图必然找不到。"""
    return "images/%04d-%d%s" % (n["id"], i + 1, os.path.splitext(n["img_files"][i])[1].lower())


def _att_rel(n, i):
    a = n["att_files"][i]
    return "files/%04d-%s" % (n["id"], _safe(a.get("name") or a.get("file")))


def _safe(name):
    """给压缩包里的文件名去掉路径分隔符和控制字符（附件名是用户传的）。"""
    name = re.sub(r"[\\/\x00-\x1f]", "_", name or "").strip() or "file"
    return name[:80]


# ---------------- Markdown 极简解析 ----------------
# 只认小记编辑器提示里写的那几种（标题 / 加粗 / 列表 / 引用 / 代码 / 链接 / 分隔线）。
# 单独引个 markdown 库不值当：HTML 和 PDF 要的是**同一份结构**，各自渲染，
# 一个库只解决 HTML 那一半，PDF 那半还得再写一遍。

_RE_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_EM = re.compile(r"(?<!\*)\*(?!\s)([^*]+?)\*(?!\*)")
_RE_CODE = re.compile(r"`([^`]+)`")


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s, plain=False):
    """行内标记 → HTML 片段（reportlab 也认 b/i/font/a 这几个标签）。"""
    if plain:
        s = _RE_LINK.sub(lambda m: m.group(1) or m.group(2), s)
        return _RE_CODE.sub(r"\1", _RE_EM.sub(r"\1", _RE_BOLD.sub(r"\1", s)))
    out = _esc(s)
    out = _RE_CODE.sub(lambda m: '<font face="Courier">%s</font>' % m.group(1), out)
    out = _RE_BOLD.sub(r"<b>\1</b>", out)
    out = _RE_EM.sub(r"<i>\1</i>", out)
    out = _RE_LINK.sub(lambda m: '<a href="%s" color="#1a6fb5">%s</a>'
                       % (m.group(2), m.group(1) or m.group(2)), out)
    return out


def _blocks(text):
    """正文 → [(kind, text)]；kind ∈ h1..h6 / p / ul / ol / quote / code / hr。"""
    out, code, buf = [], False, []
    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if code:
                out.append(("code", "\n".join(buf)))
                buf = []
            code = not code
            continue
        if code:
            buf.append(raw)
            continue
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append(("hr", ""))
        elif re.match(r"^#{1,6}\s", s):
            lv = len(s) - len(s.lstrip("#"))
            out.append(("h%d" % lv, s[lv:].strip()))
        elif re.match(r"^>\s?", s):
            out.append(("quote", re.sub(r"^>\s?", "", s)))
        elif re.match(r"^[-*+]\s", s):
            out.append(("ul", s[2:].strip()))
        elif re.match(r"^\d+[.)]\s", s):
            out.append(("ol", re.sub(r"^\d+[.)]\s", "", s)))
        else:
            out.append(("p", s))
    if code and buf:                      # 代码块没闭合也别把内容吞了
        out.append(("code", "\n".join(buf)))
    return out


# ---------------- 各格式 ----------------

def _head_line(n, o):
    """每条上面那行小字：时间 · 板块。一个开关管两样 —— 它们是同一件事
    （「这条是什么时候、归在哪」），拆成两个勾选只是给人添选择。
    注意别把这个开关叫 board：那个名字被筛选参数占着（_args 里两者同层）。"""
    if not o.get("time", True):
        return ""
    bits = [n["created_at"] or ""]
    if n["board"]:
        bits.append(n["board"])
    return "　·　".join([b for b in bits if b])


def build_md(items, o, packed=False):
    """packed=True 表示这份 md 待会儿要放进 ZIP，图片附件就在旁边。
    两种情况下的**引用路径完全一样**（见 _img_rel），差的只是顶上那句提示。"""
    L = ["# 小记导出", "",
         datetime.now().strftime("导出于 %Y-%m-%d %H:%M") + "　共 %d 条" % len(items), ""]
    if not packed and any(n["img_files"] or n["att_files"] for n in items):
        L += ["> 图片和附件没有随这个单文件走。导出 ZIP 可以拿到原件 —— "
              "包里的路径和下面这些引用一一对应。", ""]
    for n in items:
        L.append("---")
        L.append("")
        h = _head_line(n, o)
        if h:
            L.append("## " + h)
            L.append("")
        if n["content"]:
            L.append(n["content"])
            L.append("")
        if o.get("todos", True) and n["todos"]:
            L += ["- [%s] %s" % ("x" if t.get("done") else " ", t.get("text") or "")
                  for t in n["todos"]] + [""]
        for i in range(len(n["img_files"])):
            L.append("![图片%d](%s)" % (i + 1, _img_rel(n, i)))
        if n["img_files"]:
            L.append("")
        for i, a in enumerate(n["att_files"]):
            L.append("📎 [%s](%s)" % (a.get("name") or a.get("file"), _att_rel(n, i)))
        if n["att_files"]:
            L.append("")
        if o.get("tags", True) and n["tags"]:
            L.append(" ".join("#" + t for t in n["tags"]))
            L.append("")
    return "\n".join(L).rstrip() + "\n"


def build_txt(items, o):
    L = ["小记导出", datetime.now().strftime("导出于 %Y-%m-%d %H:%M") + "　共 %d 条" % len(items)]
    for n in items:
        L += ["", "─" * 36]
        h = _head_line(n, o)
        if h:
            L.append(h)
        for kind, txt in _blocks(n["content"]):
            t = _inline(txt, plain=True)
            if kind == "hr":
                L.append("─" * 20)
            elif kind.startswith("h"):
                L += ["", "【%s】" % t]
            elif kind == "ul":
                L.append("· " + t)
            elif kind == "ol":
                L.append("  " + t)
            elif kind == "quote":
                L.append("| " + t)
            elif kind == "code":
                L += ["    " + x for x in txt.split("\n")]
            else:
                L.append(t)
        if o.get("todos", True) and n["todos"]:
            L += ["%s %s" % ("☑" if t.get("done") else "☐", t.get("text") or "")
                  for t in n["todos"]]
        if n["img_files"]:
            L.append("（图片 %d 张）" % len(n["img_files"]))
        for a in n["att_files"]:
            L.append("（附件：%s）" % (a.get("name") or a.get("file")))
        if o.get("tags", True) and n["tags"]:
            L.append(" ".join("#" + t for t in n["tags"]))
    return "\n".join(L) + "\n"


def _img_data_uri(path):
    """内嵌进 HTML 的图片。webp 之外的怪格式（HEIC 等）转成 PNG，
    否则双击打开是个裂图 —— 单文件 HTML 的意义就是拿到哪都能看。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in WEB_IMG_MIME:
            with open(path, "rb") as fp:
                return "data:%s;base64,%s" % (WEB_IMG_MIME[ext],
                                              base64.b64encode(fp.read()).decode())
        buf = _to_png(path)
        if not buf:
            return ""
        return "data:image/png;base64,%s" % base64.b64encode(buf.getvalue()).decode()
    except Exception:
        log.debug("图片内嵌失败：%s", path, exc_info=True)
        return ""


def _to_png(path, max_side=1600):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    try:
        im = Image.open(path)
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if max(im.size) > max_side:
            sc = max_side / float(max(im.size))
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        buf.seek(0)
        return buf
    except Exception:
        log.debug("图片转 PNG 失败：%s", path, exc_info=True)
        return None


HTML_CSS = """
:root{--bg:#f7f7f8;--card:#fff;--fg:#22252a;--dim:#8a9099;--line:#e6e8ec;--acc:#1a6fb5}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--card:#1e2126;--fg:#e6e8ec;--dim:#8a9099;--line:#2c3037;--acc:#6fb0e8}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
  font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:760px;margin:0 auto}
h1.top{font-size:22px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin:0 0 20px}
.note{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;margin:0 0 14px}
.meta{color:var(--dim);font-size:12.5px;margin-bottom:8px}
.note h1,.note h2,.note h3,.note h4{font-size:16px;margin:12px 0 6px}
.note p{margin:6px 0}
.note ul,.note ol{margin:6px 0;padding-left:22px}
blockquote{margin:8px 0;padding:2px 12px;border-left:3px solid var(--line);color:var(--dim)}
pre{background:rgba(127,127,127,.12);padding:10px 12px;border-radius:8px;overflow-x:auto}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
hr{border:0;border-top:1px solid var(--line);margin:10px 0}
.todo{margin:3px 0}.todo.done{color:var(--dim);text-decoration:line-through}
.imgs{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.imgs img{max-width:100%;max-height:360px;border-radius:8px;border:1px solid var(--line)}
.atts{color:var(--dim);font-size:13px;margin:6px 0}
.tags{margin-top:8px}
.tag{display:inline-block;background:rgba(127,127,127,.14);color:var(--acc);
  border-radius:999px;padding:1px 9px;font-size:12.5px;margin:2px 6px 2px 0}
a{color:var(--acc)}
"""


def build_html(items, o):
    P = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         "<title>小记导出</title><style>%s</style></head><body><div class=wrap>" % HTML_CSS,
         "<h1 class=top>小记导出</h1>",
         '<p class=sub>%s　共 %d 条</p>' % (datetime.now().strftime("导出于 %Y-%m-%d %H:%M"), len(items))]
    for n in items:
        P.append("<div class=note>")
        h = _head_line(n, o)
        if h:
            P.append("<div class=meta>%s</div>" % _esc(h))
        P.append(_blocks_html(n["content"]))
        if o.get("todos", True) and n["todos"]:
            P += ['<div class="todo%s">%s %s</div>'
                  % (" done" if t.get("done") else "", "☑" if t.get("done") else "☐",
                     _esc(t.get("text") or "")) for t in n["todos"]]
        if o.get("imgs", True) and n["img_files"]:
            src = [_img_data_uri(_img_path(n, i)) for i in range(len(n["img_files"]))]
            src = [s for s in src if s]
            if src:
                P.append("<div class=imgs>%s</div>" % "".join('<img src="%s">' % s for s in src))
        for a in n["att_files"]:
            P.append("<div class=atts>📎 %s</div>" % _esc(a.get("name") or a.get("file")))
        if o.get("tags", True) and n["tags"]:
            P.append("<div class=tags>%s</div>"
                     % "".join('<span class=tag># %s</span>' % _esc(t) for t in n["tags"]))
        P.append("</div>")
    P.append("</div></body></html>")
    return "\n".join(P)


def _blocks_html(text):
    out, listk = [], None
    for kind, txt in _blocks(text):
        if kind in ("ul", "ol"):
            if listk != kind:
                if listk:
                    out.append("</%s>" % listk)
                out.append("<%s>" % kind)
                listk = kind
            out.append("<li>%s</li>" % _inline(txt))
            continue
        if listk:
            out.append("</%s>" % listk)
            listk = None
        if kind == "hr":
            out.append("<hr>")
        elif kind == "quote":
            out.append("<blockquote>%s</blockquote>" % _inline(txt))
        elif kind == "code":
            out.append("<pre><code>%s</code></pre>" % _esc(txt))
        elif kind.startswith("h"):
            out.append("<%s>%s</%s>" % (kind, _inline(txt), kind))
        else:
            out.append("<p>%s</p>" % _inline(txt))
    if listk:
        out.append("</%s>" % listk)
    return "\n".join(out)


def build_pdf(items, o):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, Image, ListFlowable, ListItem,
                                    Paragraph, SimpleDocTemplate, Spacer)

    from mods.pdfkit import ensure_pdf_font
    f = ensure_pdf_font()                 # 必须用返回值，别读模块变量（见 pdfkit 注释）
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="小记导出")
    st = ParagraphStyle("b", fontName=f, fontSize=10.5, leading=17)
    st_t = ParagraphStyle("t", fontName=f, fontSize=20, leading=26, alignment=1, spaceAfter=2)
    st_s = ParagraphStyle("s", fontName=f, fontSize=10, leading=14, alignment=1,
                          textColor=colors.grey, spaceAfter=12)
    st_m = ParagraphStyle("m", fontName=f, fontSize=9.5, leading=14,
                          textColor=colors.HexColor("#8a9099"), spaceAfter=3)
    st_h = ParagraphStyle("h", fontName=f, fontSize=13, leading=19, spaceBefore=5, spaceAfter=2)
    st_q = ParagraphStyle("q", fontName=f, fontSize=10.5, leading=17, leftIndent=10,
                          textColor=colors.HexColor("#666666"))
    st_c = ParagraphStyle("c", fontName="Courier", fontSize=9, leading=13, leftIndent=8,
                          backColor=colors.HexColor("#f2f3f5"))
    st_tag = ParagraphStyle("g", fontName=f, fontSize=9.5, leading=15,
                            textColor=colors.HexColor("#1a6fb5"))
    story = [Paragraph("小　记", st_t),
             Paragraph(datetime.now().strftime("导出于 %Y-%m-%d %H:%M") + "　共 %d 条" % len(items), st_s)]
    for n in items:
        h = _head_line(n, o)
        if h:
            story.append(Paragraph(_esc(h), st_m))
        bullets = []
        for kind, txt in _blocks(n["content"]):
            if kind in ("ul", "ol"):
                bullets.append((kind, txt))
                continue
            if bullets:
                story.append(_pdf_list(bullets, st, ListFlowable, ListItem, Paragraph))
                bullets = []
            if kind == "hr":
                story.append(HRFlowable(width="100%", thickness=0.4,
                                        color=colors.HexColor("#dddddd")))
            elif kind == "quote":
                story.append(Paragraph(_inline(txt), st_q))
            elif kind == "code":
                for ln in txt.split("\n"):
                    story.append(Paragraph(_esc(ln).replace(" ", "&nbsp;") or "&nbsp;", st_c))
            elif kind.startswith("h"):
                story.append(Paragraph("<b>%s</b>" % _inline(txt), st_h))
            else:
                story.append(Paragraph(_inline(txt), st))
        if bullets:
            story.append(_pdf_list(bullets, st, ListFlowable, ListItem, Paragraph))
        if o.get("todos", True) and n["todos"]:
            for t in n["todos"]:
                # 中文字体（uming/STSong）没有 ☑ ☐ 📎 这些字形，印出来是空白或黑块。
                # 屏幕上用什么符号是另一回事，进 PDF 一律换成字体真有的字。
                mark = "√" if t.get("done") else "□"
                story.append(Paragraph("%s %s" % (mark, _esc(t.get("text") or "")), st))
        if o.get("imgs", True):
            for i in range(len(n["img_files"])):
                img = _pdf_image(_img_path(n, i), Image, mm)
                if img:
                    story += [Spacer(1, 3), img, Spacer(1, 3)]
        for a in n["att_files"]:
            story.append(Paragraph("附件：%s" % _esc(a.get("name") or a.get("file")), st_m))
        if o.get("tags", True) and n["tags"]:
            story.append(Paragraph("　".join("# " + _esc(t) for t in n["tags"]), st_tag))
        story.append(Spacer(1, 5))
        story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#e6e8ec")))
        story.append(Spacer(1, 8))
    doc.build(story)
    buf.seek(0)
    return buf


def _pdf_list(bullets, st, ListFlowable, ListItem, Paragraph):
    kind = bullets[0][0]
    return ListFlowable([ListItem(Paragraph(_inline(t), st)) for _, t in bullets],
                        bulletType="1" if kind == "ol" else "bullet",
                        bulletFontName="Helvetica", leftIndent=16, bulletFontSize=8)


def _pdf_image(path, Image, mm):
    """PDF 里的图：一律先过 PIL 转 PNG —— reportlab 不认 webp/HEIC，
    而小记里的图来自手机相册，什么格式都有。"""
    if not os.path.exists(path):
        return None
    buf = _to_png(path, max_side=1200)
    if not buf:
        return None
    try:
        from PIL import Image as PILImage
        w, h = PILImage.open(buf).size
        buf.seek(0)
        maxw, maxh = 110 * mm, 90 * mm
        sc = min(maxw / w, maxh / h, 1.0)
        return Image(buf, width=w * sc, height=h * sc)
    except Exception:
        log.debug("PDF 嵌图失败：%s", path, exc_info=True)
        return None


def build_json(items, o):
    out = []
    for n in items:
        d = {"id": n["id"], "board": n["board"], "content": n["content"],
             "created_at": n["created_at"], "updated_at": n["updated_at"],
             "images": list(n["img_files"]),
             "attachments": [{"name": a.get("name"), "ext": a.get("ext", ""),
                              "size": a.get("size"), "file": a.get("file")}
                             for a in n["att_files"]]}
        if o.get("todos", True):
            d["todos"] = n["todos"]
        if o.get("tags", True):
            d["tags"] = n["tags"]
        out.append(d)
    return json.dumps({"exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "count": len(out), "notes": out},
                      ensure_ascii=False, indent=2)


def build_zip(items, o):
    """带附件原件的完整包：md + json + images/ + files/。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("小记.md", build_md(items, o, packed=True))
        z.writestr("notes.json", build_json(items, o))
        if o.get("imgs", True):
            for n in items:
                for i in range(len(n["img_files"])):
                    p = _img_path(n, i)
                    if os.path.exists(p):
                        z.write(p, _img_rel(n, i))
        if o.get("atts", True):
            for n in items:
                for i, a in enumerate(n["att_files"]):
                    p = _att_path(a)
                    if os.path.exists(p):
                        z.write(p, _att_rel(n, i))
    buf.seek(0)
    return buf


# ---------------- 路由 ----------------

def _args(req):
    """GET 和 POST 收同一份参数：桌面壳（WebKit）下不了 fetch 出来的 blob，
    走的是 location.href = /api/notes/export?…（积累本导出同款做法）。"""
    if req.method == "POST":
        d = req.get_json(force=True, silent=True) or {}
        ids = d.get("ids") or []
        return d, {k: d.get(k, True) for k in ("todos", "tags", "time", "imgs", "atts")}, ids
    a = req.args
    d = {"fmt": a.get("fmt", "md"), "board": a.get("board", ""), "tag": a.get("tag", ""),
         "q": a.get("q", ""), "order": a.get("order", "")}
    ids = [x for x in (a.get("ids") or "").split(",") if x.strip()]
    o = {k: _truthy(a.get(k)) for k in ("todos", "tags", "time", "imgs", "atts")}
    return d, o, ids


@bp.route("/api/notes/export", methods=["GET", "POST"])
def notes_export():
    d, o, ids = _args(request)
    fmt = (d.get("fmt") or "md").lower()
    if fmt not in FMTS:
        return jsonify({"error": "不支持的格式：%s" % fmt}), 400
    d = dict(d, ids=ids)
    items = _collect(d)
    if not items:
        return jsonify({"error": "没有可导出的内容"}), 400
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    name = "小记_%s" % stamp
    if fmt == "pdf":
        data, mime = build_pdf(items, o), "application/pdf"
    elif fmt == "zip":
        data, mime = build_zip(items, o), "application/zip"
    else:
        text = {"md": build_md, "txt": build_txt, "html": build_html,
                "json": build_json}[fmt](items, o)
        data = io.BytesIO(text.encode("utf-8"))
        mime = {"md": "text/markdown", "txt": "text/plain",
                "html": "text/html", "json": "application/json"}[fmt]
    return send_file(data, mimetype=mime, as_attachment=True,
                     download_name="%s.%s" % (name, fmt))
