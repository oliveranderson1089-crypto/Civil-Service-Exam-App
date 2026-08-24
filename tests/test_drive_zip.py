"""云盘多选打包下载 /api/drive/zip?ids=…

原来只有「一个文件夹打包」和「一个文件下载」，选中十几张证件照就只能一张张点 ——
这条路是给多选用的。三件事必须钉死：

1. 文件和文件夹混着选也能打成一个包，文件夹里的层级要在 zip 里保住；
2. 重名要改名，不能覆盖 —— 搜索结果里同名文件来自不同目录是常事，
   zipfile 遇到同名只会闷头写两条，解压时后一条盖掉前一条，那是**丢文件**；
3. 别人的 id 混进来也拿不到东西（ids 是 URL 里来的，谁都能改）。
"""
import io
import zipfile


def _up(client, name, folder="", data=b"xyz"):
    return client.post("/api/drive", data={
        "file": (io.BytesIO(data), name), "folder": folder,
    }, content_type="multipart/form-data")


def _ids(client, folder=""):
    d = client.get("/api/drive", query_string={"folder": folder}).get_json()
    return {it["name"]: it["id"] for it in d["items"]}


def _zip(client, ids):
    return client.get("/api/drive/zip", query_string={"ids": ",".join(str(i) for i in ids)})


def test_混选文件和文件夹打成一个包(auth_client):
    _up(auth_client, "单张.jpg", data=b"a" * 10)
    _up(auth_client, "里面的.txt", folder="材料/证件", data=b"b" * 10)
    ids = _ids(auth_client)
    r = _zip(auth_client, [ids["单张.jpg"], ids["材料"]])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["Content-Type"].startswith("application/zip")
    names = set(zipfile.ZipFile(io.BytesIO(r.data)).namelist())
    # 文件夹进包时要连着它自己的名字和里面的层级，不能摊平
    assert names == {"单张.jpg", "材料/证件/里面的.txt"}, names


def test_同名文件改名而不是互相覆盖(auth_client):
    _up(auth_client, "证书.jpg", folder="甲", data=b"1" * 10)
    _up(auth_client, "证书.jpg", folder="乙", data=b"2" * 20)
    ids = {}
    for f in ("甲", "乙"):
        ids[f] = _ids(auth_client, f)["证书.jpg"]
    r = _zip(auth_client, [ids["甲"], ids["乙"]])
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["证书(2).jpg", "证书.jpg"], z.namelist()
    # 两份内容都在，没有一份被顶掉
    assert {len(z.read(n)) for n in z.namelist()} == {10, 20}


def test_单个文件夹时用文件夹名当包名(auth_client):
    _up(auth_client, "x.txt", folder="讲义", data=b"z")
    r = _zip(auth_client, [_ids(auth_client)["讲义"]])
    assert "讲义.zip" in r.headers["Content-Disposition"] or \
        "%E8%AE%B2%E4%B9%89" in r.headers["Content-Disposition"]


def test_别人的文件混进来也拿不到(auth_client, flask_app):
    _up(auth_client, "我的.txt", data=b"m")
    mine = _ids(auth_client)["我的.txt"]
    with flask_app.app_context():
        from core import get_db
        db = get_db()
        cur = db.execute(
            "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
            "VALUES(999,'','别人的.txt','nope.txt','.txt','text/plain',3,0,'drive')")
        db.commit()
        other = cur.lastrowid
    r = _zip(auth_client, [mine, other])
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert names == ["我的.txt"], names


def test_没给id就明确报错(auth_client):
    assert auth_client.get("/api/drive/zip", query_string={"ids": ""}).status_code == 400


def test_预检只算账不打包(auth_client):
    """点「下载」前先问一句这一包多大。

    浏览器点 <a download> 碰上 JSON 错误响应是**静默不动**的 —— 超限、文件没了，
    用户看到的都是「点了没反应」。预检把这两种情况变成一句看得懂的话。
    """
    _up(auth_client, "甲.txt", folder="预检", data=b"a" * 100)
    _up(auth_client, "乙.txt", folder="预检", data=b"b" * 300)
    r = auth_client.get("/api/drive/zip", query_string={
        "check": "1", "ids": str(_ids(auth_client)["预检"])})
    assert r.status_code == 200
    assert r.get_json() == {"files": 2, "size": 400}
    assert not r.headers.get("Content-Disposition"), "预检不该真发一个 zip 下来"


def test_预检也会拦超限(auth_client, monkeypatch):
    from mods import social
    monkeypatch.setattr(social, "ZIP_MAX", 10)
    _up(auth_client, "胖.bin", folder="超限", data=b"x" * 50)
    r = auth_client.get("/api/drive/zip", query_string={
        "check": "1", "ids": str(_ids(auth_client)["超限"])})
    assert r.status_code == 413
    assert "打包上限" in r.get_json()["error"]


def test_预检说空文件夹也给得出话(auth_client):
    r = auth_client.post("/api/drive/folder", json={"folder": "", "name": "空的"})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    r = auth_client.get("/api/drive/zip",
                        query_string={"check": "1", "ids": str(_ids(auth_client)["空的"])})
    assert r.status_code == 400
    assert "空文件夹" in r.get_json()["error"]
