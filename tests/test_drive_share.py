"""云盘分享链接与缩略图。

分享是**全站唯一免登录就能取到东西的入口**（app.py 的 _is_public 放行了 /s/），
所以这里盯的全是「不该拿到的时候拿不拿得到」：过期、被删、进了回收站、token 乱编。
"""
import io
import os
import time

from mods import social


def _up(client, name, folder="", data=b"x"):
    r = client.post("/api/drive", data={"file": (io.BytesIO(data), name), "folder": folder},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()


# ---- 分享链接 ----

def test_建链接后不登录也能下到文件(auth_client, flask_app):
    body = "分享出去的内容".encode()
    a = _up(auth_client, "分享.txt", "分享", body)
    d = auth_client.post("/api/drive/%d/share" % a["id"], json={"days": 7}).get_json()
    assert d["url"].startswith("/s/") and len(d["token"]) >= 30, "token 太短，猜得出来就没意义了"
    anon = flask_app.test_client()                  # 全新 client，没有登录态
    r = anon.get(d["url"])
    assert r.status_code == 200, "分享链接对未登录的人应该是能用的"
    assert r.data == body
    assert "attachment" in r.headers.get("Content-Disposition", ""), \
        "公开地址上必须当附件下发，不能内联渲染别人上传的 .html"
    assert "sandbox" in (r.headers.get("Content-Security-Policy") or "")


def test_同一个文件重复点分享复用同一条链接(auth_client):
    a = _up(auth_client, "别重复.txt", "分享")
    t1 = auth_client.post("/api/drive/%d/share" % a["id"], json={}).get_json()["token"]
    t2 = auth_client.post("/api/drive/%d/share" % a["id"], json={}).get_json()["token"]
    assert t1 == t2, "每点一次就发一条新链接，收都收不回来"


def test_过期的链接取不到(auth_client, flask_app):
    a = _up(auth_client, "会过期.txt", "分享")
    d = auth_client.post("/api/drive/%d/share" % a["id"], json={"days": 1}).get_json()
    # 把过期时间改到过去
    with flask_app.app_context():
        from core import get_db
        get_db().execute("UPDATE drive_shares SET expires_at=? WHERE token=?",
                         ("2000-01-01 00:00:00", d["token"]))
        get_db().commit()
    assert flask_app.test_client().get(d["url"]).status_code == 410


def test_文件进了回收站链接立刻失效(auth_client, flask_app):
    a = _up(auth_client, "删了就没.txt", "分享")
    d = auth_client.post("/api/drive/%d/share" % a["id"], json={}).get_json()
    assert flask_app.test_client().get(d["url"]).status_code == 200
    auth_client.delete("/api/drive/%d" % a["id"])
    assert flask_app.test_client().get(d["url"]).status_code == 404, \
        "文件都扔回收站了，外面还能照着旧链接下走"


def test_乱编的token拿不到东西(flask_app):
    assert flask_app.test_client().get("/s/" + "z" * 32).status_code == 404


def test_撤销后链接失效(auth_client, flask_app):
    a = _up(auth_client, "撤销.txt", "分享")
    d = auth_client.post("/api/drive/%d/share" % a["id"], json={}).get_json()
    sid = [s for s in auth_client.get("/api/drive/shares").get_json()["shares"]
           if s["token"] == d["token"]][0]["id"]
    auth_client.delete("/api/drive/shares/%d" % sid)
    assert flask_app.test_client().get(d["url"]).status_code == 404


def test_下载次数会累计(auth_client, flask_app):
    a = _up(auth_client, "计数.txt", "分享")
    d = auth_client.post("/api/drive/%d/share" % a["id"], json={}).get_json()
    anon = flask_app.test_client()
    anon.get(d["url"]); anon.get(d["url"])
    hit = [s for s in auth_client.get("/api/drive/shares").get_json()["shares"]
           if s["token"] == d["token"]][0]["hits"]
    assert hit == 2, "不记次数的话，用户不知道链接被谁下过几次"


def test_不能分享别人的文件(auth_client):
    assert auth_client.post("/api/drive/999999/share", json={}).status_code == 404


def test_分享文件夹拿到的是打包好的zip(auth_client, flask_app):
    """原来只给文件分享。契约改了：文件夹也能分享，对方拿到的是现打包的 zip。"""
    import zipfile
    _up(auth_client, "甲.txt", "分享夹/子层", "内容甲".encode())
    _up(auth_client, "乙.txt", "分享夹", "内容乙".encode())
    top = [i for i in auth_client.get("/api/drive").get_json()["items"]
           if i["name"] == "分享夹"][0]
    d = auth_client.post("/api/drive/%d/share" % top["id"], json={}).get_json()
    assert d["is_dir"] is True
    r = flask_app.test_client().get(d["url"])          # 未登录
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/zip")
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert sorted(names) == ["分享夹/乙.txt", "分享夹/子层/甲.txt"], names


def test_加了密码的链接要先输密码(auth_client, flask_app):
    a = _up(auth_client, "机密.txt", "带密码", "只有知道密码的人能看".encode())
    d = auth_client.post("/api/drive/%d/share" % a["id"],
                         json={"password": "kouling8"}).get_json()
    assert d["has_pw"] is True
    anon = flask_app.test_client()
    r = anon.get(d["url"])
    assert r.status_code == 200 and "访问密码" in r.get_data(as_text=True), "该出密码表单"
    assert b"\xe5\x8f\xaa\xe6\x9c\x89" not in r.data, "还没验密码就把内容吐出来了"
    assert anon.post(d["url"], data={"pw": "猜错的"}).status_code == 401
    r = anon.post(d["url"], data={"pw": "kouling8"})
    assert r.status_code == 200 and r.data == "只有知道密码的人能看".encode()


def test_密码不存明文(auth_client, flask_app):
    a = _up(auth_client, "查库.txt", "带密码")
    auth_client.post("/api/drive/%d/share" % a["id"], json={"password": "mingwen123"})
    with flask_app.app_context():
        from core import get_db
        row = get_db().execute("SELECT pw_hash FROM drive_shares WHERE pw_hash IS NOT NULL "
                               "ORDER BY id DESC LIMIT 1").fetchone()
    assert "mingwen123" not in (row["pw_hash"] or ""), "密码存成明文了"


def test_文件夹打包下载(auth_client):
    import zipfile
    _up(auth_client, "深.txt", "打包/里层", "深处内容".encode())
    _up(auth_client, "浅.txt", "打包", "浅处内容".encode())
    top = [i for i in auth_client.get("/api/drive").get_json()["items"]
           if i["name"] == "打包"][0]
    r = auth_client.get("/api/drive/%d/zip" % top["id"])
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["打包/浅.txt", "打包/里层/深.txt"]
    assert z.read("打包/里层/深.txt") == "深处内容".encode(), "打进去的内容不对"


def test_空文件夹打包给明确提示而不是空zip(auth_client):
    auth_client.post("/api/drive/folder", json={"name": "空夹", "parent": ""})
    top = [i for i in auth_client.get("/api/drive").get_json()["items"]
           if i["name"] == "空夹"][0]
    r = auth_client.get("/api/drive/%d/zip" % top["id"])
    assert r.status_code == 400 and "空的" in r.get_json()["error"]


def test_打包超过上限会被拦下(auth_client, monkeypatch):
    monkeypatch.setattr(social, "ZIP_MAX", 100)
    _up(auth_client, "大.bin", "超限打包", b"x" * 4096)
    top = [i for i in auth_client.get("/api/drive").get_json()["items"]
           if i["name"] == "超限打包"][0]
    assert auth_client.get("/api/drive/%d/zip" % top["id"]).status_code == 413


def test_不是文件夹不能打包(auth_client):
    a = _up(auth_client, "单文件.txt", "打包")
    assert auth_client.get("/api/drive/%d/zip" % a["id"]).status_code == 404


# ---- 缩略图 ----

_COLOR = [0]


def _png(client, name="图.png", folder="缩略图", px=600):
    """每次换个颜色 —— 内容相同会被去重成同一个 blob，多个测试就会互相牵连
    （删一个不删文件、缩略图被别人先生成好了…），前提全乱。"""
    from PIL import Image
    _COLOR[0] += 40
    buf = io.BytesIO()
    Image.new("RGB", (px, px), (_COLOR[0] % 255, 30, 30)).save(buf, "PNG")
    return _up(client, name, folder, buf.getvalue())


def test_图片能出缩略图且被缩小了(auth_client):
    from PIL import Image
    a = _png(auth_client)
    r = auth_client.get("/api/drive/%d/thumb" % a["id"])
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("image/jpeg")
    w, h = Image.open(io.BytesIO(r.data)).size
    assert max(w, h) == social.THUMB_PX, "没缩到 %d，网格视图会白下载原图" % social.THUMB_PX


def test_缩略图有缓存不会每次重算(auth_client):
    a = _png(auth_client, "缓存.png")
    auth_client.get("/api/drive/%d/thumb" % a["id"])
    cached = social._thumb_path(1, a["stored_name"])
    assert os.path.exists(cached), "没落缓存，每次列网格都要重新解码一遍大图"
    mtime = os.path.getmtime(cached)
    auth_client.get("/api/drive/%d/thumb" % a["id"])
    assert os.path.getmtime(cached) == mtime, "缓存还新着就重算了"


def test_源文件更新了缩略图要重算(auth_client):
    a = _png(auth_client, "会变.png")
    auth_client.get("/api/drive/%d/thumb" % a["id"])
    cached = social._thumb_path(1, a["stored_name"])
    os.utime(cached, (0, 0))                       # 假装缩略图比源文件旧
    auth_client.get("/api/drive/%d/thumb" % a["id"])
    assert os.path.getmtime(cached) > 0, "源文件比缩略图新，却没重算 —— 会一直显示旧图"


def test_非图片没有缩略图(auth_client):
    a = _up(auth_client, "文档.pdf", "缩略图")
    assert auth_client.get("/api/drive/%d/thumb" % a["id"]).status_code == 404


def test_删文件时缩略图缓存一起清掉(auth_client):
    a = _png(auth_client, "要删的.png")
    auth_client.get("/api/drive/%d/thumb" % a["id"])
    cached = social._thumb_path(1, a["stored_name"])
    assert os.path.exists(cached)
    auth_client.delete("/api/drive/%d" % a["id"])
    auth_client.delete("/api/drive/trash/%d" % a["id"])
    assert not os.path.exists(cached), "缩略图缓存留在磁盘上，和之前那个 .pdf 泄漏一模一样"


def test_打包下载不会在磁盘上留临时zip(auth_client):
    """原来靠 resp.call_on_close 挂回调删临时文件，实测回调根本没触发 ——
    每下一次就留一个几百 MB 的 .tmp_zip_。现在改成先 unlink 再发。"""
    _up(auth_client, "留痕.txt", "查残留", b"x" * 2048)
    top = [i for i in auth_client.get("/api/drive").get_json()["items"]
           if i["name"] == "查残留"][0]
    for _ in range(3):
        assert auth_client.get("/api/drive/%d/zip" % top["id"]).status_code == 200
    left = [f for f in os.listdir(social._drive_dir(1)) if f.startswith(".tmp_zip_")]
    assert not left, "下了 3 次留下 %d 个临时 zip：%s" % (len(left), left)
