"""装配：蓝图别拆了忘注册。

这组是踩坑踩出来的：拆模块时 auth / me / attach 三个蓝图建好了却漏了
register_blueprint，23 个路由（含 /api/login、/api/register）**静默消失**。

为什么没被发现——test_smoke 的路由用例是从 app.url_map 动态收集的：
路由没了，它就少跑几条，照样全绿。动态收集的测试防不住「东西不见了」，
只能防「东西坏了」。所以这里换个方向：从文件系统数模块，跟注册表对。
"""
import os
import re

from conftest import BASE, appmod

MODS = BASE / "mods"


def _modules_with_blueprint():
    out = []
    for f in sorted(os.listdir(MODS)):
        if not f.endswith(".py") or f == "__init__.py":
            continue
        src = (MODS / f).read_text(encoding="utf-8")
        if re.search(r'^bp = Blueprint\(', src, re.M):
            out.append(f[:-3])
    return out


def test_每个蓝图模块都注册上了():
    """漏一个，它的路由就全没了，而动态收集路由的测试看不出来。"""
    app_src = (BASE / "app.py").read_text(encoding="utf-8")
    missing = [m for m in _modules_with_blueprint()
               if not re.search(r'register_blueprint\(%s_bp\)' % re.escape(m), app_src)]
    assert not missing, (
        "这些模块定义了蓝图却没 register_blueprint，路由会静默消失：%s" % missing)


def test_注册的蓝图数量与模块数一致():
    app_src = (BASE / "app.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'register_blueprint\((\w+)_bp\)', app_src))
    assert registered == set(_modules_with_blueprint())


class TestCriticalRoutes:
    """几条关键路由的硬清单。动态收集防不住整块丢失，这里写死。"""

    ROUTES = [
        ("/api/login", "POST"), ("/api/register", "POST"), ("/api/me", "GET"),
        ("/api/annots", "GET"), ("/api/annots", "POST"),
        ("/api/review/today", "GET"), ("/api/review/done", "POST"),
        ("/api/entries", "GET"), ("/api/notes", "GET"), ("/api/materials", "GET"),
        ("/api/search", "GET"), ("/api/news", "GET"), ("/api/plan/today", "GET"),
        ("/api/drill/quiz", "POST"), ("/api/chat/conversations", "GET"),
        ("/api/friends", "GET"), ("/api/drive", "GET"), ("/api/wrongq", "GET"),
        ("/api/admin/users", "GET"), ("/api/sync", "GET"),
    ]

    def test_关键路由一个都不能少(self):
        have = {(str(r.rule), m)
                for r in appmod.app.url_map.iter_rules()
                for m in r.methods}
        missing = [f"{m} {p}" for p, m in self.ROUTES if (p, m) not in have]
        assert not missing, "这些路由没了：%s" % missing


def test_路由总数不低于基线():
    """拆分前是 291 条。少了就是哪个蓝图掉了；多了是加了新功能，把基线调上去即可。"""
    n = len(list(appmod.app.url_map.iter_rules()))
    assert n >= 291, f"路由只剩 {n} 条（基线 291）——大概率有蓝图没注册"
