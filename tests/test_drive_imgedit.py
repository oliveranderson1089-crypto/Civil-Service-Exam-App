"""图片编辑写回：覆盖原图 / 另存副本。

最要命的一条在 test_覆盖共用同一份内容的图不会殃及旁边那行：
云盘做了去重，秒传来的、复制出来的多行**共用一个 stored_name**。要是照直觉把新字节
写回老文件，用户只编辑了一张，云盘里另外几处会跟着一起变 —— 而且没有任何提示。
所以 replace 永远写新 blob、只把这一行指过去。
"""
import io
import os


def _up(client, name, folder="", data=b"fakejpegbytes"):
    return client.post("/api/drive", data={
        "file": (io.BytesIO(data), name), "folder": folder,
    }, content_type="multipart/form-data")


def _ls(client, folder=""):
    return client.get("/api/drive", query_string={"folder": folder}).get_json()["items"]


def _one(client, name, folder=""):
    return next(it for it in _ls(client, folder) if it["name"] == name)


NEW = b"\xff\xd8edited-image-bytes"


def test_另存副本原图一个字节不动(auth_client):
    _up(auth_client, "证件.jpg", folder="改图", data=b"original-bytes")
    old = _one(auth_client, "证件.jpg", "改图")
    r = auth_client.post("/api/drive/%d/saveas?name=%s" % (old["id"], "证件-编辑.jpg"),
                         data=NEW, content_type="image/jpeg")
    assert r.status_code == 201, r.get_data(as_text=True)
    new = r.get_json()
    assert new["folder"] == "改图", "副本要落在原图旁边，不是丢到根目录"
    assert new["id"] != old["id"]
    # 原图还是原样
    assert auth_client.get("/api/drive/%d/download" % old["id"]).data == b"original-bytes"
    assert auth_client.get("/api/drive/%d/download" % new["id"]).data == NEW


def test_覆盖原图换的是内容不是记录(auth_client):
    _up(auth_client, "覆盖我.jpg", folder="改图2", data=b"before")
    it = _one(auth_client, "覆盖我.jpg", "改图2")
    r = auth_client.post("/api/drive/%d/replace" % it["id"], data=NEW,
                         content_type="image/jpeg")
    assert r.status_code == 200, r.get_data(as_text=True)
    after = r.get_json()
    assert after["id"] == it["id"], "覆盖是改这一行的内容，不是新建一行"
    assert after["size"] == len(NEW)
    assert auth_client.get("/api/drive/%d/download" % it["id"]).data == NEW
    # 目录里还是只有一份，没多出来
    assert len([x for x in _ls(auth_client, "改图2") if x["name"] == "覆盖我.jpg"]) == 1


def test_覆盖共用同一份内容的图不会殃及旁边那行(auth_client, flask_app):
    """秒传/复制会让两行指向同一个 blob。改其中一行，另一行必须纹丝不动。"""
    same = b"same-content-uploaded-twice"
    _up(auth_client, "甲.jpg", folder="共用", data=same)
    _up(auth_client, "乙.jpg", folder="共用", data=same)
    a, b = _one(auth_client, "甲.jpg", "共用"), _one(auth_client, "乙.jpg", "共用")
    with flask_app.app_context():
        from core import get_db
        rows = get_db().execute(
            "SELECT id, stored_name FROM drive_files WHERE id IN (?,?)", (a["id"], b["id"])).fetchall()
    assert len({r["stored_name"] for r in rows}) == 1, "前提没成立：这两行本该共用一个 blob"

    r = auth_client.post("/api/drive/%d/replace" % a["id"], data=NEW, content_type="image/jpeg")
    assert r.status_code == 200
    assert auth_client.get("/api/drive/%d/download" % a["id"]).data == NEW
    assert auth_client.get("/api/drive/%d/download" % b["id"]).data == same, \
        "另一行被连累了 —— 用户只编辑了一张，云盘里另一张也变了"


def test_旧内容没人用了就该从磁盘上消失(auth_client, flask_app):
    _up(auth_client, "独苗.jpg", folder="回收", data=b"lonely-bytes")
    it = _one(auth_client, "独苗.jpg", "回收")
    with flask_app.app_context():
        from core import get_db
        from mods.social import _drive_dir
        old_stored = get_db().execute("SELECT stored_name FROM drive_files WHERE id=?",
                                      (it["id"],)).fetchone()["stored_name"]
        old_path = os.path.join(_drive_dir(1), old_stored)
        assert os.path.exists(old_path)
    auth_client.post("/api/drive/%d/replace" % it["id"], data=NEW, content_type="image/jpeg")
    assert not os.path.exists(old_path), "没人再引用的老内容留在磁盘上 = 白占配额"


def test_改不动的格式当场拒绝(auth_client):
    _up(auth_client, "讲义.pdf", folder="拒", data=b"%PDF-1.4")
    it = _one(auth_client, "讲义.pdf", "拒")
    r = auth_client.post("/api/drive/%d/replace" % it["id"], data=NEW, content_type="image/jpeg")
    assert r.status_code == 400
    assert "改不了" in r.get_json()["error"]


def test_空内容不算一次编辑(auth_client):
    _up(auth_client, "空.jpg", folder="空", data=b"x")
    it = _one(auth_client, "空.jpg", "空")
    r = auth_client.post("/api/drive/%d/replace" % it["id"], data=b"", content_type="image/jpeg")
    assert r.status_code == 400
    assert auth_client.get("/api/drive/%d/download" % it["id"]).data == b"x"


def test_别人的图改不了(auth_client, flask_app):
    with flask_app.app_context():
        from core import get_db
        db = get_db()
        cur = db.execute(
            "INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,is_dir,source) "
            "VALUES(999,'','别人的.jpg','x.jpg','.jpg','image/jpeg',3,0,'drive')")
        db.commit()
        other = cur.lastrowid
    for path in ("replace", "saveas"):
        r = auth_client.post("/api/drive/%d/%s" % (other, path), data=NEW,
                             content_type="image/jpeg")
        assert r.status_code == 404, path
