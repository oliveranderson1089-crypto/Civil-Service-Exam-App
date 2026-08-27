"""全局搜索要能搜到云盘。

以前顶栏那个搜索（/api/search）跨了十几个库，唯独漏了云盘 —— 云盘自己有一个
按文件名的搜索框，于是「传上去的讲义」只有走进云盘才找得到，从全局搜索里搜
永远是「没有匹配」。这里钉三件事：

1. 文件名/文件夹名能搜到，结果带 folder（前端靠它先落到那一层再开文件）；
2. 文本类文件的**内容**也搜得到 —— 记不住文件叫什么、只记得里面写了什么，
   正是最需要全局搜索的时候；
3. 回收站里的不算数：删掉的东西不该在搜索结果里诈尸。
"""
import io


def _up(client, name, folder="", data=b"x"):
    return client.post("/api/drive", data={
        "file": (io.BytesIO(data), name), "folder": folder,
    }, content_type="multipart/form-data")


def _search(client, q):
    d = client.get("/api/search", query_string={"q": q}).get_json()
    return [r for r in d["results"] if r["type"] == "drive"]


def test_按文件名搜得到并带出所在目录(auth_client):
    auth_client.post("/api/drive/folder", json={"folder": "", "name": "讲义"})
    _up(auth_client, "行测速算技巧.pdf", folder="讲义")
    hits = _search(auth_client, "速算技巧")
    assert hits, "云盘里的文件没进全局搜索"
    assert hits[0]["title"] == "行测速算技巧.pdf"
    assert hits[0]["folder"] == "讲义"
    assert hits[0]["viewable"] is True
    assert "云盘" in hits[0]["board"]


def test_搜得到文件夹本身(auth_client):
    auth_client.post("/api/drive/folder", json={"folder": "", "name": "申论批改存档"})
    hits = _search(auth_client, "申论批改存档")
    assert any(h["is_dir"] and h["path"] == "申论批改存档" for h in hits)


def test_文本文件的内容也搜得到(auth_client):
    _up(auth_client, "随手记.txt", data="狮子山下的公共服务均等化".encode())
    hits = _search(auth_client, "公共服务均等化")
    assert hits, "文件名对不上时，内容没被搜到"
    assert hits[0]["title"] == "随手记.txt"
    assert "公共服务均等化" in hits[0]["snippet"]


def test_删进回收站的不再出现在搜索里(auth_client):
    r = _up(auth_client, "作废的模拟卷.docx")
    fid = r.get_json()["id"]
    assert _search(auth_client, "作废的模拟卷")
    auth_client.delete("/api/drive/%d" % fid)
    assert not _search(auth_client, "作废的模拟卷")
