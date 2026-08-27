"""视觉这一路的三个档：free/pro 走智谱，exact 走 DeepSeek —— **是两家，不是两个模型名**。

2026-08-27 拿《社区知识三色笔记》实测（那份 PDF 的文字层自己把「费孝通」存成了
「翌生通」，所以每处坏字都是一道有唯一答案的题）：整页转写 DeepSeek 9/9、12 秒，
智谱旗舰 8/9、77 秒；但认三色笔记里哪句是红字，智谱旗舰 17/18、DeepSeek 时灵时不灵。
所以 exact 是**多一档**，默认仍是智谱。这里锁住三件容易悄悄坏掉的事：
  1. 两家的 base 形状不同（智谱填到 /paas/v4，DeepSeek 只到域名），补地址不能一刀切；
  2. exact 用的是推理模型，额度要按 aiclient.budget 放宽，否则推理段吃光、正文一个字不出；
  3. 空正文不许当成功 —— 那会变成「识别完了，内容是空的」，比报错还难查。
"""
import json

import pytest

import aiclient
from mods import ai as aimod


# ---------------- 地址补全 ----------------

@pytest.mark.parametrize("base,want", [
    ("https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    ("https://open.bigmodel.cn/api/paas/v4/", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
    ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/chat/completions"),
    ("https://x.com/chat/completions", "https://x.com/chat/completions"),
])
def test_两家的地址各补各的(base, want):
    assert aimod._vision_url(base) == want


# ---------------- 档位名册 ----------------

def test_exact_在档位名册里():
    assert "exact" in aiclient.VISION_TIERS, "不在名册里，后台档位控制就设不了这一档"
    assert aiclient.effective_vision("exact", {}) == "exact"


def test_不认识的档位退回free():
    assert aiclient.effective_vision("胡说八道", {}) == "free"


# ---------------- 三档各带各的落点 ----------------

def test_三档各自带着自己的base和key(monkeypatch):
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "vision_model": "glm-4.6v", "vision_model_free": "glm-4.6v-flash",
        "ai_base": "https://api.deepseek.com", "ai_key": "DK"})
    lanes = aimod._vision_conf()["lanes"]
    assert lanes["pro"]["key"] == "ZK" and "zhipu" in lanes["pro"]["base"]
    assert lanes["exact"]["key"] == "DK" and "deepseek" in lanes["exact"]["base"], \
        "exact 是另一家：只换模型名会拿着智谱的 key 去敲 DeepSeek 的门"


def test_exact可以单独配到别的端点(monkeypatch):
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "ai_base": "https://api.deepseek.com", "ai_key": "DK",
        "vision_exact_base": "https://elsewhere/v1", "vision_exact_key": "EK",
        "vision_exact_model": "some-vision-model"})
    e = aimod._vision_conf()["lanes"]["exact"]
    assert (e["base"], e["key"], e["model"]) == ("https://elsewhere/v1", "EK", "some-vision-model")


def test_没配deepseek就说这档不可用(monkeypatch):
    monkeypatch.setattr(aimod, "CFG", {"vision_base": "https://zhipu/api/paas/v4",
                                       "vision_key": "ZK"})
    assert aimod.vision_exact_configured() is False, \
        "前端据此藏起那个按钮 —— 摆出来点了没反应，比没有这个按钮更糟"


# ---------------- 推理模型的额度 ----------------

def test_推理视觉模型要额外的推理额度():
    """业务给的 max_tokens 只是正文额度。不加这一份，实测会「跑了几十秒、正文一个字没有」。"""
    assert aiclient.budget("deepseek-v4-flash-vision-exp", 1800) > 1800
    assert aiclient.budget("glm-4.6v", 1800) == 1800, "智谱不是推理模型，别平白多给"


def test_整页OCR的额度够装一页中文():
    """原来是 1800，实测在整页讲义的第 26 条上无声截断（后半页全没）。"""
    assert aimod.VISION_OCR_TOKENS >= 3000


# ---------------- 调用行为 ----------------

def _fake_urlopen(captured, content="识别结果"):
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": content}}],
                               "usage": {"total_tokens": 10}}).encode()

    def op(req, timeout=None):
        captured.append({"url": req.full_url,
                         "auth": req.headers.get("Authorization"),
                         "body": json.loads(req.data.decode())})
        return R()
    return op


def test_精准档真的打到deepseek(monkeypatch):
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "vision_model": "glm-4.6v", "ai_base": "https://api.deepseek.com", "ai_key": "DK"})
    monkeypatch.setattr(aimod.aiclient, "effective_vision", lambda p, c=None, w=None: p)
    got = []
    monkeypatch.setattr(aimod.urllib.request, "urlopen", _fake_urlopen(got))
    out = aimod.vision_chat("转写", ["data:image/jpeg;base64,AA"], prefer="exact")
    assert out == "识别结果"
    assert got[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert got[0]["auth"] == "Bearer DK"
    assert got[0]["body"]["model"] == aimod.VISION_EXACT_MODEL
    assert got[0]["body"]["max_tokens"] > 1500, "推理模型的额度没放宽，正文会被推理段挤空"


def test_默认还是走智谱(monkeypatch):
    """exact 更快更准是**对整页转写而言**；认图形、认三色笔记的颜色仍是智谱旗舰强，
    别因为跑分好看就把默认换掉。"""
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "vision_model": "glm-4.6v", "ai_base": "https://api.deepseek.com", "ai_key": "DK"})
    monkeypatch.setattr(aimod.aiclient, "effective_vision", lambda p, c=None, w=None: p)
    got = []
    monkeypatch.setattr(aimod.urllib.request, "urlopen", _fake_urlopen(got))
    aimod.vision_chat("看图", ["data:image/jpeg;base64,AA"], prefer="pro")
    assert got[0]["auth"] == "Bearer ZK" and got[0]["body"]["model"] == "glm-4.6v"


def test_精准档不可用时退回智谱(monkeypatch):
    """宁可慢一点，也别让这一次识别整个失败。"""
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "vision_model": "glm-4.6v", "ai_base": "", "ai_key": ""})
    monkeypatch.setattr(aimod.aiclient, "effective_vision", lambda p, c=None, w=None: p)
    got = []
    monkeypatch.setattr(aimod.urllib.request, "urlopen", _fake_urlopen(got))
    aimod.vision_chat("看图", ["data:image/jpeg;base64,AA"], prefer="exact")
    assert got[0]["body"]["model"] == "glm-4.6v"


def test_空正文不算成功(monkeypatch):
    """推理段偶尔会吃光额度、正文一个字不出。当成功返回的话，上游拿到的是
    「识别完了，内容为空」—— 比报错还难查。"""
    monkeypatch.setattr(aimod, "CFG", {
        "vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
        "vision_model": "glm-4.6v", "vision_model_free": "", "ai_base": "", "ai_key": ""})
    monkeypatch.setattr(aimod.aiclient, "effective_vision", lambda p, c=None, w=None: p)
    monkeypatch.setattr(aimod.time, "sleep", lambda *a: None)
    monkeypatch.setattr(aimod.urllib.request, "urlopen", _fake_urlopen([], content=""))
    with pytest.raises(RuntimeError):
        aimod.vision_chat("看图", ["data:image/jpeg;base64,AA"], prefer="pro")


# ---------------- 后台「档位控制」摆得出这一档 ----------------
# 加了档位却没接进后台面板，表现是「代码里有、界面上设不了」—— 用户看到的就是
# 「你说的那个选项在哪」。2026-08-27 第一版就漏了这一步。

@pytest.fixture
def vision_cfg(monkeypatch):
    """测试库的 config 是空的。这一档要配了才该露面，所以先把两家都配上。"""
    import core
    for k, v in {"vision_base": "https://zhipu/api/paas/v4", "vision_key": "ZK",
                 "vision_model": "glm-4.6v", "vision_model_free": "glm-4.6v-flash",
                 "ai_base": "https://api.deepseek.com", "ai_key": "DK"}.items():
        monkeypatch.setitem(core.CFG, k, v)
    return core.CFG


def test_档位面板给出精准档的模型名(auth_client, vision_cfg):
    d = auth_client.get("/api/admin/ai/tiers?win=30d").get_json()
    assert d["models"]["vision_exact"], "面板拿不到模型名就不会摆出那个按钮"


def test_没配那一家就不摆出这个按钮(auth_client, monkeypatch):
    """摆出一个点了设不了的按钮，比没有这个按钮更糟。"""
    import core
    monkeypatch.setitem(core.CFG, "ai_key", "")
    monkeypatch.setitem(core.CFG, "vision_exact_key", "")
    d = auth_client.get("/api/admin/ai/tiers?win=30d").get_json()
    assert d["models"]["vision_exact"] == ""


def test_读图可以设成精准档(auth_client):
    r = auth_client.post("/api/admin/ai/tiers",
                         json={"vision": {"*": "exact"}, "confirmed": True})
    assert r.status_code == 200
    assert auth_client.get("/api/admin/ai/tiers?win=30d").get_json()["global"]["vision"] == "exact"


def test_读图档位仍然只认名册里的那几个(auth_client):
    r = auth_client.post("/api/admin/ai/tiers",
                         json={"vision": {"*": "胡说八道"}, "confirmed": True})
    assert r.status_code == 400
    assert "exact" in r.get_json()["error"], "报错要把可选项列全，不然管理员得去翻代码"
