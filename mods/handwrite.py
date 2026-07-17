"""手写识别：申论作答的手写转文字。

本机直连 Google 不通、走本地代理可达；代理端口会变，做成可配 + 多端口兜底，记住能用的那个
"""
import json
import os
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from core import CONFIG, log

bp = Blueprint("handwrite", __name__)


_HW_ITC = "zh-t-i0-handwrit"
_hw_proxy_ok = None   # 上次跑通的代理，命中就先用它


def _hw_proxies():
    env = os.environ.get("GONGKAO_HW_PROXY", "").strip()
    cfg = ""
    try:
        cfg = (json.load(open(CONFIG, encoding="utf-8")).get("hw_proxy") or "").strip()
    except Exception:
        log.debug("读 config.json 的 hw_proxy 失败", exc_info=True)
    cand = [p for p in (_hw_proxy_ok, env, cfg) if p]
    cand += ["http://127.0.0.1:7897", "http://127.0.0.1:7890",
             "http://127.0.0.1:1080", "http://127.0.0.1:8080"]
    seen, out = set(), []
    for p in cand:
        if p and p not in seen:
            seen.add(p); out.append(p)
    return out


def _hw_recognize(ink, w, h):
    """把画布笔迹交给 Google 手写识别，返回候选字列表。经本地代理出网。"""
    global _hw_proxy_ok
    payload = {"options": "enable_pre_space", "requests": [{
        "writing_guide": {"writing_area_width": w, "writing_area_height": h},
        "ink": ink, "language": "zh"}]}
    data = json.dumps(payload).encode()
    saved = {k: os.environ.pop(k) for k in ("NO_PROXY", "no_proxy") if k in os.environ}
    try:
        for proxy in _hw_proxies():
            try:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                req = urllib.request.Request(
                    "https://inputtools.google.com/request?itc=%s&app=demopage" % _HW_ITC,
                    data=data, headers={"Content-Type": "application/json"})
                raw = opener.open(req, timeout=10).read().decode("utf-8", "ignore")
                arr = json.loads(raw)
                if arr and arr[0] == "SUCCESS":
                    _hw_proxy_ok = proxy
                    return arr[1][0][1] or []
            except Exception:
                continue
        return None
    finally:
        os.environ.update(saved)


@bp.post("/api/handwrite")
def handwrite():
    d = request.get_json(silent=True) or {}
    ink = d.get("ink") or []
    if not ink:
        return jsonify({"candidates": []})
    try:
        w = max(1, int(d.get("w") or 400))
        h = max(1, int(d.get("h") or 400))
    except Exception:
        w = h = 400
    cands = _hw_recognize(ink, w, h)
    if cands is None:
        return jsonify({"candidates": [], "error": "手写识别服务连不上，请稍后再试或直接键盘输入"}), 200
    return jsonify({"candidates": cands[:12]})
