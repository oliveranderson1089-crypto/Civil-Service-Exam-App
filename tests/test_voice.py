"""聊天语音条 + 语音转文字（ASR）。

两条要守的线：
  1. **发语音不依赖识别引擎**。引擎默认是关的，这时候录一段照样能发、能听、能撤回；
     只有「转文字」那一下才会被挡（503），而且要说人话。
  2. 语音的时长和转写结果塞在 body 的 JSON 里（没为它加表列），所以凡是会读 body 的地方
     ——会话列表摘要、搜索结果——都不能把那串 JSON 原样端给用户。
"""
import io
import json
import shutil
import sqlite3
import subprocess
import tempfile

import pytest

import core
from conftest import DB
from mods import asr as asrmod

FRIEND = 91501


def _exec(*stmts):
    con = sqlite3.connect(DB, timeout=10)
    try:
        for st in stmts:
            sql, params = (st, ()) if isinstance(st, str) else st
            con.execute(sql, params)
        con.commit()
    finally:
        con.close()


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def me(auth_client):
    u = _uid()
    # 语音也会在云盘「聊天文件」里留记录，一起清掉：别的用例会数 source='chat' 有几条
    _exec("DELETE FROM chat_msgs", "DELETE FROM drive_files WHERE source='chat'",
          ("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
           (FRIEND, "friend91501", "x")),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, FRIEND)),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (FRIEND, u)))
    return u


@pytest.fixture(autouse=True)
def engine_off():
    """每个用例都从「识别引擎没开」起步——那才是默认状态。"""
    for k in ("asr_engine", "asr_key", "asr_model", "asr_base",
              "asr_whisper_bin", "asr_whisper_model"):
        core.CFG.pop(k, None)
    yield
    core.CFG.pop("asr_engine", None)


def _wav(seconds=1.0):
    """现生成一段 wav。用真音频而不是随便几个字节：后端要 ffprobe 量时长。"""
    if not shutil.which("ffmpeg"):
        pytest.skip("没有 ffmpeg，这台机器上量不出时长")
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=%s" % seconds,
                        "-ac", "1", "-ar", "16000", f.name],
                       capture_output=True, check=True)
        with open(f.name, "rb") as fp:
            return fp.read()


def _send_voice(c, to, data=None, dur="1.0"):
    return c.post("/api/chat/%d" % to, data={
        "file": (io.BytesIO(data if data is not None else _wav()), "voice.wav"),
        "voice": "1", "dur": dur,
    }, content_type="multipart/form-data")


def test_send_voice_without_engine(auth_client, me):
    """引擎关着也能发语音、也能听 —— 这是这次改动最要紧的一条。"""
    r = _send_voice(auth_client, FRIEND)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json()["dur"] > 0            # 时长由服务端量，不信前端报的那个

    msgs = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"]
    assert len(msgs) == 1 and msgs[0]["kind"] == "voice"
    assert msgs[0]["dur"] > 0 and msgs[0]["text"] == ""
    assert msgs[0]["file_id"], "语音要能按文件取回来，不然放不出声"
    # 音频本身取得到（气泡里的播放就是拉这个地址）
    assert auth_client.get("/api/chat/file/%d?inline=1" % msgs[0]["file_id"]).status_code == 200


def test_voice_body_not_leaked(auth_client, me):
    """body 里那串 JSON 不能出现在会话列表和搜索结果里。"""
    _send_voice(auth_client, FRIEND)
    convos = auth_client.get("/api/chat/conversations").get_json()["conversations"]
    prev = [x["preview"] for x in convos if x.get("id") == FRIEND]
    assert prev and prev[0].startswith("[语音]") and "dur" not in prev[0]

    hits = auth_client.get("/api/chat/search?q=voice").get_json()["results"]
    assert all("{" not in (h.get("text") or "") for h in hits)


def test_transcribe_blocked_when_off(auth_client, me):
    """没开引擎时点「转文字」：要给 503 + 一句能照做的提示，而不是 500。"""
    _send_voice(auth_client, FRIEND)
    mid = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][0]["id"]
    r = auth_client.post("/api/chat/msg/%d/voicetext" % mid)
    assert r.status_code == 503
    assert "后台" in r.get_json()["error"]
    assert auth_client.get("/api/asr/status").get_json()["enabled"] is False


def test_transcribe_caches(auth_client, me, monkeypatch):
    """转过一次就写回消息：第二次点不该再调引擎（云端是按量计费的）。"""
    _send_voice(auth_client, FRIEND)
    mid = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][0]["id"]
    calls = []
    monkeypatch.setattr(asrmod, "asr_configured", lambda: True)
    monkeypatch.setattr(asrmod, "transcribe", lambda p: calls.append(p) or "今天先把资料分析刷完")

    r = auth_client.post("/api/chat/msg/%d/voicetext" % mid)
    assert r.status_code == 200 and r.get_json()["text"] == "今天先把资料分析刷完"
    r2 = auth_client.post("/api/chat/msg/%d/voicetext" % mid)
    assert r2.get_json()["cached"] is True
    assert len(calls) == 1, "第二次不该再调引擎"

    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][0]
    assert m["text"] == "今天先把资料分析刷完" and m["dur"] > 0   # 转写不能把时长冲掉
    # 转完之后列表摘要直接显示那句话，别再是一排「[语音]」
    convos = auth_client.get("/api/chat/conversations").get_json()["conversations"]
    assert any("资料分析" in (x["preview"] or "") for x in convos)


def test_reject_non_audio(auth_client, me):
    """带 voice=1 却传了别的东西：挡住，别在库里留一条放不出声的语音。"""
    r = auth_client.post("/api/chat/%d" % FRIEND, data={
        "file": (io.BytesIO(b"not audio at all"), "voice.txt"), "voice": "1", "dur": "3",
    }, content_type="multipart/form-data")
    assert r.status_code == 400


def test_plain_file_still_file(auth_client, me):
    """不带 voice=1 的音频还是普通文件消息（老客户端发的、或者真就是想传个 mp3）。"""
    auth_client.post("/api/chat/%d" % FRIEND, data={
        "file": (io.BytesIO(_wav()), "song.wav"),
    }, content_type="multipart/form-data")
    m = auth_client.get("/api/chat/%d" % FRIEND).get_json()["messages"][0]
    assert m["kind"] == "file"


def test_asr_engine_switch(auth_client, me):
    """后台切引擎：写进 CFG，未填全时 configured 仍是 False。"""
    r = auth_client.post("/api/admin/asr", json={"engine": "whisper",
                                                 "whisper_bin": "definitely-not-here"})
    assert r.get_json()["configured"] is False
    assert core.CFG["asr_engine"] == "whisper"
    # 不认识的引擎名当成关闭，别把配置写坏
    auth_client.post("/api/admin/asr", json={"engine": "某个不存在的引擎"})
    assert core.CFG["asr_engine"] == ""
    assert auth_client.get("/api/admin/asr").get_json()["engine"] == ""


def test_asr_upload_needs_engine(auth_client, me):
    """AI 助手的语音输入：引擎没开就 503，别静默返回空文本。"""
    r = auth_client.post("/api/asr", data={"file": (io.BytesIO(_wav()), "v.wav")},
                         content_type="multipart/form-data")
    assert r.status_code == 503


def test_voice_body_shape():
    """body 的形状是约定，前后端都按它读——脏数据也要能退化出一个能画的气泡。"""
    from mods.social import _voice_body, _voice_of
    assert json.loads(_voice_body(3.14159, "喂")) == {"dur": 3.1, "text": "喂"}
    assert _voice_of({"body": "这不是 JSON"}) == {"dur": 0.0, "text": ""}
