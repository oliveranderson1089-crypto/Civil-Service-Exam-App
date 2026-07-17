"""本地手写识别：Zinnia，离线瞬时。

电脑端不出网、毫秒级；准度不如 Google/ML Kit，作为"快"的选项，拿不准可切云端兜准。
"""
import os
import threading

from flask import Blueprint, jsonify, request

bp = Blueprint("zinnia", __name__)


_ZINNIA = None
_zinnia_lock = threading.Lock()
_ZINNIA_MODEL = os.environ.get("GONGKAO_ZINNIA_MODEL",
                               "/usr/share/tegaki/models/zinnia/handwriting-zh_CN.model")


def _zinnia():
    """懒加载 Zinnia 识别器（ctypes 直调 libzinnia）。装不上就返回 None，前端自动退云端。"""
    global _ZINNIA
    if _ZINNIA is not None:
        return _ZINNIA or None
    try:
        import ctypes
        z = ctypes.CDLL("libzinnia.so.0")
        z.zinnia_recognizer_new.restype = ctypes.c_void_p
        z.zinnia_recognizer_open.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        z.zinnia_recognizer_open.restype = ctypes.c_int
        z.zinnia_character_new.restype = ctypes.c_void_p
        z.zinnia_character_clear.argtypes = [ctypes.c_void_p]
        z.zinnia_character_set_width.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_character_set_height.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_character_add.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int]
        z.zinnia_recognizer_classify.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_recognizer_classify.restype = ctypes.c_void_p
        z.zinnia_result_size.argtypes = [ctypes.c_void_p]
        z.zinnia_result_size.restype = ctypes.c_size_t
        z.zinnia_result_value.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.zinnia_result_value.restype = ctypes.c_char_p
        z.zinnia_result_destroy.argtypes = [ctypes.c_void_p]
        z.zinnia_character_destroy.argtypes = [ctypes.c_void_p]
        rec = z.zinnia_recognizer_new()
        if not rec or not z.zinnia_recognizer_open(rec, _ZINNIA_MODEL.encode()):
            _ZINNIA = False
            return None
        _ZINNIA = (z, rec)
        return _ZINNIA
    except Exception:
        _ZINNIA = False
        return None


def _zinnia_norm(ink, side=256, pad_ratio=0.12):
    """按字的外接框把笔迹居中归一化到一个正方形里——不管写在画布哪、多大，
    喂给 Zinnia 的都是"框好、居中、统一大小"的字，识别率比拿画布尺寸归一化高很多。"""
    xs_all, ys_all = [], []
    for st in ink:
        xs_all += list(st[0]) if len(st) > 0 else []
        ys_all += list(st[1]) if len(st) > 1 else []
    if not xs_all:
        return [], side
    minx, maxx = min(xs_all), max(xs_all)
    miny, maxy = min(ys_all), max(ys_all)
    bw, bh = max(1.0, maxx - minx), max(1.0, maxy - miny)
    span = max(bw, bh)
    pad = span * pad_ratio
    scale = side / (span + 2 * pad)
    ox = pad + (span - bw) / 2.0        # 居中：短边两侧补空
    oy = pad + (span - bh) / 2.0
    out = []
    for st in ink:
        xs = st[0] if len(st) > 0 else []
        ys = st[1] if len(st) > 1 else []
        pts = []
        for i in range(min(len(xs), len(ys))):
            nx = int((xs[i] - minx + ox) * scale)
            ny = int((ys[i] - miny + oy) * scale)
            pts.append((nx, ny))
        out.append(pts)
    return out, side


def _zinnia_recognize(ink, w, h, n=12):
    zz = _zinnia()
    if not zz:
        return None
    z, rec = zz
    strokes, side = _zinnia_norm(ink)      # 外接框居中归一化，跟画布大小无关
    with _zinnia_lock:      # zinnia 识别器非线程安全，串行化
        ch = z.zinnia_character_new()
        z.zinnia_character_clear(ch)
        z.zinnia_character_set_width(ch, side)
        z.zinnia_character_set_height(ch, side)
        for si, pts in enumerate(strokes):
            for (x, y) in pts:
                z.zinnia_character_add(ch, si, x, y)
        res = z.zinnia_recognizer_classify(rec, ch, n)
        out = []
        if res:
            for i in range(z.zinnia_result_size(res)):
                v = z.zinnia_result_value(res, i)
                if v:
                    out.append(v.decode("utf-8", "ignore"))
            z.zinnia_result_destroy(res)
        z.zinnia_character_destroy(ch)
        return out


@bp.post("/api/handwrite/local")
def handwrite_local():
    d = request.get_json(silent=True) or {}
    ink = d.get("ink") or []
    if not ink:
        return jsonify({"candidates": []})
    try:
        w = max(1, int(d.get("w") or 300))
        h = max(1, int(d.get("h") or 300))
    except Exception:
        w = h = 300
    cands = _zinnia_recognize(ink, w, h)
    if cands is None:
        return jsonify({"candidates": [], "error": "本地手写引擎未就绪"}), 200
    return jsonify({"candidates": cands[:12], "engine": "zinnia"})
