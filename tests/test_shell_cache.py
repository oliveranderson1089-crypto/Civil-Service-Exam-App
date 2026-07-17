"""外壳文件必须带 no-store。

这组是踩坑踩出来的：app.js 拆成 js/*.js 之后，_SHELL_NOSTORE 里还写着老的
/app.js，15 个新文件一个都没登记 —— 全都只剩 no-cache，CDN 可以存副本，
而这行当初就是为了「让 Cloudflare 与浏览器都不要缓存，避免旧脚本」加的。

前端那 22 条 jsdom 测试一条都没拦住：它们测的是 app.js 的内部行为，
而缓存头是 Flask 的 after_request 给的 —— 两边都没人管。

所以这里从 index.html 里**读真实的 script 清单**去验，而不是自己抄一份：
抄的那份迟早跟 index.html 走散，就又回到「漏登记」的老路。
"""
import re

from conftest import BASE


def _script_srcs():
    html = (BASE / "static/index.html").read_text(encoding="utf-8")
    return re.findall(r'<script src="([^"]+)"></script>', html)


class TestShellNoStore:
    def test_index_html_里的每个脚本都带no_store(self, auth_client):
        srcs = _script_srcs()
        assert srcs, "index.html 里一个 <script src> 都没有？"
        bad = []
        for s in srcs:
            r = auth_client.get("/" + s.lstrip("/"))
            cc = r.headers.get("Cache-Control", "")
            if r.status_code != 200 or "no-store" not in cc:
                bad.append(f"{s} -> {r.status_code} {cc or '(无 Cache-Control)'}")
        assert not bad, "这些前端脚本没有 no-store，CDN 可能发旧版本给用户：\n  " + "\n  ".join(bad)

    def test_样式和外壳页也带no_store(self, auth_client):
        for p in ("/", "/index.html", "/style.css", "/sw.js", "/manifest.webmanifest"):
            r = auth_client.get(p)
            assert "no-store" in r.headers.get("Cache-Control", ""), f"{p} 少了 no-store"

    def test_上传的资料不该被no_store(self, auth_client):
        """no-store 是给外壳用的。资料/图片那些内容文件该让浏览器缓存，
        否则每次翻页都重下，家里的上行只有一百多 KB/s。"""
        r = auth_client.get("/api/materials")
        assert r.status_code == 200
        assert "no-store" not in r.headers.get("Cache-Control", ""), "API 不该进 no-store 名单"

    def test_新增前端文件时这条会红(self):
        """守着「加了文件忘登记」——正是这次踩的坑。
        _SHELL_NOSTORE 是按 /js/ 前缀放行的，所以只要脚本都放在 js/ 下就自动覆盖。"""
        import app as appmod
        for s in _script_srcs():
            p = "/" + s.lstrip("/")
            assert appmod._is_shell(p), (
                f"{p} 不在外壳判断里 —— 它要么得挪进 js/，要么得进 _SHELL_NOSTORE")
