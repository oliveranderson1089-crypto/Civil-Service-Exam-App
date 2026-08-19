"""服务级档位控制（aiclient.effective_tier + mods/aitier.py）的测试。

这一层的价值全在「无处可漏」：管理员在后台把某个服务降到 fast，就得连那 13 个
没人 import 的定时器脚本一起管住。所以最要紧的两条不是接口的增删改，而是：
  · test_chat真的按覆盖发出去 —— 解析对了但没接进调用的话，线上一分钱都省不下来。
  · test_展示接口不被覆盖染色 —— 「现在配的是哪个模型」必须是配置原样，
    否则后台 AI 设置页会跟着「谁在问」变，改配置的人第一步就被误导。
"""
import ast
import json
import re
from io import BytesIO
from pathlib import Path

import pytest

import aiclient
import core

BASE = Path(__file__).resolve().parent.parent


def _ok(text="ok"):
    return json.dumps({"choices": [{"message": {"content": text},
                                   "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()


class _FakeResp:
    def __init__(self, body):
        self.body = BytesIO(body)

    def __enter__(self):
        return self.body

    def __exit__(self, *a):
        return False


CFG = {"ai_model": "m-fast", "ai_model_pro": "m-pro", "ai_key": "k"}


# ---------------------------------------------------------------- 解析优先级
class Test档位解析:
    def test_没设覆盖就跟着代码走(self):
        assert aiclient.effective_tier("pro", CFG, "gen_essays") == "pro"

    def test_按服务降级(self):
        cfg = dict(CFG, ai_tiers={"gen_essays": "fast"})
        assert aiclient.effective_tier("pro", cfg, "gen_essays") == "fast"
        assert aiclient.effective_tier("pro", cfg, "gen_quiz") == "pro", "不该殃及别的服务"

    def test_全局兜底(self):
        cfg = dict(CFG, ai_tiers={"*": "fast"})
        assert aiclient.effective_tier("pro", cfg, "谁都行") == "fast"

    def test_精确到档位的键最优先(self):
        """write 里 fast 的取材和 pro 的成文是两码事：只想降成文的钱，
        不想把取材也从便宜档「升」到贵档。"""
        cfg = dict(CFG, ai_tiers={"*": "pro", "write": "pro", "write:pro": "fast"})
        assert aiclient.effective_tier("pro", cfg, "write") == "fast"
        assert aiclient.effective_tier("fast", cfg, "write") == "pro"

    def test_服务键压过全局(self):
        cfg = dict(CFG, ai_tiers={"*": "fast", "find": "pro"})
        assert aiclient.effective_tier("fast", cfg, "find") == "pro"
        assert aiclient.effective_tier("pro", cfg, "别人") == "fast"

    @pytest.mark.parametrize("bad", [{"gen_quiz": "旗舰"}, {"gen_quiz": ""},
                                     {"gen_quiz": None}, {"gen_quiz": 3}, "不是字典"])
    def test_脏值一律当没设(self, bad):
        """配置文件是人手改过的（emergency.sh、备份回滚），别让一个错值把调用整崩。"""
        cfg = dict(CFG, ai_tiers=bad)
        assert aiclient.effective_tier("pro", cfg, "gen_quiz") == "pro"

    def test_who为空串时不查覆盖(self):
        cfg = dict(CFG, ai_tiers={"*": "fast"})
        assert aiclient.effective_tier("pro", cfg, who="") == "pro"


# ---------------------------------------------------------------- 真的发出去了
class Test接进调用:
    def test_conf按覆盖给模型名(self):
        cfg = dict(CFG, ai_tiers={"gen_essays": "fast"})
        assert aiclient.conf("pro", cfg, who="gen_essays")["model"] == "m-fast"
        assert aiclient.conf("pro", cfg, who="")["model"] == "m-pro"

    def test_chat真的按覆盖发出去(self, monkeypatch):
        """caller 是本测试模块，所以这里能端到端验一次「后台设了 → 请求真变了」。"""
        seen = []
        monkeypatch.setattr(aiclient, "_open",
                            lambda c, payload, t: (seen.append(payload["model"]),
                                                   _FakeResp(_ok()))[1])
        cfg = dict(CFG, ai_tiers={"test_aitier": "fast"})
        aiclient.chat([], cfg=cfg, tier="pro")
        assert seen == ["m-fast"], "档位覆盖没接进真实请求，等于一分钱没省"

    def test_记账记的是生效档位(self, monkeypatch):
        """报表和面板是同一套口径：设成 fast 之后，用量就该记在 fast 上。"""
        got = {}
        monkeypatch.setattr(aiclient, "_open", lambda *a, **k: _FakeResp(_ok()))
        monkeypatch.setattr(aiclient.aimeter, "record",
                            lambda **kw: got.update(kw))
        aiclient.chat([], cfg=dict(CFG, ai_tiers={"test_aitier": "fast"}), tier="pro")
        assert got["tier"] == "fast" and got["model"] == "m-fast"


# ---------------------------------------------------------------- 后台接口
def _set(client, confirmed=True, **kv):
    """默认带 confirmed：多数用例验的不是闸而是设置本身。闸有专门一节。"""
    return client.post("/api/admin/ai/tiers", json={"set": kv, "confirmed": confirmed})


class Test后台接口:
    @pytest.fixture(autouse=True)
    def _clean_cfg(self):
        old = core.CFG.get(aiclient.OVERRIDE_KEY)
        yield
        if old is None:
            core.CFG.pop(aiclient.OVERRIDE_KEY, None)
        else:
            core.CFG[aiclient.OVERRIDE_KEY] = old
        core._save_cfg()

    def test_未登录进不去(self, client):
        assert client.get("/api/admin/ai/tiers").status_code in (302, 401, 403)

    def test_面板列出服务与当前档位(self, auth_client):
        d = auth_client.get("/api/admin/ai/tiers").get_json()
        svcs = {s["key"]: s for g in d["groups"] for s in g["services"]}
        assert {"gen_essays", "agent", "write"} <= set(svcs)
        assert {"fast", "pro", "vision_free", "vision_pro"} <= set(d["models"])
        assert {r["tier"] for r in svcs["write"]["text"]["rows"]} == {"fast", "pro"}, \
            "混档服务要能分别设"
        assert svcs["docqa"]["vision"]["rows"], "会读图的服务要有读图那一列旋钮"
        assert not svcs["gen_essays"]["vision"]["rows"], "不读图的服务别摆一个没用的旋钮"

    def test_设置与清除(self, auth_client):
        assert _set(auth_client, gen_essays="fast").get_json()["ok"]
        assert core.CFG[aiclient.OVERRIDE_KEY]["gen_essays"] == "fast"
        assert aiclient.effective_tier("pro", core.CFG, "gen_essays") == "fast"
        # 空串 = 跟随默认，也是唯一的清除方式
        _set(auth_client, gen_essays="")
        assert "gen_essays" not in core.CFG[aiclient.OVERRIDE_KEY]
        assert aiclient.effective_tier("pro", core.CFG, "gen_essays") == "pro"

    def test_批量一次改一片(self, auth_client):
        r = _set(auth_client, **{"gen_essays": "fast", "gen_quiz": "fast", "*": "fast"})
        assert r.get_json()["changed"] == 3
        d = auth_client.get("/api/admin/ai/tiers").get_json()
        assert d["global"] == {"text": "fast", "vision": ""}

    def test_落盘了而不只是改内存(self, auth_client):
        """定时器脚本是另起的进程，读的是盘上的 config.json——没落盘等于没生效。"""
        _set(auth_client, gen_quiz="fast")
        on_disk = json.load(open(core.CONFIG, encoding="utf-8"))
        assert on_disk[aiclient.OVERRIDE_KEY]["gen_quiz"] == "fast"
        assert aiclient.effective_tier("pro", None, "gen_quiz") == "fast", "脱离 Flask 的脚本也要跟着变"

    @pytest.mark.parametrize("kv", [{"gen_quiz": "旗舰"}, {"gen_quiz": "vision"}])
    def test_拒绝非法档位(self, auth_client, kv):
        assert _set(auth_client, **kv).status_code == 400

    def test_拒绝乱七八糟的键(self, auth_client):
        """config.json 是全站共用的，接口不能变成往里写任意键的入口。"""
        auth_client.post("/api/admin/ai/tiers",
                         json={"set": {"../../etc": "fast", "a b": "fast"}})
        assert not (core.CFG.get(aiclient.OVERRIDE_KEY) or {})

    def test_展示接口不被覆盖染色(self, auth_client):
        """AI 设置页显示的必须是「两个档位各配了哪个模型」，
        不能因为某个服务被降级就跟着变——否则改配置的人第一步就被误导。"""
        _set(auth_client, **{"*": "fast"})
        d = auth_client.get("/api/admin/ai").get_json()
        assert d["model_pro"] == aiclient.conf("pro", core.CFG, who="")["model"]
        assert d["model_pro"] != d["model"]


# ---------------------------------------------------------------- 名册别过期
def test_代码里写了pro的模块名册必须标pro():
    """名册是人工维护的，最容易过期的正是「这个服务本来该用哪档」。

    过期的后果不是报错而是**误导**：面板上写着 fast 的服务其实在烧 pro 的钱，
    管理员按面板做的成本判断全是错的。所以这条按代码里真实写的 tier="pro" 来对。
    """
    from mods import aitier
    src = {}
    for p in list(BASE.glob("*.py")) + list((BASE / "mods").glob("*.py")):
        if p.name in ("ai.py", "aiclient.py", "aitier.py"):
            continue        # 转发层/真源本身的 tier= 是参数默认值，不是业务选择
        if re.search(r'tier\s*=\s*["\']pro["\']', p.read_text(encoding="utf-8")):
            src[p.stem] = True
    for mod in src:
        assert mod in aitier._MAP, "%s 用了 pro 档但名册里没有，后台看不到它" % mod
        assert "pro" in aitier._MAP[mod][2], "%s 名册里没标 pro，面板会给出错误的成本印象" % mod


def test_名册里的服务都真实存在():
    """反过来防的是「模块删了名册还留着」：面板上摆一个永远 0 调用的幽灵服务。"""
    from mods import aitier
    for key, *_ in aitier.SERVICES:
        assert (BASE / ("%s.py" % key)).exists() or (BASE / "mods" / ("%s.py" % key)).exists(), \
            "名册里的 %s 找不到对应模块" % key


# ---------------------------------------------------------------- 降档闸
class Test降档要确认:
    @pytest.fixture(autouse=True)
    def _clean_cfg(self):
        for k in (aiclient.OVERRIDE_KEY, aiclient.VISION_KEY):
            core.CFG.pop(k, None)
        yield
        for k in (aiclient.OVERRIDE_KEY, aiclient.VISION_KEY):
            core.CFG.pop(k, None)
        core._save_cfg()

    def test_把旗舰服务降下来要先确认(self, auth_client):
        r = _set(auth_client, confirmed=False, gen_real_explain="fast").get_json()
        assert r["ok"] is False
        assert r["need_confirm"][0]["key"] == "gen_real_explain"
        assert "真题" in r["need_confirm"][0]["why"], "得说清降的是什么、会怎样"
        assert aiclient.OVERRIDE_KEY not in core.CFG or \
            "gen_real_explain" not in core.CFG[aiclient.OVERRIDE_KEY], "没确认就不许落库"

    def test_确认之后才真的写进去(self, auth_client):
        assert _set(auth_client, gen_real_explain="fast").get_json()["ok"]
        assert aiclient.effective_tier("pro", core.CFG, "gen_real_explain") == "fast"

    def test_升档不拦(self, auth_client):
        """升档只是多花钱——钱是管理员自己的事，用不着挡一道。"""
        assert _set(auth_client, confirmed=False, crawl_news="pro").get_json()["ok"]

    def test_本来就是快档的服务降不着(self, auth_client):
        assert _set(auth_client, confirmed=False, crawl_news="fast").get_json()["ok"]

    def test_只降混档服务的旗舰那一半要确认(self, auth_client):
        r = auth_client.post("/api/admin/ai/tiers",
                             json={"set": {"write:pro": "fast"}}).get_json()
        assert r["ok"] is False and r["need_confirm"][0]["key"] == "write:pro"
        # 同一个服务里本来就走 fast 的那一半，设成 fast 是原地踏步，不该弹
        assert auth_client.post("/api/admin/ai/tiers",
                                json={"set": {"write:fast": "fast"}}).get_json()["ok"]

    def test_全站兜底降档会列出被殃及的服务(self, auth_client):
        r = auth_client.post("/api/admin/ai/tiers",
                             json={"set": {"*": "fast"}}).get_json()
        why = r["need_confirm"][0]["why"]
        assert "大作文成文" in why and "项" in why, "得让人看见这一下压到了谁、一共多少"

    def test_一条要确认就一条都不写(self, auth_client):
        """不能「弹窗还开着，一半改动已经生效了」——要么全过要么全不过。"""
        r = auth_client.post("/api/admin/ai/tiers", json={
            "set": {"crawl_news": "pro", "gen_essays": "fast"}}).get_json()
        assert r["ok"] is False
        assert not core.CFG.get(aiclient.OVERRIDE_KEY), "被拦下时不该留下半截改动"


# ---------------------------------------------------------------- 读图那家
class Test读图档位:
    @pytest.fixture(autouse=True)
    def _clean_cfg(self):
        yield
        core.CFG.pop(aiclient.VISION_KEY, None)
        core._save_cfg()

    def test_解析与文字档位同一套规则(self):
        cfg = {aiclient.VISION_KEY: {"*": "free", "docqa": "pro", "docqa:pro": "free"}}
        assert aiclient.effective_vision("pro", cfg, "别人") == "free"
        assert aiclient.effective_vision("free", cfg, "docqa") == "pro"
        assert aiclient.effective_vision("pro", cfg, "docqa") == "free", "精确键最优先"
        assert aiclient.effective_vision("pro", cfg, who="") == "pro", "展示不被染色"

    def test_两家互不干扰(self):
        """键分两张表存：把文字降了，读图不该跟着降。"""
        cfg = {aiclient.OVERRIDE_KEY: {"*": "fast"}}
        assert aiclient.effective_vision("pro", cfg, "docqa") == "pro"
        assert aiclient.effective_tier("pro", cfg, "docqa") == "fast"

    def test_读图真的按覆盖走(self, monkeypatch):
        """vision_chat 里 prefer 决定先打哪个模型；覆盖没接进去就等于没做。"""
        from mods import ai as aimod
        core.CFG[aiclient.VISION_KEY] = {"test_aitier": "pro"}
        core.CFG.update(vision_base="https://v.test", vision_key="k",
                        vision_model="v-pro", vision_model_free="v-free")
        seen = []

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "图上写着字"}}],
                                   "usage": {}}).encode()

        def fake(req, timeout=None):
            seen.append(json.loads(req.data)["model"])
            return _R()

        monkeypatch.setattr(aimod.urllib.request, "urlopen", fake)
        aimod.vision_chat("读图", ["data:image/jpeg;base64,AAAA"], prefer="free")
        assert seen[0] == "v-pro", "设成旗舰后就不该再先去打免费档"

    def test_读图降档也要确认(self, auth_client):
        r = auth_client.post("/api/admin/ai/tiers",
                             json={"vision": {"docqa": "free"}}).get_json()
        assert r["ok"] is False and r["need_confirm"][0]["kind"] == "vision"
        r = auth_client.post("/api/admin/ai/tiers",
                             json={"vision": {"docqa": "free"}, "confirmed": True}).get_json()
        assert r["ok"] and core.CFG[aiclient.VISION_KEY]["docqa"] == "free"

    @pytest.mark.parametrize("bad", ["fast", "旗舰"])
    def test_读图不认文字那套档位名(self, auth_client, bad):
        assert auth_client.post("/api/admin/ai/tiers",
                                json={"vision": {"docqa": bad}, "confirmed": True}
                                ).status_code == 400


def test_读图的模块名册必须标出来():
    """跟 pro 那条同一个道理：名册过期不报错，只让面板给出错误的印象。

    这里对的是「谁真的会去读图」——调了 vision_chat / vision_ocr 的模块，
    面板上就该有那一列旋钮；prefer="pro" 的还得标成旗舰，不然管理员会以为
    自己已经把读图的钱管住了，其实最贵的那几处根本没在面板上。
    """
    from mods import aitier
    for p in list(BASE.glob("*.py")) + list((BASE / "mods").glob("*.py")):
        if p.name in ("ai.py", "aitier.py"):
            continue                    # 转发层自己不算调用方
        txt = p.read_text(encoding="utf-8")
        if not re.search(r"\bvision_(chat|ocr)\s*\(", txt):
            continue
        e = aitier._MAP.get(p.stem)
        assert e, "%s 会读图但名册里没有" % p.stem
        assert e[3], "%s 会读图，名册里得给它读图那一列" % p.stem
        if re.search(r'prefer\s*=\s*["\']pro["\']', txt):
            assert "pro" in e[3], "%s 读图默认走旗舰，名册没标就会误导成本判断" % p.stem
