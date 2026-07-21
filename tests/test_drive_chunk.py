"""云盘 P2：分片上传（断点续传）与按内容去重（秒传）。

分片是为了绕开 Cloudflare 隧道 100MB 的请求体硬上限 —— 单请求再怎么放宽
max_content_length 都没用，只能切块分多次送；顺带换来断点续传。

去重带来一个新的、很容易漏的风险：**多行共用一个 stored_name**。删其中一行时若照旧
无条件 os.remove，另一行的文件也没了 —— 那一行还在列表里好好显示着，点开却 404。
下面专门盯这件事。
"""
import hashlib
import io
import os

from mods import social


def _up(client, name, folder="", data=b"x"):
    r = client.post("/api/drive", data={"file": (io.BytesIO(data), name), "folder": folder},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()


def _ls(client, folder=""):
    return client.get("/api/drive", query_string={"folder": folder}).get_json()


def _blob_path(row):
    return os.path.join(social._drive_dir(1), row["stored_name"])


# ---- 去重 ----

def test_同样内容传两次磁盘上只存一份(auth_client):
    a = _up(auth_client, "甲.bin", "去重", "完全一样的内容".encode())
    b = _up(auth_client, "乙.bin", "去重", "完全一样的内容".encode())
    assert a["stored_name"] == b["stored_name"], "内容相同却存了两份，白占磁盘"
    assert a["id"] != b["id"], "去重不该把两条记录合成一条 —— 用户传的是两个文件"
    assert a["sha256"] == b["sha256"]


def test_内容不同不会被误判成同一份(auth_client):
    a = _up(auth_client, "甲.bin", "不去重", "内容一".encode())
    b = _up(auth_client, "乙.bin", "不去重", "内容二".encode())
    assert a["stored_name"] != b["stored_name"]


def _wipe(client, fid):
    """彻底删掉：删除只是进回收站（软删），要再清一次才真从磁盘上抹掉。"""
    assert client.delete("/api/drive/%d" % fid).status_code == 200
    assert client.delete("/api/drive/trash/%d" % fid).status_code == 200


def test_删掉共用同一份内容的一行不会带走另一行的文件(auth_client):
    """去重最危险的副作用。彻底清掉 b 之后，a 必须还打得开。"""
    a = _up(auth_client, "留下.bin", "共用", "共用的内容".encode())
    b = _up(auth_client, "删掉.bin", "共用", "共用的内容".encode())
    assert a["stored_name"] == b["stored_name"]
    _wipe(auth_client, b["id"])
    assert os.path.exists(_blob_path(a)), "另一行的磁盘文件被带走了"
    assert auth_client.get("/api/drive/%d/download" % a["id"]).status_code == 200


def test_进回收站时磁盘文件先留着(auth_client):
    a = _up(auth_client, "先留着.bin", "软删", "还能后悔".encode())
    auth_client.delete("/api/drive/%d" % a["id"])
    assert os.path.exists(_blob_path(a)), "软删就把文件删了，回收站里的东西恢复不出来"


def test_最后一行彻底清掉后磁盘文件才真的删(auth_client):
    a = _up(auth_client, "独一份.bin", "独占", "只有我用这份内容".encode())
    p = _blob_path(a)
    assert os.path.exists(p)
    _wipe(auth_client, a["id"])
    assert not os.path.exists(p), "没人引用了还留着，磁盘会越用越多"


def test_配额按去重后的实际占用算(auth_client):
    before = _ls(auth_client)["used"]
    _up(auth_client, "配额甲.bin", "配额", b"z" * 5000)
    mid = _ls(auth_client)["used"]
    _up(auth_client, "配额乙.bin", "配额", b"z" * 5000)      # 同内容，不该再涨
    after = _ls(auth_client)["used"]
    assert mid - before == 5000
    assert after == mid, "同一份内容占了两次配额"


# ---- 秒传 ----

def test_秒传命中就不用传内容(auth_client):
    body = "这份内容服务端已经有了".encode()
    _up(auth_client, "原件.bin", "秒传", body)
    digest = hashlib.sha256(body).hexdigest()
    r = auth_client.post("/api/drive/instant",
                         json={"sha256": digest, "name": "副本.bin", "folder": "秒传目标"})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    d = r.get_json()
    assert d["hit"] is True and d["size"] == len(body)
    assert [i["name"] for i in _ls(auth_client, "秒传目标")["items"]] == ["副本.bin"]
    # 秒传出来的那份要真能下下来（指向的是原件那个 blob）
    assert auth_client.get("/api/drive/%d/download" % d["id"]).data == body


def test_秒传没命中如实返回(auth_client):
    r = auth_client.post("/api/drive/instant", json={
        "sha256": "0" * 64, "name": "没有的.bin", "folder": ""})
    assert r.status_code == 200 and r.get_json()["hit"] is False


def test_秒传拒绝乱来的哈希(auth_client):
    assert auth_client.post("/api/drive/instant", json={"sha256": "abc", "name": "x"}).status_code == 400


# ---- 分片上传 ----

def _chunked(client, name, body, folder="", chunk=8):
    r = client.post("/api/drive/chunk/init",
                    json={"name": name, "size": len(body), "folder": folder})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    up = r.get_json()["upload_id"]
    parts = [body[i:i + chunk] for i in range(0, len(body), chunk)]
    for i, p in enumerate(parts):
        r = client.post("/api/drive/chunk/%s/%d" % (up, i), data=p,
                        content_type="application/octet-stream")
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return up, parts


def test_分片上传拼回原文(auth_client):
    body = bytes(range(256)) * 5
    up, parts = _chunked(auth_client, "大片.bin", body, "分片")
    r = auth_client.post("/api/drive/chunk/%s/done" % up)
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    row = r.get_json()
    assert row["size"] == len(body)
    got = auth_client.get("/api/drive/%d/download" % row["id"]).data
    assert got == body, "拼出来的内容和原文不一致"


def test_分片可以断点续传(auth_client):
    body = b"0123456789" * 6
    r = auth_client.post("/api/drive/chunk/init", json={"name": "断点.bin", "size": len(body)})
    up = r.get_json()["upload_id"]
    parts = [body[i:i + 10] for i in range(0, len(body), 10)]
    for i in (0, 1, 2):                       # 只传前三块，假装断了
        auth_client.post("/api/drive/chunk/%s/%d" % (up, i), data=parts[i],
                         content_type="application/octet-stream")
    got = auth_client.get("/api/drive/chunk/%s" % up).get_json()["received"]
    assert got == [0, 1, 2], "问不出已经收到哪些块，就没法接着传"
    for i in (3, 4, 5):                       # 接着传剩下的
        auth_client.post("/api/drive/chunk/%s/%d" % (up, i), data=parts[i],
                         content_type="application/octet-stream")
    row = auth_client.post("/api/drive/chunk/%s/done" % up).get_json()
    assert auth_client.get("/api/drive/%d/download" % row["id"]).data == body


def test_缺块时拒绝入库而不是存半个文件(auth_client):
    body = b"abcdefghij" * 4
    r = auth_client.post("/api/drive/chunk/init", json={"name": "缺块.bin", "size": len(body)})
    up = r.get_json()["upload_id"]
    for i in (0, 2):                          # 故意跳过第 1 块
        auth_client.post("/api/drive/chunk/%s/%d" % (up, i), data=body[i * 10:(i + 1) * 10],
                         content_type="application/octet-stream")
    r = auth_client.post("/api/drive/chunk/%s/done" % up)
    assert r.status_code == 400, "缺块也入库了，用户会拿到一个坏文件"


def test_大小对不上时拒绝入库(auth_client):
    r = auth_client.post("/api/drive/chunk/init", json={"name": "短了.bin", "size": 999})
    up = r.get_json()["upload_id"]
    auth_client.post("/api/drive/chunk/%s/0" % up, data="就这几个字节".encode(),
                     content_type="application/octet-stream")
    assert auth_client.post("/api/drive/chunk/%s/done" % up).status_code == 400


def test_分片上传也走去重(auth_client):
    body = "分片和单发共用同一条入库路径".encode()
    single = _up(auth_client, "单发.bin", "分片去重", body)
    up, _ = _chunked(auth_client, "分片.bin", body, "分片去重")
    row = auth_client.post("/api/drive/chunk/%s/done" % up).get_json()
    assert row["stored_name"] == single["stored_name"], "分片那条没走去重"


def test_乱编的会话id拿不到东西(auth_client):
    # upload_id 来自 URL，不校验就能用 ../ 跳出自己的目录
    assert auth_client.get("/api/drive/chunk/../../etc").status_code in (404, 308)
    assert auth_client.post("/api/drive/chunk/zzz/done").status_code == 404
