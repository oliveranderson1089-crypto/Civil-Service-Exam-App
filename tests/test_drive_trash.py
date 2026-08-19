"""云盘回收站：删除改成软删，能后悔。

删错文件是最不可逆的操作，原来 DELETE 一按文件当场从磁盘上消失。改成打个
deleted_at 时间戳，过 N 天或手动清空才真抹掉。

配套要盯的两件事：
1. **凡是列文件的地方都得带 deleted_at IS NULL** —— 漏一处，回收站里的东西就漏回
   列表里，看着像没删掉；
2. 恢复文件夹时只该捞回「跟它一起删的那批」，不能把之前单独删进回收站的也一并捞回来。
"""
import io
import os

from mods import social


def _up(client, name, folder="", data=b"x"):
    r = client.post("/api/drive", data={"file": (io.BytesIO(data), name), "folder": folder},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()


def _ls(client, folder=""):
    return client.get("/api/drive", query_string={"folder": folder}).get_json()["items"]


def _trash(client):
    return client.get("/api/drive/trash").get_json()


def _dir_id(client, name, folder=""):
    return [i for i in _ls(client, folder) if i["name"] == name and i["is_dir"]][0]["id"]


def test_删除只是进回收站文件还在磁盘上(auth_client):
    a = _up(auth_client, "后悔.txt", "软删", "内容".encode())
    p = os.path.join(social._drive_dir(1), a["stored_name"])
    assert auth_client.delete("/api/drive/%d" % a["id"]).get_json()["trashed"] is True
    assert os.path.exists(p), "软删不该动磁盘"
    assert [i["name"] for i in _ls(auth_client, "软删")] == [], "删了还在列表里"
    assert "后悔.txt" in [i["name"] for i in _trash(auth_client)["items"]]


def test_恢复后回到原来的目录(auth_client):
    a = _up(auth_client, "回来.txt", "恢复/深处")
    auth_client.delete("/api/drive/%d" % a["id"])
    assert auth_client.post("/api/drive/trash/%d/restore" % a["id"]).status_code == 200
    assert [i["name"] for i in _ls(auth_client, "恢复/深处")] == ["回来.txt"]
    assert a["id"] not in [i["id"] for i in _trash(auth_client)["items"]]


def test_删文件夹连子孙一起进回收站恢复时一起回来(auth_client):
    _up(auth_client, "里面.txt", "整棵/子层")
    top = _dir_id(auth_client, "整棵")
    auth_client.delete("/api/drive/%d" % top)
    assert [i["name"] for i in _ls(auth_client, "整棵/子层")] == [], "子孙没跟着进回收站"
    assert auth_client.post("/api/drive/trash/%d/restore" % top).status_code == 200
    assert [i["name"] for i in _ls(auth_client, "整棵/子层")] == ["里面.txt"], "子孙没跟着回来"


def test_恢复文件夹不会把之前单独删的也捞回来(auth_client):
    """靠 deleted_at 认批次。认错了，用户恢复一个文件夹会连带捞回一堆他早就删掉的东西。"""
    early = _up(auth_client, "早就删了.txt", "批次/子")
    auth_client.delete("/api/drive/%d" % early["id"])          # 先单独删这个
    later = _up(auth_client, "后来的.txt", "批次/子")
    top = _dir_id(auth_client, "批次")
    auth_client.delete("/api/drive/%d" % top)                  # 再删整个文件夹
    auth_client.post("/api/drive/trash/%d/restore" % top)
    names = [i["name"] for i in _ls(auth_client, "批次/子")]
    assert names == ["后来的.txt"], "把早先单独删掉的也捞回来了：%s" % names


def test_恢复时原目录已被删会把目录补回来(auth_client):
    a = _up(auth_client, "孤儿.txt", "会没的目录")
    top = _dir_id(auth_client, "会没的目录")
    auth_client.delete("/api/drive/%d" % a["id"])              # 先删文件
    auth_client.delete("/api/drive/%d" % top)                  # 再把目录也删了
    assert auth_client.post("/api/drive/trash/%d/restore" % a["id"]).status_code == 200
    # 目录被补回来了，文件在里面看得见
    assert "会没的目录" in [i["name"] for i in _ls(auth_client) if i["is_dir"]]
    assert [i["name"] for i in _ls(auth_client, "会没的目录")] == ["孤儿.txt"]


def test_彻底删除才真从磁盘上抹掉(auth_client):
    a = _up(auth_client, "真删.txt", "彻底", "独占内容".encode())
    p = os.path.join(social._drive_dir(1), a["stored_name"])
    auth_client.delete("/api/drive/%d" % a["id"])
    assert os.path.exists(p)
    assert auth_client.delete("/api/drive/trash/%d" % a["id"]).status_code == 200
    assert not os.path.exists(p), "彻底删了磁盘上还留着"
    assert a["id"] not in [i["id"] for i in _trash(auth_client)["items"]]


def test_彻底删除也认引用计数(auth_client):
    """回收站 + 去重叠在一起最容易出事：清空回收站把还在用的文件也删了。"""
    keep = _up(auth_client, "还要用.bin", "叠加", "共用这份".encode())
    gone = _up(auth_client, "要清掉.bin", "叠加", "共用这份".encode())
    assert keep["stored_name"] == gone["stored_name"]
    auth_client.delete("/api/drive/%d" % gone["id"])
    auth_client.delete("/api/drive/trash/%d" % gone["id"])     # 彻底清掉副本
    assert os.path.exists(os.path.join(social._drive_dir(1), keep["stored_name"])), \
        "清回收站把还在用的那份也删了"
    assert auth_client.get("/api/drive/%d/download" % keep["id"]).status_code == 200


def test_清空回收站(auth_client):
    _up(auth_client, "清1.txt", "清空")
    b = _up(auth_client, "清2.txt", "清空")
    auth_client.delete("/api/drive/%d" % b["id"])
    assert auth_client.post("/api/drive/trash/empty").get_json()["n"] >= 1
    assert _trash(auth_client)["items"] == []


def test_回收站里的东西预览下载都当不存在(auth_client):
    a = _up(auth_client, "看不了.txt", "禁用", "正文".encode())
    auth_client.delete("/api/drive/%d" % a["id"])
    assert auth_client.get("/api/drive/%d/view" % a["id"]).status_code == 404
    assert auth_client.get("/api/drive/%d/download" % a["id"]).status_code == 404
    assert auth_client.patch("/api/drive/%d" % a["id"], json={"name": "x.txt"}).status_code == 404


def test_回收站里的东西不出现在搜索和目录清单里(auth_client):
    a = _up(auth_client, "搜不到才对.txt", "藏起来/深")
    auth_client.delete("/api/drive/%d" % a["id"])
    hits = auth_client.get("/api/drive", query_string={"q": "搜不到才对"}).get_json()["items"]
    assert hits == [], "回收站里的东西还能被搜出来"
    top = _dir_id(auth_client, "藏起来")
    auth_client.delete("/api/drive/%d" % top)
    folders = auth_client.get("/api/drive/folders").get_json()["folders"]
    assert "藏起来" not in folders, "删掉的目录还出现在「移动到…」的选项里"


def test_同名文件夹删掉后可以再建一个(auth_client):
    auth_client.post("/api/drive/folder", json={"name": "重名夹", "parent": ""})
    top = _dir_id(auth_client, "重名夹")
    auth_client.delete("/api/drive/%d" % top)
    r = auth_client.post("/api/drive/folder", json={"name": "重名夹", "parent": ""})
    assert r.status_code == 200, "回收站里那个把新建挡住了：%s" % r.get_data(as_text=True)[:120]


def test_回收站报告占着多少空间(auth_client):
    a = _up(auth_client, "占地方.bin", "占用", b"q" * 4096)
    before = _trash(auth_client)["held"]
    auth_client.delete("/api/drive/%d" % a["id"])
    assert _trash(auth_client)["held"] - before == 4096, "不告诉用户回收站占了多少，他不知道为什么配额不降"


# ---- 大目录：删了 560 项之后还能不能整棵捞回来 ----

def test_删掉的大目录在回收站里只列一行而且能整棵恢复(auth_client):
    """用户实测：一个 560 项的资料文件夹删掉后，回收站被子项刷屏，
    而**文件夹本身**（id 最小、排最后）被 LIMIT 500 截掉 —— 于是只能一个个恢复子项，
    怎么点都只回来一个空壳文件夹。这条盯住「根必须列出来」和「恢复要带全子孙」。"""
    for i in range(60):
        _up(auth_client, "f%02d.txt" % i, "大目录/子层%d" % (i % 6))
    top = _dir_id(auth_client, "大目录")
    auth_client.delete("/api/drive/%d" % top)
    tr = _trash(auth_client)
    mine = [i for i in tr["items"] if i["id"] == top or "大目录" in (i["folder"] or "")]
    assert [i["name"] for i in mine] == ["大目录"], "回收站该只列这一行（子项折进去）"
    assert mine[0]["kids"] == 66, "没数清它带走了多少东西（6 个子目录 + 60 个文件）"
    r = auth_client.post("/api/drive/trash/%d/restore" % top)
    assert r.status_code == 200 and r.get_json()["n"] == 67
    assert sorted(i["name"] for i in _ls(auth_client, "大目录/子层0")) == \
        ["f%02d.txt" % i for i in range(0, 60, 6)], "子孙没跟着回来"
    assert top not in [i["id"] for i in _trash(auth_client)["items"]]


def test_恢复文件夹时原位已有同名的就并过去(auth_client):
    """并发上传会在同一个目录下留下重复的同名壳（见 idx_drive_dir1 那条迁移）。
    恢复时若硬把回收站里那行也放回来，列表里就会并排站着两个一模一样的文件夹。"""
    _up(auth_client, "里面.txt", "并过去")
    top = _dir_id(auth_client, "并过去")
    auth_client.delete("/api/drive/%d" % top)
    assert auth_client.post("/api/drive/folder", json={"name": "并过去"}).status_code == 200
    auth_client.post("/api/drive/trash/%d/restore" % top)
    assert [i["name"] for i in _ls(auth_client)].count("并过去") == 1, "多出一个同名空壳"
    assert [i["name"] for i in _ls(auth_client, "并过去")] == ["里面.txt"], "内容没回到那个目录里"


def test_同一个目录下建不出两个同名文件夹(auth_client):
    """上传整个文件夹是并发请求，各自补中间目录、彼此看不见对方没提交的行。
    库上的部分唯一索引是最后一道闸。"""
    assert auth_client.post("/api/drive/folder", json={"name": "只此一个"}).status_code == 200
    r = auth_client.post("/api/drive/folder", json={"name": "只此一个"})
    assert r.status_code == 400
    assert [i["name"] for i in _ls(auth_client)].count("只此一个") == 1
