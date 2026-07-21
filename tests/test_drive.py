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


def _mk(client, name, folder="", data=b"x"):
    """传一个文件，返回它的 id。"""
    r = _up(client, name, folder, data)
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()["id"]


# ---- 预览 ----

def test_预览是内联返回而不是下载(auth_client):
    fid = _mk(auth_client, "读我.txt", folder="预览", data="正文内容".encode())
    r = auth_client.get("/api/drive/%d/view" % fid)
    assert r.status_code == 200
    # download 那条是 attachment；预览这条必须 inline，否则点开就变成下载
    assert "attachment" not in (r.headers.get("Content-Disposition") or "")


def test_预览给上传的HTML关进沙箱(auth_client):
    """云盘什么都收，.html 内联返回时必须挡住脚本 —— 否则等于在本站源上执行别人的代码。"""
    fid = _mk(auth_client, "坏.html", folder="预览", data=b"<script>alert(1)</script>")
    r = auth_client.get("/api/drive/%d/view" % fid)
    assert r.status_code == 200
    assert "sandbox" in (r.headers.get("Content-Security-Policy") or ""), "缺 CSP sandbox"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_预览不支持的格式返回415而不是硬塞给浏览器(auth_client):
    fid = _mk(auth_client, "装.exe", folder="预览")
    r = auth_client.get("/api/drive/%d/view" % fid)
    assert r.status_code == 415


def test_预览取纯文字供阅读模式用(auth_client):
    fid = _mk(auth_client, "文.txt", folder="预览", data="给定资料一".encode())
    d = auth_client.get("/api/drive/%d/view?text=1" % fid).get_json()
    assert "给定资料一" in d["text"]


def test_列目录标出哪些能预览(auth_client):
    _mk(auth_client, "图.png", folder="可预览")
    _mk(auth_client, "包.apk", folder="可预览")
    items = {i["name"]: i["viewable"] for i in _ls(auth_client, "可预览")["items"]}
    assert items["图.png"] is True
    assert items["包.apk"] is False


# ---- 重命名 / 移动 ----

def test_重命名文件(auth_client):
    fid = _mk(auth_client, "旧名.txt", folder="改名")
    r = auth_client.patch("/api/drive/%d" % fid, json={"name": "新名.txt"})
    assert r.status_code == 200
    assert [i["name"] for i in _ls(auth_client, "改名")["items"]] == ["新名.txt"]


def test_移动文件到别的目录(auth_client):
    fid = _mk(auth_client, "搬.txt", folder="甲")
    assert auth_client.patch("/api/drive/%d" % fid, json={"folder": "乙/丙"}).status_code == 200
    assert [i["name"] for i in _ls(auth_client, "甲")["items"]] == []
    assert [i["name"] for i in _ls(auth_client, "乙/丙")["items"]] == ["搬.txt"]


def test_重命名文件夹时子孙跟着走(auth_client):
    """最容易静默丢数据的一条：folder 只是字符串，改了父目录名而不改子孙前缀，
    子孙就既不在旧目录也不在新目录 —— 文件还在库里，但界面上凭空消失。"""
    _mk(auth_client, "深.txt", folder="老名/子/孙")
    top = [i for i in _ls(auth_client)["items"] if i["name"] == "老名"][0]
    assert auth_client.patch("/api/drive/%d" % top["id"], json={"name": "新名"}).status_code == 200
    assert [i["name"] for i in _ls(auth_client, "新名/子/孙")["items"]] == ["深.txt"]
    assert _ls(auth_client, "老名/子/孙")["items"] == [], "旧路径下还留着东西"


def test_移动文件夹时子孙跟着走(auth_client):
    _mk(auth_client, "里.txt", folder="待搬/内层")
    top = [i for i in _ls(auth_client)["items"] if i["name"] == "待搬"][0]
    assert auth_client.patch("/api/drive/%d" % top["id"], json={"folder": "归档"}).status_code == 200
    assert [i["name"] for i in _ls(auth_client, "归档/待搬/内层")["items"]] == ["里.txt"]


def test_不能把文件夹移进它自己里面(auth_client):
    _mk(auth_client, "x.txt", folder="自套/下层")
    top = [i for i in _ls(auth_client)["items"] if i["name"] == "自套"][0]
    r = auth_client.patch("/api/drive/%d" % top["id"], json={"folder": "自套/下层"})
    assert r.status_code == 400, "移进自己会把整棵子树挂到自己底下，列表里直接消失"


def test_同名冲突会被拦下(auth_client):
    _mk(auth_client, "占位.txt", folder="撞名")
    fid = _mk(auth_client, "另一个.txt", folder="撞名")
    r = auth_client.patch("/api/drive/%d" % fid, json={"name": "占位.txt"})
    assert r.status_code == 400 and "同名" in r.get_json()["error"]


# ---- 搜索 / 排序 / 目录清单 ----

def test_搜索是全盘找不分目录(auth_client):
    _mk(auth_client, "唯一关键词甲.txt", folder="搜/深处")
    d = auth_client.get("/api/drive", query_string={"q": "唯一关键词甲"}).get_json()
    assert [i["name"] for i in d["items"]] == ["唯一关键词甲.txt"]
    assert d["items"][0]["folder"] == "搜/深处", "搜索结果要带 folder，否则不知道文件在哪"


def test_搜索里的下划线百分号当普通字符(auth_client):
    # LIKE 的通配符没转义的话，搜 "a_c" 会连 abc 一起搜出来
    _mk(auth_client, "a_c.txt", folder="转义")
    _mk(auth_client, "abc.txt", folder="转义")
    names = [i["name"] for i in auth_client.get(
        "/api/drive", query_string={"q": "a_c"}).get_json()["items"]]
    assert names == ["a_c.txt"], names


def test_排序按名字和大小(auth_client):
    _mk(auth_client, "b.bin", folder="排序", data=b"x" * 30)
    _mk(auth_client, "a.bin", folder="排序", data=b"x" * 10)
    by_name = auth_client.get("/api/drive", query_string={"folder": "排序", "sort": "name"}).get_json()
    assert [i["name"] for i in by_name["items"]] == ["a.bin", "b.bin"]
    by_big = auth_client.get("/api/drive", query_string={"folder": "排序", "sort": "big"}).get_json()
    assert [i["name"] for i in by_big["items"]] == ["b.bin", "a.bin"]


def test_乱传的sort值退回默认而不是拼进SQL(auth_client):
    r = auth_client.get("/api/drive", query_string={"sort": "id; DROP TABLE drive_files--"})
    assert r.status_code == 200
    assert auth_client.get("/api/drive").status_code == 200, "表还在"


def test_目录清单给移动用(auth_client):
    _mk(auth_client, "t.txt", folder="清单甲/清单乙")
    folders = auth_client.get("/api/drive/folders").get_json()["folders"]
    assert "清单甲" in folders and "清单甲/清单乙" in folders


def test_文件名里的路径会被剥掉(auth_client):
    # 客户端可能把相对路径塞进 filename，落库只留基名，免得下载名带出路径
    r = _up(auth_client, "../../etc/passwd")
    assert r.status_code == 201
    assert r.get_json()["name"] == "passwd"


# ---- 复制（右键「复制/粘贴」用） ----

def test_复制到别的目录内容共用不占额外磁盘(auth_client):
    a = _mk(auth_client, "原件.bin", folder="复制源", data=b"y" * 2048)
    before = _ls(auth_client)["used"]
    r = auth_client.post("/api/drive/%d/copy" % a, json={"folder": "复制目标"})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    assert [i["name"] for i in _ls(auth_client, "复制目标")["items"]] == ["原件.bin"]
    assert _ls(auth_client)["used"] == before, "复制吃了配额 —— 内容明明是共用的"


def test_复制到同一个目录自动改名而不是报错(auth_client):
    a = _mk(auth_client, "就地.txt", folder="就地复制")
    assert auth_client.post("/api/drive/%d/copy" % a, json={"folder": "就地复制"}).status_code == 201
    names = sorted(i["name"] for i in _ls(auth_client, "就地复制")["items"])
    assert names == ["就地 副本.txt", "就地.txt"], names


def test_复制文件夹连子孙一起复制(auth_client):
    _mk(auth_client, "深文件.txt", folder="待复制/内层")
    top = [i for i in _ls(auth_client)["items"] if i["name"] == "待复制"][0]["id"]
    assert auth_client.post("/api/drive/%d/copy" % top, json={"folder": "存档"}).status_code == 201
    assert [i["name"] for i in _ls(auth_client, "存档/待复制/内层")["items"]] == ["深文件.txt"]
    # 原件必须原封不动（复制不是移动）
    assert [i["name"] for i in _ls(auth_client, "待复制/内层")["items"]] == ["深文件.txt"]


def test_不能把文件夹复制进它自己里面(auth_client):
    _mk(auth_client, "x.txt", folder="自我复制/下层")
    top = [i for i in _ls(auth_client)["items"] if i["name"] == "自我复制"][0]["id"]
    r = auth_client.post("/api/drive/%d/copy" % top, json={"folder": "自我复制/下层"})
    assert r.status_code == 400


def test_复制出来的那份能独立删除(auth_client):
    """复制共用 blob，所以删副本绝不能把原件的文件带走。"""
    a = _mk(auth_client, "共享.bin", folder="独立删", data=b"w" * 999)
    auth_client.post("/api/drive/%d/copy" % a, json={"folder": "独立删2"})
    cid = _ls(auth_client, "独立删2")["items"][0]["id"]
    auth_client.delete("/api/drive/%d" % cid)
    auth_client.delete("/api/drive/trash/%d" % cid)
    assert auth_client.get("/api/drive/%d/download" % a).status_code == 200, "原件被副本的删除带坏了"
