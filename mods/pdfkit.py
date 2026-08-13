"""PDF 字体：中文字体注册（导出 PDF 用）。

单独成文件而不是塞进 core：core 是无第三方依赖的地基，这里要 reportlab。
古诗文速查、积累本导出、申论卷导出都要它。
"""
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

from core import log


EMBED_FONT_CANDIDATES = [
    ("CN", "/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    ("CN", "/usr/share/fonts/truetype/arphic/ukai.ttc", 0),
]
# 名字带下划线是**故意的**：这个值在 ensure_pdf_font() 里才被改写成真正注册上的
# 字体名。谁要是 `from mods.pdfkit import PDF_FONT`，拿到的永远是这行的初始值
# ——一个从没注册过的名字（uming.ttc 存在时走的是 TTFont 分支，CID 那句压根不执行），
# reportlab 到 doc.build() 才炸 ValueError，且只在点导出的那一刻炸。
# 曾经 pdfexport / classics_lookup 就是这么坏了两个导出接口的。
# 唯一正确的用法：f = ensure_pdf_font()，用返回值。
_PDF_FONT = "STSong-Light"
_font_ready = False


def ensure_pdf_font():
    """注册中文字体，返回**实际可用**的字体名。必须用返回值，别读模块变量。"""
    global _PDF_FONT, _font_ready
    if _font_ready:
        return _PDF_FONT
    for name, path, idx in EMBED_FONT_CANDIDATES:
        try:
            if not os.path.exists(path):
                continue
            f = TTFont(name, path) if idx is None else TTFont(name, path, subfontIndex=idx)
            pdfmetrics.registerFont(f)
            _PDF_FONT = name
            _font_ready = True
            return _PDF_FONT
        except Exception:
            continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        log.error("中文字体全部注册失败：导出的 PDF 会是乱码方框")
    _PDF_FONT = "STSong-Light"
    _font_ready = True
    return _PDF_FONT
