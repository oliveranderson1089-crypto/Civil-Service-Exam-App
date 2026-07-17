"""AI 调用：云端大模型（OpenAI 兼容）+ 视觉模型。

全项目最常用的依赖——_ai_call_or_error 有 29 处调用方。它经 ai_chat 依赖 CFG，
所以 CFG 得先在 core.py 里，不然任何模块想用 AI 都要 import app，绕成环。

不含 ai_chat_agentic（AI 工具调用）：那个要拿 db 去操作各业务表，依赖朝业务侧，
留在 app.py 更合适。

_ai_call_or_error 原先躺在「小记」区段中间（L3201），位置本身就是错的：
它是通用封装，不属于任何一个业务。
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

from flask import jsonify

from core import CFG, log


def _ai_conf():
    return {
        "base": (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/"),
        "model": CFG.get("ai_model") or "deepseek-chat",
        "key": CFG.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", ""),
    }


def ai_configured():
    return bool(_ai_conf()["key"])


def ai_chat(messages, temperature=0.4, max_tokens=1600, timeout=120, json_mode=False):
    """调用 OpenAI 兼容的对话接口（默认 DeepSeek），返回回复文本。"""
    conf = _ai_conf()
    if not conf["key"]:
        raise RuntimeError("AI 未配置，请管理员在「后台 → AI 设置」填写 API Key")
    b = conf["base"]
    if b.endswith("/chat/completions"):
        url = b
    elif b.endswith("/v1"):
        url = b + "/chat/completions"
    else:
        url = b + "/v1/chat/completions"
    payload = {"model": conf["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + conf["key"],
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------- 视觉模型（智谱 GLM-4.6V，OpenAI 兼容）
# DeepSeek 没有视觉，图片相关（拍照识题、图形推理、图片附件）走这里。文字任务仍走 DeepSeek。
def _vision_conf():
    return {
        "base": (CFG.get("vision_base") or "").rstrip("/"),
        "key": CFG.get("vision_key") or "",
        "model": CFG.get("vision_model") or "glm-4.6v",       # 旗舰：图形推理这类硬任务
        "free": CFG.get("vision_model_free") or "",           # 免费 flash：读图/OCR 足够
    }


def vision_configured():
    c = _vision_conf()
    return bool(c["key"] and c["base"])


def _img_data_url(path, maxpx=1600):
    """读图 → 摆正/压到合理尺寸 → base64 data URL（省流量、够清晰）。"""
    from PIL import Image, ImageOps
    im = Image.open(path)
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        log.debug("EXIF 转向失败，按原图用", exc_info=True)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > maxpx:
        s = maxpx / float(max(w, h))
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def vision_chat(text, images, prefer="free", temperature=0.2, max_tokens=1500, timeout=90, json_mode=False):
    """智谱视觉对话。images 为文件路径或 data-url 列表。
    prefer='free' 先用免费 flash（省钱、读图够用），429/失败自动退到旗舰 glm-4.6v。"""
    conf = _vision_conf()
    if not conf["key"] or not conf["base"]:
        raise RuntimeError("视觉模型未配置")
    content = [{"type": "text", "text": text}]
    for im in images:
        u = im if isinstance(im, str) and im.startswith("data:") else _img_data_url(im)
        content.append({"type": "image_url", "image_url": {"url": u}})
    url = conf["base"] + ("" if conf["base"].endswith("/chat/completions") else "/chat/completions")
    order = ([conf["free"], conf["model"]] if prefer == "free" and conf["free"]
             else [conf["model"]] + ([conf["free"]] if conf["free"] and conf["free"] != conf["model"] else []))
    last = "未知错误"
    for model in [m for m in order if m]:
        for attempt in range(3):
            payload = {"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": temperature, "max_tokens": max_tokens, "stream": False}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + conf["key"]})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                return (d["choices"][0]["message"]["content"] or "").strip()
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                if e.code == 429 and attempt < 2:
                    time.sleep(2 + attempt * 2)
                    continue
                break     # 其它错误：换下一个模型再试
            except Exception as e:
                last = str(e)
                time.sleep(1)
                continue
    raise RuntimeError("视觉识别失败（%s）" % last)


VISION_OCR_PROMPT = (
    "请把这张图片里的文字**原样转写**出来：题干、选项(A/B/C/D)、数字、数学式、标点都要，按阅读顺序分行。"
    "若有图形/表格但没有文字，用【图形】【表格】占位标注。"
    "只输出图片中的文字内容，不要解释、不要作答、不要加任何前后缀。")


def vision_ocr(path):
    """用视觉模型把图片转写成文字（手写、排版、公式都比 tesseract 强）。"""
    return vision_chat(VISION_OCR_PROMPT, [path], prefer="free", temperature=0.1, max_tokens=1800)


def _ai_call_or_error(messages, **kw):
    """统一封装：调用 AI，出错时返回 (None, (json, code))。"""
    try:
        return ai_chat(messages, **kw), None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            log.debug("读 HTTP 错误详情失败", exc_info=True)
        msg = "AI 服务返回错误 %d" % e.code
        if e.code == 401:
            msg = "API Key 无效或未授权，请在后台重新填写"
        elif e.code == 402:
            msg = "账户余额不足，请到 DeepSeek 充值"
        elif e.code == 429:
            msg = "请求过于频繁，请稍后再试"
        return None, (jsonify({"error": msg, "detail": detail}), 502)
    except urllib.error.URLError as e:
        return None, (jsonify({"error": "连不上 AI 服务：" + str(e.reason)}), 502)
    except Exception as e:
        return None, (jsonify({"error": "AI 调用失败：" + str(e)}), 502)
