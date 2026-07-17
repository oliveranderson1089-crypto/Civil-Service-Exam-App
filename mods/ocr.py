"""OCR 识图：先试视觉模型，回退 tesseract。


"""
import os
import re
import subprocess
import tempfile
import uuid

from flask import Blueprint, jsonify, request

from core import log
from mods.ai import vision_configured, vision_ocr

bp = Blueprint("ocr", __name__)


@bp.post("/api/ocr")
def api_ocr():
    f = request.files.get("file") or request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "没有图片"}), 400
    ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
    tmp = os.path.join(tempfile.gettempdir(), "ocr_" + uuid.uuid4().hex + ext)
    f.save(tmp)
    # 优先用视觉模型识别（手写 / 排版 / 公式都比 tesseract 强），失败再退 tesseract
    if vision_configured():
        try:
            vt = vision_ocr(tmp)
            if vt.strip():
                try:
                    os.remove(tmp)
                except Exception:
                    log.debug("临时文件没删掉", exc_info=True)
                return jsonify({"text": vt.strip(), "engine": "vision"})
        except Exception:
            log.warning("vision OCR 失败，回退到本地 OCR", exc_info=True)
    # 预处理：摆正方向 / 灰度 / 放大 / 拉对比度 / 锐化 —— 显著提升拍照识别率
    proc = tmp
    try:
        from PIL import Image, ImageOps, ImageFilter
        im = Image.open(tmp)
        im = ImageOps.exif_transpose(im)
        im = im.convert("L")
        w, h = im.size
        if max(w, h) < 2200:
            s = min(3.0, 2200.0 / max(w, h))
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=2)
        im = im.filter(ImageFilter.SHARPEN)
        proc = tmp + ".png"
        im.save(proc)
    except Exception:
        proc = tmp
    text = ""
    try:
        out = subprocess.run(["tesseract", proc, "stdout", "-l", "chi_sim+eng",
                              "--oem", "1", "--psm", "6"],
                             capture_output=True, timeout=120)
        text = out.stdout.decode("utf-8", "ignore")
    except Exception as e:
        for p in {tmp, proc}:
            try:
                os.remove(p)
            except Exception:
                log.debug("临时文件没删掉", exc_info=True)
        return jsonify({"error": "识别失败：" + str(e)}), 500
    for p in {tmp, proc}:
        try:
            os.remove(p)
        except Exception:
            log.debug("临时文件没删掉", exc_info=True)
    # tesseract 中文常在汉字间插空格，去掉相邻汉字间的空白
    text = re.sub(r"(?<=[一-鿿，。！？；：、（）《》“”])[ \t]+(?=[一-鿿，。！？；：、（）《》“”])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return jsonify({"text": text})
