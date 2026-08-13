"""打包器：可打包的 <script> 必须都在 DOM 后面。

这是线上真出过的事故，且**只在打包后复现**：
把一个 `<script src="js/daylight.js"></script>` 插在启动屏那段 DOM 后面（页面中间），
assets.py 会把 56 个脚本合成的整个 bundle **挪到第一个标签的位置**执行 ——
那时下面的 DOM 还没解析，shell.js 第一句 `$('#crumb').addEventListener` 就是
"null is not an object"，其后所有顶层语句（包括撤启动页的兜底定时器、init()）全不执行。
表现就是：启动屏停在那儿，进不去主页面。

前端测试抓不到它：jsdom 是把脚本拼好、等 DOM 全解析完再求值的，顺序问题在那儿不存在。
所以这条闸和这个测试放在后端。
"""
import re

import pytest

import assets


def test_真实的_index_html_通过检查():
    """当前仓库里的 index.html 必须是合规的 —— 这条一红就是有人又把脚本插到中间了。"""
    js, gz, etag = assets.bundle("core")
    assert js and gz and etag
    html = assets._CACHE["html"]
    assert "app.bundle.js" in html
    # bundle 标签在所有 section 收尾之后
    assert html.rfind("</section>") < html.find("app.bundle.js")


def test_早加载的脚本不被并进_bundle():
    """带属性的标签（data-early）打包器不认，它得留在原地单独加载。"""
    html = assets._CACHE["html"]
    assert 'src="js/daylight.js"' in html, "早加载的脚本标签被打包器吃掉了"
    both = assets.bundle("core")[0].decode("utf8") + assets.bundle("rest")[0].decode("utf8")
    assert "DL_KEYS" not in both, "早加载的脚本被并进了 bundle，会随 bundle 一起提前执行"
    # 它必须排在 bundle 之前（启动屏要在第一帧就是对的颜色）
    assert html.find('js/daylight.js') < html.find("app.bundle.js")


def test_脚本插在_DOM_中间时宁可不打包也不打错():
    """把闸门单独拎出来测：给它一段"脚本在中间"的 HTML，必须抛异常。

    抛异常 = 调用方退回不打包的原始 index.html（56 个标签，慢但对），
    而不是打出一个顺序错误的 bundle 把应用弄死。
    """
    bad = ('<body><div id="splash"></div>\n'
           '<script src="js/daylight.js"></script>\n'
           '<section id="view-home"></section>\n'
           '<script src="js/core.js"></script>\n</body>')
    with pytest.raises(RuntimeError) as e:
        assets._check_tags_at_end(bad)
    assert "启动页" in str(e.value) or "DOM" in str(e.value)


def test_脚本都在末尾时闸门放行():
    ok = ('<body><div id="splash"></div>\n<section id="view-home"></section></div>\n'
          '<script src="js/core.js"></script>\n<script src="js/shell.js"></script>\n</body>')
    assets._check_tags_at_end(ok)          # 不抛就是通过


def test_两个包合起来不重不漏():
    """core + rest 必须正好覆盖 index.html 里的全部脚本。

    漏一个 = 那个功能的函数永远不存在（点了就 ReferenceError）；
    重一个 = 同一段顶层代码执行两遍，事件绑两次、计数器翻倍。
    两种都不会在启动时报错，只会在某个具体功能上莫名其妙。
    """
    from pathlib import Path

    from core import STATIC
    html = (Path(STATIC) / "index.html").read_text(encoding="utf8")
    srcs = re.findall(r'<script src="(js/[^"]+\.js)"></script>', html)
    core_js = assets.bundle("core")[0].decode("utf8")
    rest_js = assets.bundle("rest")[0].decode("utf8")

    for s in srcs:
        mark = "/* ==== %s ==== */" % s
        in_core, in_rest = mark in core_js, mark in rest_js
        assert in_core or in_rest, "%s 两个包里都没有" % s
        assert not (in_core and in_rest), "%s 同时进了两个包，会执行两遍" % s


def test_每个包内部与标签顺序一致():
    """包**内部**各文件的先后，必须和 index.html 里标签的先后一样。

    注意这条只管包内。**跨包的相对顺序确实变了** —— 原先 convo.js 排在
    materials.js 前面，拆完 materials 在 core、convo 在 rest，于是 materials 先跑。
    这是拆包的本质（core 整体先执行，rest 整体后执行），不是 bug；
    它的安全性由 tests/frontend/bundle_split.test.js 的两道闸保证：
    core 的顶层同步代码不许引用 rest 里定义的符号。
    """
    from pathlib import Path

    from core import STATIC
    html = (Path(STATIC) / "index.html").read_text(encoding="utf8")
    srcs = re.findall(r'<script src="(js/[^"]+\.js)"></script>', html)
    for which in ("core", "rest"):
        js = assets.bundle(which)[0].decode("utf8")
        pos = [js.find("/* ==== %s ==== */" % s) for s in srcs]
        got = [p for p in pos if p >= 0]
        assert got == sorted(got), "%s 包里的文件顺序和 index.html 里的标签顺序不一致" % which


def test_rest_包必须是_defer():
    """rest 只能用 defer，绝不能用 async。

    defer 保证「在 core 之后、在 DOMContentLoaded 之前」执行；
    async 是下完就跑、不保证顺序 —— rest 可能先于 core 执行，
    那时 core.js 里的 $ / api 都还不存在，整个应用当场散架。
    """
    html = assets._CACHE["html"]
    m = re.search(r'<script src="/js/app\.rest\.js[^"]*"([^>]*)>', html)
    assert m, "index.html 里没有 rest 包的标签"
    attrs = m.group(1)
    assert "defer" in attrs, "rest 包丢了 defer，执行时机就没保证了"
    assert "async" not in attrs, "rest 包用了 async —— 它不保证顺序，会先于 core 执行"


def test_首屏包确实小于整包():
    """拆完首屏还占八成以上的话，这刀不值它带来的风险。"""
    c = len(assets.bundle("core")[0])
    r = len(assets.bundle("rest")[0])
    assert r > 0, "rest 空了 —— 这刀等于没拆"
    assert c < (c + r) * 0.8, "首屏包占 %.0f%%，拆得不够" % (100.0 * c / (c + r))
