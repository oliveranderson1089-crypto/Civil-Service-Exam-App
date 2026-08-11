"""前端静态资源打包 —— 把 index.html 里那串 <script src="js/*.js"> 合成 1 个 bundle。

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

# 只认「js/xxx.js」这种相对 src，且整行就一个 script 标签（index.html 末尾那 56 行就是）
_SCRIPT_RE = re.compile(r'[ \t]*<script src="(js/[^"]+\.js)"></script>[ \t]*\n?')
# style.css 也挂内容指纹。它本来靠固定 URL + no-cache 回源校验，链路上（Cloudflare 隧道、
# 安卓 WebView）只要有一层没照做，就会出现「JS 更新了、CSS 还是旧的」这种半新不旧的状态，
# 排查起来极其费劲。URL 里带上哈希，改了必然重取。
_CSS_RE = re.compile(r'href="style\.css(?:\?[^"]*)?"')

_LOCK = threading.Lock()
_CACHE = {"mtime": None, "js": b"", "js_gz": b"", "etag": "", "html": ""}


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


def _rebuild():
    """读 index.html + 56 个 js，拼 bundle、算哈希、压 gzip、把标签换成一个 bundle 标签。"""
    idx = Path(STATIC) / "index.html"
    html = idx.read_text(encoding="utf-8")
    srcs = _SCRIPT_RE.findall(html)
    if not srcs:
        raise RuntimeError("index.html 里没找到 <script src=js/*.js> 标签，放弃打包")
    files = [Path(STATIC) / s for s in srcs]
    _check_tags_at_end(html)
    css = Path(STATIC) / "style.css"
    mtime = _newest_mtime([idx, *files] + ([css] if css.exists() else []))

    parts = []
    for src, f in zip(srcs, files):
        # 每个文件前补 `\n;`：万一某文件结尾漏了分号，也不会和下一个文件首行黏成一句
        parts.append(f"\n;/* ==== {src} ==== */\n")
        parts.append(f.read_text(encoding="utf-8"))
    js = "".join(parts).encode("utf-8")
    etag = 'b' + hashlib.sha1(js).hexdigest()[:16]

    # 56 个标签整体换成一个：第一个标签的位置放 bundle 标签，其余删掉
    one = f'<script src="/js/app.bundle.js?v={etag}"></script>\n'
    seen = [0]

    def _repl(_m):
        seen[0] += 1
        return one if seen[0] == 1 else ""

    html_b = _SCRIPT_RE.sub(_repl, html)
    if css.exists():
        cssv = hashlib.sha1(css.read_bytes()).hexdigest()[:16]
        html_b = _CSS_RE.sub(f'href="style.css?v={cssv}"', html_b)

    _CACHE.update(mtime=mtime, js=js, js_gz=gzip.compress(js, 6),
                  etag='"' + etag + '"', html=html_b)


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


def bundle():
    """返回 (js_bytes, js_gzip_bytes, etag)。"""
    _ensure_fresh()
    return _CACHE["js"], _CACHE["js_gz"], _CACHE["etag"]


def index_html():
    """返回把脚本标签合成一个 bundle 标签后的 index.html 文本；打包失败会抛异常。"""
    _ensure_fresh()
    return _CACHE["html"]


def warm():
    """启动时预热一次：能拼就拼、拼不了就抛，让调用方决定要不要启用打包。"""
    _rebuild()
