"""语音识别（ASR）：把一段录音转成文字。

**默认不接引擎**——录音、发语音条、播放这些都不依赖它，装好就能用；
只有「把语音转成文字」这一步需要识别引擎，由管理员在后台自己选：

    ""       关闭（默认）。前端照常能发语音条，只是转文字按钮会说「管理员没开」
    zhipu    走 OpenAI 兼容的 /audio/transcriptions（预设智谱 GLM-ASR，
             复用后台已经填过的视觉 Key；改 base/model 就能指向别家兼容接口）
    whisper  本地 whisper.cpp，完全离线、不花钱，但吃 CPU、慢

加引擎只要写一个 `_run_xxx(path) -> str` 再挂进 _ENGINES，别处不用动。

音频统一由 ffmpeg 转码后再送出去：浏览器录出来的是 webm/opus（Safari 是 mp4），
云端接口和 whisper.cpp 认的格式各不相同，在这儿收口一次，前端就不必操心。
"""
import os
import shutil
import subprocess
import tempfile
import uuid

from flask import Blueprint, jsonify, request

from core import CFG, _save_cfg, log

bp = Blueprint("asr", __name__)

# 一段语音最长多久。超过就别转了——录这么久多半是忘了停，转出来也没人看，
# 而云端是按时长计费的。
MAX_SECONDS = 300
MAX_BYTES = 25 * 1024 * 1024

ZHIPU_BASE = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL = "glm-asr"


def asr_conf():
    return {
        "engine": (CFG.get("asr_engine") or "").strip(),
        "base": (CFG.get("asr_base") or ZHIPU_BASE).rstrip("/"),
        # Key 留空就借用视觉那份：两边都是智谱，绝大多数情况下就是同一个 Key，
        # 让管理员少填一次，也少一处会忘记同步的地方。
        "key": (CFG.get("asr_key") or CFG.get("vision_key") or "").strip(),
        "model": (CFG.get("asr_model") or ZHIPU_MODEL).strip(),
        "bin": (CFG.get("asr_whisper_bin") or "whisper-cli").strip(),
        "wmodel": (CFG.get("asr_whisper_model") or "").strip(),
    }


def asr_configured():
    """引擎选了、而且该填的都填了，才算真能转。"""
    c = asr_conf()
    if c["engine"] == "zhipu":
        return bool(c["key"] and c["base"] and c["model"])
    if c["engine"] == "whisper":
        return bool(shutil.which(c["bin"]) and c["wmodel"] and os.path.exists(c["wmodel"]))
    return False


def has_ffmpeg():
    return bool(shutil.which("ffmpeg"))


def audio_duration(path):
    """秒。取不到就返回 0——时长只是显示用，缺了不该让发送失败。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return round(float(out), 1)
    except Exception:
        log.debug("ffprobe 读时长失败：%s", path, exc_info=True)
        return 0.0


def _transcode(src, ext, args):
    """转成识别引擎认的格式。没有 ffmpeg 就原样返回，让引擎自己碰运气。"""
    if not has_ffmpeg():
        return src
    dst = os.path.join(tempfile.gettempdir(), "asr-" + uuid.uuid4().hex + ext)
    try:
        subprocess.run(["ffmpeg", "-y", "-i", src] + args + [dst],
                       capture_output=True, timeout=180, check=True)
        return dst if os.path.getsize(dst) > 0 else src
    except Exception:
        log.info("ffmpeg 转码失败，改用原始音频", exc_info=True)
        return src


def _run_zhipu(path):
    """OpenAI 兼容的语音转写接口：multipart 传 file + model，回 {"text": ...}。"""
    import requests

    c = asr_conf()
    # 云端普遍认 mp3/wav，不一定认 webm/opus；顺手压到 16k 单声道，上传快一截
    f = _transcode(path, ".mp3", ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k"])
    try:
        with open(f, "rb") as fp:
            r = requests.post(
                c["base"] + "/audio/transcriptions",
                headers={"Authorization": "Bearer " + c["key"]},
                files={"file": (os.path.basename(f), fp, "audio/mpeg")},
                data={"model": c["model"]}, timeout=180)
        if r.status_code >= 400:
            raise RuntimeError("识别接口返回 %d：%s" % (r.status_code, r.text[:200]))
        try:
            d = r.json()
        except ValueError:
            raise RuntimeError("识别接口返回的不是 JSON：" + r.text[:200])
        # 各家字段不完全一致：标准是 text，也见过包一层 result/segments 的
        txt = d.get("text") or d.get("result") or ""
        if not txt and isinstance(d.get("segments"), list):
            txt = "".join(s.get("text") or "" for s in d["segments"])
        return (txt or "").strip()
    finally:
        if f != path:
            _rm(f)


def _run_whisper(path):
    """本地 whisper.cpp。只吃 16kHz 单声道 wav，所以这一步的转码不是可选的。"""
    c = asr_conf()
    wav = _transcode(path, ".wav", ["-vn", "-ac", "1", "-ar", "16000"])
    try:
        r = subprocess.run(
            [c["bin"], "-m", c["wmodel"], "-f", wav, "-l", "zh", "-nt", "-np", "--no-prints"],
            capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError("whisper 退出码 %d：%s" % (r.returncode, (r.stderr or "")[-200:]))
        # -nt 已去掉时间戳，剩下的是逐行正文；空行和 [BLANK_AUDIO] 这类占位要滤掉
        lines = [ln.strip() for ln in (r.stdout or "").splitlines()]
        return " ".join(ln for ln in lines if ln and not ln.startswith("[")).strip()
    finally:
        if wav != path:
            _rm(wav)


_ENGINES = {"zhipu": _run_zhipu, "whisper": _run_whisper}


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        log.debug("临时音频没删掉：%s", p, exc_info=True)


def transcribe(path):
    """转文字。返回文本；转不出来抛 RuntimeError（调用方负责变成人话）。"""
    c = asr_conf()
    fn = _ENGINES.get(c["engine"])
    if not fn:
        raise RuntimeError("管理员还没开启语音转文字")
    if not asr_configured():
        raise RuntimeError("语音转文字没配置好（后台 → 语音识别）")
    dur = audio_duration(path)
    if dur > MAX_SECONDS:
        raise RuntimeError("这段语音 %d 秒，超过 %d 秒上限了" % (int(dur), MAX_SECONDS))
    txt = fn(path)
    if not txt:
        raise RuntimeError("没识别出内容（可能太吵、太轻，或整段没人说话）")
    return txt


def save_upload(f, prefix="asr"):
    """把上传的音频落成临时文件，返回路径。调用方用完自己删。"""
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in (".webm", ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".mp4", ".wav", ".aac", ".amr"):
        ext = ".webm"          # 手机 WebView 上传常常没扩展名
    p = os.path.join(tempfile.gettempdir(), prefix + "-" + uuid.uuid4().hex + ext)
    f.save(p)
    return p


# ---------------------------------------------------------------- 前台
@bp.get("/api/asr/status")
def asr_status():
    """前端据此决定「转文字」按钮给不给点。"""
    return jsonify({"enabled": asr_configured(), "engine": asr_conf()["engine"],
                    "max_seconds": MAX_SECONDS})


@bp.post("/api/asr")
def asr_upload():
    """一段录音换一段文字。AI 助手的「语音输入」走这条。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "没有音频"}), 400
    if not asr_configured():
        return jsonify({"error": "语音转文字还没开启（管理员可在后台 → 语音识别 里配置）"}), 503
    p = save_upload(f)
    try:
        if os.path.getsize(p) > MAX_BYTES:
            return jsonify({"error": "录音太大了"}), 400
        return jsonify({"text": transcribe(p), "seconds": audio_duration(p)})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception:
        log.exception("语音识别失败")
        return jsonify({"error": "识别失败了，稍后再试"}), 502
    finally:
        _rm(p)


# ---------------------------------------------------------------- 后台
@bp.get("/api/admin/asr")
def admin_asr_get():
    c = asr_conf()
    return jsonify({
        "engine": c["engine"], "base": c["base"], "model": c["model"],
        "has_key": bool(CFG.get("asr_key")), "borrow_vision": bool(
            not CFG.get("asr_key") and CFG.get("vision_key")),
        "whisper_bin": c["bin"], "whisper_model": c["wmodel"],
        "configured": asr_configured(), "ffmpeg": has_ffmpeg(),
        "whisper_found": bool(shutil.which(c["bin"])),
        "defaults": {"base": ZHIPU_BASE, "model": ZHIPU_MODEL},
    })


@bp.post("/api/admin/asr")
def admin_asr_set():
    data = request.get_json(silent=True) or {}
    if "engine" in data:
        e = (data.get("engine") or "").strip()
        CFG["asr_engine"] = e if e in _ENGINES else ""
    for k, cfgk in (("base", "asr_base"), ("model", "asr_model"),
                    ("whisper_bin", "asr_whisper_bin"), ("whisper_model", "asr_whisper_model")):
        if k in data:
            CFG[cfgk] = (data.get(k) or "").strip()
    if data.get("clear_key"):
        CFG["asr_key"] = ""
    elif (data.get("key") or "").strip():
        CFG["asr_key"] = data["key"].strip()
    _save_cfg()
    return jsonify({"ok": True, "configured": asr_configured()})


@bp.post("/api/admin/asr/test")
def admin_asr_test():
    """拿一段现生成的静音之外的音频试跑一次。

    没有麦克风也要能在后台确认「配置对不对」——这里用 ffmpeg 合成 1 秒提示音走完
    整条链路。**识别不出文字是正常的**（本来就没人说话），我们要看的是接口通不通、
    Key 对不对、whisper 二进制在不在。
    """
    if not asr_configured():
        return jsonify({"ok": False, "msg": "还没配置好：引擎、Key/模型路径检查一下"}), 400
    if not has_ffmpeg():
        return jsonify({"ok": False, "msg": "服务器上没有 ffmpeg，装一个：sudo apt install ffmpeg"}), 400
    p = os.path.join(tempfile.gettempdir(), "asrtest-" + uuid.uuid4().hex + ".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-ac", "1", "-ar", "16000", p], capture_output=True, timeout=60, check=True)
        txt = _ENGINES[asr_conf()["engine"]](p)
        return jsonify({"ok": True, "msg": "链路通了（识别结果：%s）" % (txt or "空——这段本来就没人说话，正常")})
    except RuntimeError as e:
        return jsonify({"ok": False, "msg": str(e)}), 502
    except Exception as e:
        log.exception("语音识别自测失败")
        return jsonify({"ok": False, "msg": "跑不通：%s" % e}), 502
    finally:
        _rm(p)
