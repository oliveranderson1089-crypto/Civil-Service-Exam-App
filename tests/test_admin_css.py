"""后台页的样式撞车守卫。

`admin.html` 是独立页面，但它 `<link>` 了主应用的 `static/style.css`——于是它内联
`<style>` 里写的类名，只要跟主应用同名，就会同时吃到那边的声明。

这条测试是拿一个真 bug 换来的：后台三处按钮行用了 `.ai-acts`，而主应用的 `.ai-acts`
是 AI 对话里「悬停才浮出来」的操作条（`opacity:0`，靠 `.ai-row:hover` 点亮）。后台没有
`.ai-row`，所以「保存邀请码」「开放/关闭注册」「清除 Key」「测试连通」这些按钮**永远
是透明的**——DOM 在、位置也占着、点上去还有反应，就是看不见。这类事故不会报错、
不会进日志，只能靠盯住「两边定义了同名类」这条约束本身。

白名单里的是确认过不冲突的（主应用那边只有复合选择器、或者两边的声明本来就一致）。
往里加名字之前，先去 style.css 看一眼那个类都声明了什么。
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# 确认过不冲突的同名类。加名字前先看 style.css 里那条规则写了什么，
# 尤其是 opacity / display / visibility / position 这几个「会让人看不见」的属性。
ALLOWED = {
    "bad", "cp-bar", "danger", "err", "new", "ok", "on", "pill",
    "primary", "sel", "sub", "t", "view-title", "warn", "zero",
}

# 这几个属性一旦从主应用漏进后台，症状都是「元素在，但看不见/跑位了」
_HIDING = re.compile(r"opacity\s*:\s*0(?!\.)|display\s*:\s*none|visibility\s*:\s*hidden")


def _strip(css):
    """去掉注释。这两份 CSS 的注释里到处在讲「.ai-acts 那次」「见 style.css」，
    不剥掉的话它们会被当成定义过的类名，测试自己给自己报假警。"""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _classes(css):
    """从一段 CSS 里取出被**定义**过的类名（只看选择器部分）。"""
    out = set()
    for sel in re.findall(r"([^{}]+)\{", _strip(css)):
        out.update(re.findall(r"\.([a-zA-Z][\w-]*)", sel))
    return out


def _admin_style():
    html = (BASE / "static" / "admin.html").read_text(encoding="utf-8")
    return re.search(r"<style>(.*?)</style>", html, re.S).group(1)


def test_后台内联样式不和主应用撞类名():
    both = _classes(_admin_style()) & _classes((BASE / "static" / "style.css").read_text(encoding="utf-8"))
    assert not (both - ALLOWED), (
        "admin.html 内联定义的这些类，主应用 style.css 里也定义了：%s。\n"
        "后台 link 了 style.css，两边会叠在一起——`.ai-acts` 那次就是整行按钮隐形。\n"
        "改个后台专用的名字；确认过不冲突再加进 ALLOWED。" % "、".join(sorted(both - ALLOWED)))


def test_白名单里的类没有隐藏声明():
    """白名单是人工判断的，而 style.css 一直在改——它可能哪天给某个白名单类加上
    opacity:0。这条盯的是那种「白名单当年没问题、后来变成有问题」的漂移。"""
    css = (BASE / "static" / "style.css").read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip(css)):
        sel, body = m.group(1), m.group(2)
        if not _HIDING.search(body):
            continue
        # 只认「光秃秃的类选择器」：.foo{...} / .foo,.bar{...}。
        # .foo .bar 或 .foo.bar 这种带上下文的，后台没有那个上下文，漏不过来。
        for one in sel.split(","):
            one = one.strip()
            if re.fullmatch(r"\.([a-zA-Z][\w-]*)", one) and one[1:] in ALLOWED:
                bad.append((one, body.strip()[:60]))
    assert not bad, "白名单里的类在 style.css 里被加了隐藏声明：%s" % bad
