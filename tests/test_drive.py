"""云盘：请求体上限 / 配额 / 传文件夹时自动补建中间目录。

这块以前有个对不上的坑：mods/social.py 写着单文件 200MB，app.py 的
MAX_CONTENT_LENGTH 却是 64MB —— 超过 64MB 的文件在进到视图函数之前就被 Flask
413 掉了，前端还照着「200MB」提示，表现出来就是「云盘传不了大文件」且报错莫名其妙。
两个数字分在两个文件里，是迟早还会再走散的那种坑，所以这里钉死三件事：

1. 放宽只对「收文件」的路生效，别的接口仍受全局 64MB 保护；
2. 配额是真的会拦，不是算出来给人看的；
3. 传文件夹时中间目录必须在库里补出来 —— 否则文件的 folder 指向一个列表里看不见的
   目录，传上去了但用户点不进去，等于传丢了。
"""
import io

from flask import request

from mods import social


def _up(client, name, folder="", data=b"x"):
    return client.post("/api/drive", data={
        "file": (io.BytesIO(data), name), "folder": folder,
    }, content_type="multipart/form-data")


def _ls(client, folder=""):
    return client.get("/api/drive", query_string={"folder": folder}).get_json()


def test_上传后能在当前目录列出来(auth_client):
    r = _up(auth_client, "a.txt")
    assert r.status_code == 201, r.get_data(as_text=True)
    assert any(it["name"] == "a.txt" for it in _ls(auth_client)["items"])


def test_列目录带出配额和单文件上限(auth_client):
    # 前端拿它显示「已用 x / y」，少了就只剩「已用」，用户不知道还剩多少
    d = _ls(auth_client)
    assert d["quota"] == social.DRIVE_QUOTA
    assert d["max_file"] == social.DRIVE_MAX


def test_传文件夹逐级补出中间目录(auth_client):
    assert _up(auth_client, "p.jpg", folder="照片/2024/春").status_code == 201
    root = _ls(auth_client)
    assert any(it["name"] == "照片" and it["is_dir"] for it in root["items"]), "根目录下看不见「照片」"
    mid = _ls(auth_client, "照片")
    assert any(it["name"] == "2024" and it["is_dir"] for it in mid["items"]), "中间那层没补出来"
    leaf = _ls(auth_client, "照片/2024/春")
    assert [it["name"] for it in leaf["items"] if not it["is_dir"]] == ["p.jpg"]


def test_同一子目录传两次不会建出两个同名文件夹(auth_client):
    _up(auth_client, "1.txt", folder="重复/子")
    _up(auth_client, "2.txt", folder="重复/子")
    assert len([it for it in _ls(auth_client)["items"] if it["name"] == "重复"]) == 1
    assert len(_ls(auth_client, "重复/子")["items"]) == 2


def test_超过配额会被拦下(auth_client, monkeypatch):
    monkeypatch.setattr(social, "DRIVE_QUOTA", 10)          # 配额压到 10 字节
    r = _up(auth_client, "big.bin", data=b"y" * 64)
    assert r.status_code == 400
    assert "空间不足" in r.get_json()["error"]


def test_单文件超上限会被拦下(auth_client, monkeypatch):
    monkeypatch.setattr(social, "DRIVE_MAX", 16)
    r = _up(auth_client, "big.bin", data=b"y" * 64)
    assert r.status_code == 400
    assert "超过" in r.get_json()["error"]


def test_云盘的请求体上限高于全局而别的接口不变(flask_app):
    """治「传不了大文件」的正是这一条：/api/drive 用 DRIVE_MAX，不是全局那 64MB。"""
    assert flask_app.config["MAX_CONTENT_LENGTH"] == 64 * 1024 * 1024, \
        "全局上限被改大了 —— 那等于给所有接口都开了口子，放宽该只在 social 里按请求做"
    with flask_app.test_request_context("/api/drive", method="POST"):
        social._relax_body_limit()
        assert request.max_content_length >= social.DRIVE_MAX
        assert request.max_content_length > flask_app.config["MAX_CONTENT_LENGTH"]
    with flask_app.test_request_context("/api/friends/request", method="POST"):
        social._relax_body_limit()
        assert request.max_content_length == flask_app.config["MAX_CONTENT_LENGTH"], \
            "非收文件的接口不该被放宽"


def test_文件名里的路径会被剥掉(auth_client):
    # 客户端可能把相对路径塞进 filename，落库只留基名，免得下载名带出路径
    r = _up(auth_client, "../../etc/passwd")
    assert r.status_code == 201
    assert r.get_json()["name"] == "passwd"
