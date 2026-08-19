"""文件处理设施：上传目录、格式转换、OCR、文本抽取。

不是某个业务的，是大家的：_remove_file 被 8 处用、_user_dir 7 处、
_ocr_image 5 处、_extract_text 4 处、_office_to_pdf 3 处，横跨资料库 /
知识库 / 小记 / 文档识题 / 申论卷。它们原先散在「资料库」区段和文本处理那一带，
资料库因此既是业务又是设施——谁想用 OCR 就得从资料库里掏。

抽出来之后资料库才只剩它自己的路由，小题训练也才拆得动。
"""
import os
import re
import shutil
import subprocess
import tempfile

from core import UPLOADS, log


# 文件查看
INLINE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
              ".bmp", ".txt", ".md", ".html", ".htm", ".csv", ".json"}
OFFICE_EXT = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
              ".odt", ".ods", ".odp", ".rtf"}
TEXT_EXT = {".txt", ".md", ".csv", ".json"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
             ".heic", ".heif", ".tif", ".tiff", ".avif"}


_JUNK_KW = re.compile(r"申公宝|优路教育|仅供学习|智能批改|都说得清来源|版权所有|www\.|扫码|关注公众号")
_JUNK_PAGE = re.compile(r"^第\s*\d+\s*页(?:\s*[·・.]?\s*共\s*\d+\s*页)?$")
_JUNK_GRID = re.compile(r"^(?:\d{1,2}00[ \t]*)+$")        # 答题卡行号：100 200 300 …


def _user_dir(user_id):
    d = os.path.join(UPLOADS, str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


# 上传件旁边会派生出来的缓存（都拿原文件名去掉后缀当前缀）。
# 新加一种派生缓存时**记得加进来** —— 漏了它就永远没人清：没有记录引用它、不计进配额、
# 用户也看不见。.pdf 是 Office 预览转的，.thumb.jpg 是云盘网格视图的缩略图。
_DERIVED = (".pdf", ".thumb.jpg")


def _remove_blob(path):
    """删一个上传件，**连它派生出来的缓存一起删**。

    资料库/小记/知识库走 _remove_file（按 uid 拼路径），云盘的文件在 uploads/drive/<uid>/
    下、拼法不同，所以公共部分收在这里，两边都调它。
    """
    try:
        if os.path.exists(path):
            os.remove(path)
        base = os.path.splitext(path)[0]
        for suf in _DERIVED:
            p = base + suf
            if p != path and os.path.exists(p):
                os.remove(p)
    except Exception:
        log.debug("删文件失败（残留不影响功能）", exc_info=True)


def _remove_file(user_id, stored_name):
    _remove_blob(os.path.join(UPLOADS, str(user_id), stored_name))


def _office_to_pdf(src):
    pdf = os.path.splitext(src)[0] + ".pdf"
    if os.path.exists(pdf) and os.path.getmtime(pdf) >= os.path.getmtime(src):
        return pdf
    prof = "file://" + os.path.join(tempfile.gettempdir(), "lo_profile")
    try:
        subprocess.run(
            ["soffice", "--headless", "-env:UserInstallation=" + prof,
             "--convert-to", "pdf", "--outdir", os.path.dirname(src), src],
            timeout=120, check=True, capture_output=True)
    except Exception:
        return None
    return pdf if os.path.exists(pdf) else None


def _extract_pdf_text(pdf_path):
    """用 pdftotext 提取 PDF 文字（-layout 尽量保留版式），供阅读模式用。"""
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", pdf_path, "-"],
                             capture_output=True, timeout=90)
        return out.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def _clean_ocr(text):
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tess(img_path, psm):
    try:
        out = subprocess.run(["tesseract", img_path, "stdout", "-l", "chi_sim+eng",
                              "--oem", "1", "--psm", str(psm)], capture_output=True, timeout=150)
        return _clean_ocr(out.stdout.decode("utf-8", "ignore"))
    except Exception:
        return ""


def _ocr_image(path):
    """预处理+tesseract OCR。兼容 HEIC/RGBA/超大图；单一版面识别不到时换 psm 重试。"""
    proc = None
    try:
        from PIL import Image, ImageOps, ImageFilter
        try:                                   # iPhone HEIC / HEIF
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            log.debug("pillow_heif 没装，HEIC/HEIF 图片会打不开", exc_info=True)
        im = Image.open(path)
        im.load()                              # 多帧 GIF/TIFF 只取第一帧
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):     # 透明底 → 铺白，否则变全黑
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("L")
        w, h = im.size
        if max(w, h) < 2200:                   # 太小 → 放大，提升小字识别率
            sc = min(3.0, 2200.0 / max(w, h))
            im = im.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        elif max(w, h) > 5000:                 # 太大 → 缩小，避免 tesseract 超时
            sc = 5000.0 / max(w, h)
            im = im.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=2).filter(ImageFilter.SHARPEN)
        proc = path + ".ocr.png"
        im.save(proc)
    except Exception:
        proc = None
    src = proc or path
    try:
        text = _tess(src, 6)                   # 统一版面（题目/文档截图）
        if len(text) < 8:
            text = _tess(src, 3) or text       # 自动分栏
        if len(text) < 8:
            text = _tess(src, 11) or text      # 稀疏文字（照片/海报）
        return text
    finally:
        if proc:
            try:
                os.remove(proc)
            except Exception:
                log.debug("临时文件没删掉", exc_info=True)


def _ocr_image_page(pdf, p, tmpdir):
    """没有文字层的页（扫描件）走 OCR。"""
    try:
        pre = os.path.join(tmpdir, "sc_%d" % p)
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(p), "-l", str(p),
                        "-singlefile", pdf, pre], check=True, timeout=180, capture_output=True)
        return _ocr_image(pre + ".png")
    except Exception:
        return ""


def _extract_text(path, ext):
    """把文件转成纯文本：pdf 直接提取；Office 先转 pdf 再提取；文本类直接读。"""
    if not os.path.exists(path):
        return None
    if ext == ".pdf":
        return _extract_pdf_text(path)
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        return _extract_pdf_text(pdf) if pdf else ""
    if ext in TEXT_EXT or ext in (".html", ".htm"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""
    return ""


def pdf_pages(path):
    """PDF 有多少页；问不出来就返回 0。

    用来向用户和模型交代「这份文件一共多少页、你只看到了前几页」——
    没有这个数，截断就是无声的（见 attach.py 那段注释）。"""
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, timeout=20)
        for line in out.stdout.decode("utf-8", "ignore").splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        log.debug("pdfinfo 取页数失败", exc_info=True)
    return 0


def _pdf_text_or_ocr(path, ext, max_pages=30):
    """先按文本抽取；扫描件抽不出字就逐页 OCR。

    max_pages 是 OCR 的页数上限（文本层抽取不受它限制——那个不花时间）。
    调用方各有各的口径：资料库这类离线场景给得起 30 页，AI 附件是用户盯着等的，
    只给 20 页（300dpi 一页要跑几秒）。
    """
    txt = (_extract_text(path, ext) or "").strip()
    if len(txt) >= 200 or ext != ".pdf":
        return txt
    tmp = tempfile.mkdtemp(prefix="slocr_")
    try:
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", "-l", str(int(max_pages)), path,
                        os.path.join(tmp, "p")], check=True, timeout=900, capture_output=True)
        out = []
        for f in sorted(x for x in os.listdir(tmp) if x.endswith(".png")):
            out.append(_ocr_image(os.path.join(tmp, f)))
        return "\n".join(out).strip()
    except Exception:
        return txt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 「给定资料」「作答要求」在注意事项里也会被提一嘴，所以优先认独占一行的大标题
_SL_TITLE_MAT = re.compile(r"^[ \t]*(?:[二2][、.．]\s*)?给\s*定\s*资\s*料[ \t]*$", re.M)
_SL_TITLE_REQ = re.compile(r"^[ \t]*(?:[三3][、.．]\s*)?作\s*答\s*(?:要\s*求|任\s*务)[ \t]*$", re.M)
_SL_HEAD_MAT = re.compile(r"给\s*定\s*资\s*料")
_SL_HEAD_REQ = re.compile(r"作\s*答\s*要\s*求|作\s*答\s*任\s*务")
_SL_MAT_1 = re.compile(r"^[ \t]*(?:给定)?材\s*料\s*[一1][ \t]*$|^[ \t]*(?:给定)?材\s*料\s*[一1][：:，,]", re.M)
# 题号形式：第一题 / 1. / （2） / 三、  —— 只在「作答要求」之后的文本里找，不会误伤材料
_SL_Q_HEAD = re.compile(
    r"^[ \t]*(?:第\s*([一二三四五六七八九十\d]+)\s*题[.、．:：]?"
    r"|[（(]?\s*(\d{1,2})\s*[.、．)）]"
    r"|([一二三四五六七八九十]{1,3})\s*[、.．])\s*", re.M)
_SL_SCORE = re.compile(r"[（(]\s*(\d{1,2})\s*分\s*[）)]")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _strip_artifacts(text):
    """去掉页眉页脚 / 水印 / 答题卡行号，保留正文与空行结构。"""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s and (_JUNK_KW.search(s) or _JUNK_PAGE.fullmatch(s) or _JUNK_GRID.fullmatch(s)):
            continue
        out.append(ln)
    return "\n".join(out)


def _reflow(text):
    """把 PDF 版式的硬换行拼回自然段：段内换行去掉（中文可任意断行），空行分段。
    这样前端渲染时每一排都排满了再换行，不会中途留半截。"""
    text = (text or "").strip()
    # 「材料N / 资料N」序号标题单独成段，别和正文粘在一起
    text = re.sub(r"[ \t]*\n?[ \t]*((?:给定)?(?:材|资)料\s*[一二三四五六七八九十\d]{1,3})[.、：:]?[ \t]*",
                  r"\n\n\1\n\n", text)
    paras = re.split(r"\n[ \t]*\n+", text)
    out = []
    for p in paras:
        p = re.sub(r"[ \t]*\n[ \t]*", "", p.strip())
        if p:
            out.append(p)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()


def _cacheable(resp, days=30):
    """文件内容不可变（stored_name 是 uuid），让浏览器长期本地缓存。
    用 private：不进 CDN 边缘，避免带登录态的资料被别人按 URL 命中。"""
    resp.headers["Cache-Control"] = "private, max-age=%d" % (days * 86400)
    resp.headers.pop("Expires", None)
    return resp


def _no_script(resp):
    """内联返回用户上传的文件时，挡住里面可能夹带的脚本。

    资料库 / 小记 / 知识库 / 错题图 / 云盘 / 聊天文件都收**任意格式**，其中 .html
    和 .svg 是能带 <script> 的。`as_attachment=False` 意味着浏览器会**当页面打开**
    它 —— 那段脚本就跑在本站源上，读得到登录 cookie、调得动任何接口。聊天文件尤其
    要紧：那是**别人**发过来的东西。

    CSP `sandbox`（不给 allow-scripts）把这类响应关进独立源的沙箱，脚本执行不了、
    也拿不到本站的 cookie 和 storage；`nosniff` 再拦住浏览器把内容猜成 HTML 再执行。
    图片 / PDF / 音视频在沙箱里照常渲染，pdf.js 是用 XHR 取字节的、更不受影响，
    所以预览功能一个都不受损。
    """
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp
