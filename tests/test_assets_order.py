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
    js, gz, etag = assets.bundle()
    assert js and gz and etag
    html = assets._CACHE["html"]
    assert "app.bundle.js" in html
    # bundle 标签在所有 section 收尾之后
    assert html.rfind("</section>") < html.find("app.bundle.js")


def test_早加载的脚本不被并进_bundle():
    """带属性的标签（data-early）打包器不认，它得留在原地单独加载。"""
    js, _, _ = assets.bundle()
    html = assets._CACHE["html"]
    assert 'src="js/daylight.js"' in html, "早加载的脚本标签被打包器吃掉了"
    assert "DL_KEYS" not in js.decode("utf8"), "早加载的脚本被并进了 bundle，会随 bundle 一起提前执行"
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


def test_打包内容与标签顺序一致():
    """bundle 里各文件的先后，必须和 index.html 里标签的先后一样 —— 顺序是行为的一部分。"""
    from core import STATIC
    from pathlib import Path
    html = (Path(STATIC) / "index.html").read_text(encoding="utf8")
    srcs = re.findall(r'<script src="(js/[^"]+\.js)"></script>', html)
    js = assets.bundle()[0].decode("utf8")
    pos = [js.find("/* ==== %s ==== */" % s) for s in srcs]
    assert all(p >= 0 for p in pos), "有文件没进 bundle"
    assert pos == sorted(pos), "bundle 里的文件顺序和 index.html 里的标签顺序不一致"
