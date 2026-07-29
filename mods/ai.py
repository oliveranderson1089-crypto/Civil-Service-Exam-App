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
import time
import urllib.error
import urllib.request

import aiclient
import aimeter
from core import CFG, log


def _ai_conf():
    """模型名的解析规则在 aiclient 里（别名/下线名纠正），这儿只负责把内存 CFG 递过去。

    必须传 CFG 而不是让 aiclient 自己读盘：后台改完 AI 设置是先改内存 CFG 再存盘，
    并发下盘上的可能还是旧值。
    """
    fast = aiclient.conf("fast", CFG)
    return {"base": fast["base"], "model": fast["model"],
            "pro": aiclient.conf("pro", CFG)["model"], "key": fast["key"]}


def ai_configured():
    return aiclient.configured(CFG)


def ai_chat(messages, temperature=0.4, max_tokens=1600, timeout=120, json_mode=False, tier="fast"):
    """调用 OpenAI 兼容的对话接口（默认 DeepSeek），返回回复文本。

    tier="fast" 用常规模型（flash，提取/解读/查询够用）；
    tier="pro" 用旗舰模型（创作/批改/命题这类质量敏感任务）。
    档位→真实模型名的映射、以及官方改名时的自动纠正，都在 aiclient.py。

    max_tokens 按**正文**估就行（"这个回答最多写多少字"）：现在两个档都是推理模型，
    推理段要烧的额度由 aiclient.budget() 另加、不够还会自己加额度重试，
    调用方不用也不该在这儿替推理段留余量。"""
    return aiclient.chat(messages, tier=tier, temperature=temperature,
                         max_tokens=max_tokens, timeout=timeout,
                         json_mode=json_mode, cfg=CFG)


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
            # 视觉走的是智谱、不经 aiclient，但一样烧钱（图片 token 还特别贵），
            # 所以记账要自己挂在这儿——否则后台的用量报表少掉一整类调用。
            # mode="vision" 把它和文本调用分开；caller 由 aimeter 顺栈找，
            # 会落到真正的业务模块（drill / docqa / attach），不是这个转发层。
            t = aimeter.Timer()
            d = None
            try:
                with t, urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                out = (d["choices"][0]["message"]["content"] or "").strip()
            except urllib.error.HTTPError as e:
                aimeter.record(tier="vision", model=model, mode="vision",
                               elapsed_ms=t.ms, ok=False, err=e)
                last = "HTTP %d" % e.code
                if e.code == 429 and attempt < 2:
                    time.sleep(2 + attempt * 2)
                    continue
                break     # 其它错误：换下一个模型再试
            except Exception as e:
                # 取 content 那步也在上面的 try 里（响应缺字段会 KeyError），所以
                # 成功那行必须等它走完才记 —— 先记再解析的话，同一个请求会留下
                # 「一行成功 + 一行失败」，调用数翻倍、失败率减半。
                aimeter.record(tier="vision", model=model, mode="vision",
                               usage=(d or {}).get("usage"), elapsed_ms=t.ms,
                               ok=False, err=e)
                last = str(e)
                time.sleep(1)
                continue
            aimeter.record(tier="vision", model=model, mode="vision",
                           usage=d.get("usage"), elapsed_ms=t.ms, ok=True)
            return out
    raise RuntimeError("视觉识别失败（%s）" % last)


VISION_OCR_PROMPT = (
    "请把这张图片里的文字**原样转写**出来：题干、选项(A/B/C/D)、数字、数学式、标点都要，按阅读顺序分行。"
    "若有图形/表格但没有文字，用【图形】【表格】占位标注。"
    "只输出图片中的文字内容，不要解释、不要作答、不要加任何前后缀。")


def vision_ocr(path):
    """用视觉模型把图片转写成文字（手写、排版、公式都比 tesseract 强）。"""
    return vision_chat(VISION_OCR_PROMPT, [path], prefer="free", temperature=0.1, max_tokens=1800)


def _ai_call_or_error(messages, **kw):
    """统一封装：调用 AI，出错时返回 (None, (dict, code))。

    错误分支别用 jsonify：dailytest 等处在线程池里调它，线程内没有 Flask
    application context，jsonify 会直接抛 "Working outside of application context"，
    把上游错误变成 500 崩溃。普通 dict 元组由视图 return 时自动序列化，线程里也只是数据。
    """
    try:
        return ai_chat(messages, **kw), None
    except urllib.error.HTTPError as e:
        # detail 由 aiclient 读好挂在 gk_detail 上：HTTPError 的 body 只能读一次，
        # 它已经读过（要判断是不是模型名失效），这儿再 read() 只会拿到空串。
        return None, ({"error": aiclient.error_message(e),
                       "detail": getattr(e, "gk_detail", "")[:300]}, 502)
    except Exception as e:
        return None, ({"error": aiclient.error_message(e)}, 502)
