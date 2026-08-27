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
import re
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
    # who="" 是关掉「服务级档位覆盖」：这函数是给后台/前端**展示**用的（两个档位
    # 各配了哪个模型），要的是配置原样。不关的话它会按调用栈把自己也当成一个服务，
    # 显示的模型会跟着谁在问而变。
    fast = aiclient.conf("fast", CFG, who="")
    return {"base": fast["base"], "model": fast["model"],
            "pro": aiclient.conf("pro", CFG, who="")["model"], "key": fast["key"]}


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
# 「精准」档的兜底模型名住在 aiclient（真实模型名的唯一住处，见那边的 Test全局约束）。
# 这里只取一个别名，方便本模块和测试引用 —— 名字本身仍然只有那一份。
VISION_EXACT_MODEL = aiclient.VISION_EXACT_MODEL


def _vision_conf():
    """三个视觉档各自的**完整落点**（不只是模型名）。

    free / pro —— 智谱（vision_* 那几个键）。
    exact      —— DeepSeek 的视觉模型。它不是「更贵的智谱」，是**另一家**：base 和 key
                  都不一样，所以三档得各带各的落点，只换模型名会打到错的门上。

    为什么值得多接一家（2026-08-27 拿那份《社区知识三色笔记》实测，14 页里挑
    文字层最烂的三页当标尺 —— 那份 PDF 自己把「费孝通」存成了「翌生通」，
    每一处坏字都是一道有唯一答案的题）：
        纯文字转写   智谱旗舰 46/47，DeepSeek 46~47/47   —— 打平
        速度         智谱 ~48 秒/页，DeepSeek ~12 秒/页  —— 快 4 倍
        token        智谱 ~4200/页，DeepSeek ~1800/页    —— 省一半多
        颜色标注     智谱旗舰 17/18，DeepSeek 不稳定     —— 智谱明显更好
    所以是**多一个选项**，不是换掉智谱：要「快而准的整页转写」用 exact，
    要认三色笔记里哪句是红字（红字＝必背考点）还得靠智谱旗舰。
    另外免费那档 glm-4.6v-flash 实测持续 429（该模型当前访问量过大），
    exact 顺带也是这条路堵死时的另一条腿。
    """
    zbase = (CFG.get("vision_base") or "").rstrip("/")
    zkey = CFG.get("vision_key") or ""
    return {
        "base": zbase, "key": zkey,                           # ← 旧字段留着：老调用方还在读
        "model": CFG.get("vision_model") or "glm-4.6v",       # 旗舰：图形推理这类硬任务
        "free": CFG.get("vision_model_free") or "",           # 免费 flash：读图/OCR 足够
        "lanes": {
            "free":  {"base": zbase, "key": zkey,
                      "model": CFG.get("vision_model_free") or "", "who": "智谱-flash"},
            "pro":   {"base": zbase, "key": zkey,
                      "model": CFG.get("vision_model") or "glm-4.6v", "who": "智谱-旗舰"},
            # 默认借 DeepSeek 那套文本的 base/key（同一个账号、同一把 key）。
            # vision_exact_* 三个键照样留着：哪天它挪到别的端点，改配置就行，不用动代码。
            "exact": {"base": (CFG.get("vision_exact_base") or CFG.get("ai_base") or "").rstrip("/"),
                      "key": CFG.get("vision_exact_key") or CFG.get("ai_key") or "",
                      "model": CFG.get("vision_exact_model") or VISION_EXACT_MODEL,
                      "who": "DeepSeek-视觉"},
        },
    }


def _vision_url(base):
    """两家的 base 形状不一样：智谱填到 `/paas/v4`，DeepSeek 只填到域名。
    前者补 `/chat/completions` 就对，后者还差一段 `/v1` —— 一刀切必然打到 404。"""
    b = (base or "").rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return b + ("/chat/completions" if re.search(r"/v\d+$", b) else "/v1/chat/completions")


def vision_configured():
    c = _vision_conf()
    return bool(c["key"] and c["base"])


def vision_exact_configured():
    """「精准」档能不能用。前端据此决定要不要把那个开关摆出来 ——
    摆出来却点了没反应，比没有这个开关更糟。"""
    e = _vision_conf()["lanes"]["exact"]
    return bool(e["key"] and e["base"] and e["model"])


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
    """视觉对话。images 为文件路径或 data-url 列表。

    三档（见 _vision_conf 里那张实测对照表）：
        free  —— 智谱免费 flash，读图/OCR 够用；失败自动退到旗舰
        pro   —— 智谱旗舰 glm-4.6v，图形推理、认三色笔记的颜色靠它
        exact —— DeepSeek 视觉，整页转写又快又准（token 还省一半），认颜色不行

    每一档都自带 base/key，**不是只换模型名**：exact 是另一家服务商。
    退路都往「还能出结果」的方向走 —— 宁可慢一点，也别让这一次识别整个失败。

    prefer 是**业务的建议**，管理员在「后台 → 档位控制」里能按服务改掉它——
    和 DeepSeek 那两档同一个旋钮体系（键的形状、优先级、清除方式都一样）。
    who 顺调用栈找，落到真正的业务模块（drill / docqa / attach），不是这个转发层。
    """
    prefer = aiclient.effective_vision(prefer, CFG, aimeter.caller())
    conf = _vision_conf()
    lanes = conf["lanes"]
    if prefer == "exact" and lanes["exact"]["key"] and lanes["exact"]["model"]:
        # 精准档：DeepSeek 打头，它不在时照样退回智谱两档
        order = [lanes["exact"], lanes["pro"], lanes["free"]]
    elif prefer == "free" and lanes["free"]["model"]:
        order = [lanes["free"], lanes["pro"]]
    else:
        order = [lanes["pro"], lanes["free"]]
    order = [l for l in order if l["model"] and l["key"] and l["base"]]
    if not order:
        raise RuntimeError("视觉模型未配置")
    content = [{"type": "text", "text": text}]
    for im in images:
        u = im if isinstance(im, str) and im.startswith("data:") else _img_data_url(im)
        content.append({"type": "image_url", "image_url": {"url": u}})
    last = "未知错误"
    for lane in order:
        model, url = lane["model"], _vision_url(lane["base"])
        # 推理模型（DeepSeek 视觉就是）要先烧一段 reasoning_content，业务给的
        # max_tokens 只够正文。不加这一份额度，实测会出现「跑了几十秒、正文一个字没有」。
        # 换算规则跟文本那边共用 aiclient.budget，不在这儿另抄一份。
        cap = aiclient.budget(model, max_tokens)
        for attempt in range(3):
            payload = {"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": temperature, "max_tokens": cap, "stream": False}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + lane["key"]})
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
                if not out:
                    # 空正文**不是成功**。推理模型偶尔会把额度全烧在 reasoning_content 上，
                    # 正文一个字不出（实测 DeepSeek 视觉出现过）。当成功返回的话，
                    # 上游拿到的是一份「识别完了，内容为空」—— 比报错还难查。
                    raise ValueError("模型没有返回正文（可能推理段吃光了额度）")
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


# 整页 A4 的中文讲义，转写出来一千五到两千字是常态，折成 token 还要更多。
# 原来这里是 1800 —— 实测拿《社区知识三色笔记》第 13 页跑，智谱那一路在第 26 条上
# 硬生生截断（只出了 1061 字，后半页全没），而**截断是无声的**：上游拿到的是一段
# 看起来正常、其实少了一半的文字。max_tokens 是上限不是花销（模型写完就停），
# 给宽了不多花一分钱，给窄了赔上的是整页后半段。
VISION_OCR_TOKENS = 4000


def vision_ocr(path, prefer="free"):
    """用视觉模型把图片转写成文字（手写、排版、公式都比 tesseract 强）。

    prefer='exact' 换 DeepSeek 视觉那一档：整页转写更快更准（见 _vision_conf 的实测表）。
    """
    return vision_chat(VISION_OCR_PROMPT, [path], prefer=prefer, temperature=0.1,
                       max_tokens=VISION_OCR_TOKENS)


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
