"""前端资源的缓存策略：绝不能让 CDN/浏览器把「旧版本」发给用户。

改版历史（都是踩坑踩出来的）：
- 起初前端是一个 app.js，外壳一律 no-store。
- 拆成 js/*.js 后一度漏登记，差点让 CDN 存旧脚本。
- 现在 56 个 js 合并成 /js/app.bundle.js：带内容哈希版本号走 immutable 长缓存
  （内容一变 URL 就变，天然发不出旧的）；仍能单独取的 js/css/sw 走 no-cache
  （每次带 ETag 回源校验，也发不出旧的）；真·外壳页走 no-store。

这里从 index.html 读真实脚本清单去验，别自己抄一份 —— 抄的迟早跟 index.html 走散。
"""
import re

from conftest import BASE


def _script_srcs():
    html = (BASE / "static/index.html").read_text(encoding="utf-8")
    return re.findall(r'<script src="(js/[^"]+\.js)"></script>', html)


class TestAssetCache:
    def test_每个单独脚本都会回源校验不发旧版本(self, auth_client):
        srcs = _script_srcs()
        assert srcs, "index.html 里一个 <script src=js/*.js> 都没有？"
        bad = []
        for s in srcs:
            r = auth_client.get("/" + s)
            cc = r.headers.get("Cache-Control", "")
            if r.status_code != 200 or "no-cache" not in cc:
                bad.append(f"{s} -> {r.status_code} {cc or '(无 Cache-Control)'}")
        assert not bad, "这些前端脚本没有 no-cache（回源校验），CDN 可能发旧版本：\n  " + "\n  ".join(bad)

    def test_合并bundle带版本号且走immutable长缓存(self, auth_client):
        html = auth_client.get("/").get_data(as_text=True)
        m = re.search(r'/js/app\.bundle\.js\?v=(\w+)', html)
        assert m, "首页没有引用带版本号的 /js/app.bundle.js（打包没生效？）"
        r = auth_client.get("/js/app.bundle.js")
        cc = r.headers.get("Cache-Control", "")
        assert r.status_code == 200
        assert "immutable" in cc and "max-age" in cc, f"bundle 该走 immutable 长缓存，实际：{cc}"
        assert r.headers.get("ETag"), "bundle 该带 ETag（内容哈希）"

    def test_bundle条件请求返回304(self, auth_client):
        etag = auth_client.get("/js/app.bundle.js").headers.get("ETag")
        r = auth_client.get("/js/app.bundle.js", headers={"If-None-Match": etag})
        assert r.status_code == 304, "同版本再请求该回 304，别重下一整份"

    def test_外壳页no_store_可校验资源no_cache(self, auth_client):
        for p in ("/", "/index.html"):
            assert "no-store" in auth_client.get(p).headers.get("Cache-Control", ""), f"{p} 该 no-store"
        for p in ("/style.css", "/sw.js", "/manifest.webmanifest"):
            assert "no-cache" in auth_client.get(p).headers.get("Cache-Control", ""), f"{p} 该 no-cache"

    def test_上传的资料不该被no_store(self, auth_client):
        """no-store 是给外壳用的。资料/图片那些内容文件该让浏览器缓存，
        否则每次翻页都重下，家里的上行只有一百多 KB/s。"""
        r = auth_client.get("/api/materials")
        assert r.status_code == 200
        assert "no-store" not in r.headers.get("Cache-Control", ""), "API 不该进 no-store 名单"

    def test_文本响应会gzip压缩(self, auth_client):
        for p in ("/js/app.bundle.js", "/style.css"):
            r = auth_client.get(p, headers={"Accept-Encoding": "gzip"})
            assert r.headers.get("Content-Encoding") == "gzip", f"{p} 该被 gzip 压缩"


class TestAuthPageAssets:
    """登录 / 注册 / 找回三页引用的东西，**没登录也得拿得到**。

    这三页的外观从内联 <style> 挪进了 static/auth.css，底图由 js/daylight.js 画
    （和启动屏同一张色表）。它们不在 _PUBLIC_EXACT 里的话，未登录访问一律 302 回
    /login —— 页面照样出来，只是一堆没样式的裸标签，而且**服务端没有任何报错**。
    这里从三页的 HTML 里读真实引用去验，别自己抄一份清单。
    """

    PAGES = ("login.html", "register.html", "forgot.html")

    @staticmethod
    def _refs(page):
        html = (BASE / "static" / page).read_text(encoding="utf-8")
        return (re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
                + re.findall(r'<script src="([^"]+)"', html))

    def test_三页的样式和脚本未登录就能取到(self, client):
        bad = []
        for page in self.PAGES:
            refs = self._refs(page)
            assert refs, f"{page} 里一个 css/js 引用都没有？"
            for ref in refs:
                r = client.get("/" + ref.lstrip("/"))
                if r.status_code != 200:
                    bad.append(f"{page} 引的 /{ref} -> {r.status_code}（没登录拿不到）")
        assert not bad, "登录页会变成没样式的裸标签：\n  " + "\n  ".join(bad)

    def test_登录页那套资源会回源校验(self, client):
        for p in ("/auth.css", "/js/daylight.js", "/js/auth.js"):
            cc = client.get(p).headers.get("Cache-Control", "")
            assert "no-cache" in cc, f"{p} 该 no-cache（URL 固定又没内容哈希），实际：{cc or '(无)'}"
