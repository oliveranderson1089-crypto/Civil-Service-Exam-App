"""前端静态资源打包 —— 把 index.html 里那串 <script src="js/*.js"> 合成 2 个 bundle。

重构把前端从 15 个 js 拆成了 56 个，index.html 于是排了 56 个同步阻塞的
<script>。手机端（尤其走 Cloudflare 隧道 + 代理时）要为此发 56 个请求、每个都
no-store 重下、还没压缩 —— 首屏迟迟出不来，6 秒兜底把启动页撤掉就成了「白屏没内容」。

这里把这 56 个文件按 index.html 里的原次序拼成一个 /js/app.bundle.js：
  - 56 个请求 → 1 个；配 gzip（约 636KB → 190KB）与内容哈希版本号（长缓存自动失效）
  - 拼接是「同一段 classic 脚本按序连起来」，顶层 let/const 共享全局词法环境，
    行为与 56 个 <script> 逐个执行完全一致（node --check 已验证无语法/重复声明问题）
  - 出任何岔子（读文件失败、找不到标签…）就抛异常，调用方退回原始 index.html +
    56 个单独标签。所以打包只会更快，绝不会把应用弄坏。

依赖单向：assets.py → core.py（拿 STATIC 路径），无环。
"""
import gzip
import hashlib
import re
import threading
from pathlib import Path

from core import STATIC

# ---------------------------------------------------------------- 首屏清单
# 打成一个包解决的是**请求数**，没解决**字节数**：手机冷启动要先下完整包、
# 再解析 1.1MB 的 JS，才轮到「今日」那几个数字出现（走隧道时更明显）。
# 所以再切一刀：首屏必需的进 core、其余进 rest（defer，DOM 解析完再执行）。
#
# 清单是**显式**写在这儿的，不是自动算的 —— 自动算要么过松（线上白屏），
# 要么过严（等于没拆）。但它必须和真实依赖对得上，所以
# tests/frontend/bundle_split.test.js 会做两件事盯着它：
#   ① 只加载 core 包，启动要能走完，不许抛 ReferenceError
#   ② core 里任何文件的**顶层同步代码**都不许引用 rest 里定义的符号
# 加了新 js 之后测试挂了，先想清楚它到底要不要进首屏，再改这份清单。
#
# 判据是「加载那一刻会不会被同步求值」，不是「重不重要」：
# 挂 onclick、写进路由表的引用都是延后执行的，等用户点的时候 rest 早到了。
# chat.js(80K) / aichat.js(61K) / find.js(43K) / drive.js(37K) 都属于这一类。
CORE_FILES = [
    "js/core.js",         # 地基：$ / api / esc，人人都用
    "js/articons.js",     # 图标册：外壳第一帧就要画
    "js/qtimer.js",
    "js/shell.js",        # 外壳：启动屏、面包屑、返回栈
    "js/materials.js", "js/entries.js", "js/classics.js", "js/basics.js",
    "js/topbar.js", "js/video.js", "js/news.js", "js/gongwen.js",
    "js/yylib.js", "js/yyerr.js", "js/drill.js", "js/write.js",
    "js/changkao.js", "js/theory.js", "js/works.js", "js/changshi.js",
    "js/policydocs.js", "js/fanwen.js", "js/partydict.js",
    "js/theme.js",        # 主题：晚一拍就是肉眼可见的闪一下
    "js/notifications.js", "js/quizdetail.js", "js/ink.js", "js/dock.js",
    "js/matpanel.js", "js/desktop.js",
    "js/tabs.js", "js/tabviews.js",   # 常驻导航
    "js/today.js",        # 首屏仪表盘，末尾 tdLoad() 是整个启动的最后一步
]

# 只认「js/xxx.js」这种相对 src，且整行就一个 script 标签（index.html 末尾那 56 行就是）
_SCRIPT_RE = re.compile(r'[ \t]*<script src="(js/[^"]+\.js)"></script>[ \t]*\n?')
# style.css 也挂内容指纹。它本来靠固定 URL + no-cache 回源校验，链路上（Cloudflare 隧道、
# 安卓 WebView）只要有一层没照做，就会出现「JS 更新了、CSS 还是旧的」这种半新不旧的状态，
# 排查起来极其费劲。URL 里带上哈希，改了必然重取。
_CSS_RE = re.compile(r'href="style\.css(?:\?[^"]*)?"')

_LOCK = threading.Lock()
# 两个包各自一份内容哈希：改了 rest 不该让 core 的长缓存失效，反之亦然。
_CACHE = {"mtime": None, "html": "",
          "core": {"js": b"", "gz": b"", "etag": ""},
          "rest": {"js": b"", "gz": b"", "etag": ""}}


def _newest_mtime(paths):
    return max(p.stat().st_mtime for p in paths)


def _check_tags_at_end(html):
    """确认可打包的那串 <script> 都在 DOM 后面。

    打包是把它们**整体挪到第一个标签的位置**。所以只要有一个可打包的脚本被插在页面中间
    （比如贴着启动屏那段 DOM），整个 bundle 就会提前到 DOM 还没解析完时执行 ——
    第一个 $('#xxx') 就是 null，应用当场停在启动页，而且**只在打包后的线上才复现**
    （测试是等 DOM 全解析完再求值的，照样绿）。这条闸把它变成"退回不打包"，而不是白屏。

    要早于 DOM 加载的脚本，给标签加个属性（如 data-early）绕开 _SCRIPT_RE 即可。
    """
    m = _SCRIPT_RE.search(html)
    if not m:
        return
    last_dom = max(html.rfind("</section>"), html.rfind("</main>"), html.rfind("</div>"))
    if last_dom > m.start():
        raise RuntimeError(
            "可打包的 <script> 出现在 DOM 中间（位置 %d，DOM 收尾在 %d）："
            "打包会把整个 bundle 提前到那儿执行，应用会停在启动页。"
            "要早加载就给那个标签加 data-early 之类的属性绕开打包。" % (m.start(), last_dom))


def _split(srcs):
    """按 CORE_FILES 把脚本清单切成 (core, rest)，**两边都保持 index.html 里的原次序**。

    次序不能动：拼接的语义是「同一段 classic 脚本按序连起来」，顶层 let/const
    走的是全局词法环境，谁先谁后决定了谁看得见谁。
    清单里写了但 index.html 里没有的（删了某个 js 却忘了改清单），这里直接忽略——
    真正会出事的是反过来，那由测试盯着。
    """
    core = [s for s in srcs if s in CORE_FILES]
    rest = [s for s in srcs if s not in CORE_FILES]
    if not core:
        raise RuntimeError("core 包一个文件都没有：CORE_FILES 和 index.html 对不上了")
    return core, rest


def _pack(srcs):
    """把一组 js 拼成 (bytes, gzip, etag)。"""
    parts = []
    for src in srcs:
        # 每个文件前补 `\n;`：万一某文件结尾漏了分号，也不会和下一个文件首行黏成一句
        parts.append(f"\n;/* ==== {src} ==== */\n")
        parts.append((Path(STATIC) / src).read_text(encoding="utf-8"))
    js = "".join(parts).encode("utf-8")
    return js, gzip.compress(js, 6), "b" + hashlib.sha1(js).hexdigest()[:16]


def _rebuild():
    """读 index.html + 71 个 js，拼成 core / rest 两个 bundle，把标签换成两个标签。"""
    idx = Path(STATIC) / "index.html"
    html = idx.read_text(encoding="utf-8")
    srcs = _SCRIPT_RE.findall(html)
    if not srcs:
        raise RuntimeError("index.html 里没找到 <script src=js/*.js> 标签，放弃打包")
    files = [Path(STATIC) / s for s in srcs]
    _check_tags_at_end(html)
    css = Path(STATIC) / "style.css"
    mtime = _newest_mtime([idx, *files] + ([css] if css.exists() else []))

    core_srcs, rest_srcs = _split(srcs)
    cjs, cgz, cetag = _pack(core_srcs)
    rjs, rgz, retag = _pack(rest_srcs) if rest_srcs else (b"", b"", "")

    # 所有标签整体换成两个：第一个标签的位置放它俩，其余删掉。
    # rest 用 defer —— 它保证「在 core 之后、在 DOMContentLoaded 之前」执行：
    #   · 在 core 之后 → rest 里的顶层代码能看见 core 定义的东西
    #   · 在 DOMContentLoaded 之前 → 用户能点之前它已经就位
    # 不能用 async：async 不保证顺序，rest 可能先于 core 执行，那就全炸了。
    tags = f'<script src="/js/app.bundle.js?v={cetag}"></script>\n'
    if rest_srcs:
        tags += f'<script src="/js/app.rest.js?v={retag}" defer></script>\n'
    seen = [0]

    def _repl(_m):
        seen[0] += 1
        return tags if seen[0] == 1 else ""

    html_b = _SCRIPT_RE.sub(_repl, html)
    if css.exists():
        cssv = hashlib.sha1(css.read_bytes()).hexdigest()[:16]
        html_b = _CSS_RE.sub(f'href="style.css?v={cssv}"', html_b)

    _CACHE.update(mtime=mtime, html=html_b,
                  core={"js": cjs, "gz": cgz, "etag": '"' + cetag + '"'},
                  rest={"js": rjs, "gz": rgz, "etag": '"' + retag + '"' if retag else ""})


def _ensure_fresh():
    """有改动才重拼（改了某个 js / index.html / style.css 就自动失效）；线程安全。"""
    idx = Path(STATIC) / "index.html"
    srcs = _SCRIPT_RE.findall(idx.read_text(encoding="utf-8"))
    files = [idx] + [Path(STATIC) / s for s in srcs]
    css = Path(STATIC) / "style.css"
    if css.exists():
        files.append(css)
    mtime = _newest_mtime(files)
    if _CACHE["mtime"] != mtime:
        with _LOCK:
            if _CACHE["mtime"] != mtime:   # 双检，别重复拼
                _rebuild()


def bundle(which="core"):
    """返回 (js_bytes, js_gzip_bytes, etag)。which 取 "core" 或 "rest"。"""
    _ensure_fresh()
    c = _CACHE[which]
    return c["js"], c["gz"], c["etag"]


def index_html():
    """返回把脚本标签换成两个 bundle 标签后的 index.html 文本；打包失败会抛异常。"""
    _ensure_fresh()
    return _CACHE["html"]


def warm():
    """启动时预热一次：能拼就拼、拼不了就抛，让调用方决定要不要启用打包。"""
    _rebuild()
