"""发送到聊天：云盘 / 资料库 → 好友 + 小组。

以前这条路只有「云盘的单个文件 → 一个好友」：文件夹发不了、群聊到不了、资料库
压根没有应用内分享（菜单里那个「分享」走的是系统分享面板，浏览器下就是下载到本地）。

这里盯三件事：
· 一次选好对象能同时发给多个好友和多个小组，越权的目标要被丢掉；
· 文件夹是打包成 zip 发出去的，不是把里面的文件摊平刷屏；
· 发进小组必须在发送方云盘留一行（群消息引用的就是那一行），且按 sha256 去重，
  不能因为「发了一次」就多占一份盘。
"""
import io
import os
import sqlite3

import pytest

from conftest import DB
from mods import social

A, B = 93001, 93002        # 两个好友
OUT = 93009                # 不是好友、也不在组里的陌生人


def _exec(*stmts):
    con = sqlite3.connect(DB, timeout=10)
    try:
        last = None
        for st in stmts:
            sql, params = (st, ()) if isinstance(st, str) else st
            last = con.execute(sql, params).lastrowid
        con.commit()
        return last
    finally:
        con.close()


def _q(sql, params=()):
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


@pytest.fixture
def me(auth_client):
    u = _q("SELECT id FROM users WHERE username='tester'")[0]["id"]
    _exec("DELETE FROM chat_msgs", "DELETE FROM friends", "DELETE FROM conv_members",
          "DELETE FROM conversations", "DELETE FROM notifications",
          "DELETE FROM drive_files", "DELETE FROM materials")
    for f, name in ((A, "友甲93001"), (B, "友乙93002"), (OUT, "路人93009")):
        _exec(("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)",
               (f, name, "x")))
    for f in (A, B):
        _exec(("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, f)),
              ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (f, u)))
    return u


def _group(c, name="省考冲刺组", members=(A, B)):
    return c.post("/api/chat/groups", json={"name": name, "members": list(members)}).get_json()["id"]


def _up(c, name, folder="", data="一份资料".encode()):
    r = c.post("/api/drive", data={"file": (io.BytesIO(data), name), "folder": folder},
               content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()


def _mat(c, name="讲义.pdf", board="时政", data="资料库里的一份".encode()):
    r = c.post("/api/materials", data={"file": (io.BytesIO(data), name), "board": board,
                                       "section": "", "title": ""},
               content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()


# ---- 能发给谁 ----

def test_可选对象里好友和小组都在(auth_client, me):
    g = _group(auth_client)
    d = auth_client.get("/api/chat/targets").get_json()
    assert {f["id"] for f in d["friends"]} == {A, B}
    assert [x["id"] for x in d["groups"]] == [g]
    assert d["groups"][0]["title"] == "省考冲刺组"
    assert d["groups"][0]["n"] == 3, "群里三个人（自己 + 两个好友）"


def test_不是好友的人不在可选列表里(auth_client, me):
    assert OUT not in {f["id"] for f in auth_client.get("/api/chat/targets").get_json()["friends"]}


# ---- 云盘 → 聊天 ----

def test_一次发给多个好友和多个小组(auth_client, me):
    g1, g2 = _group(auth_client, "甲组"), _group(auth_client, "乙组")
    row = _up(auth_client, "范文.pdf")
    r = auth_client.post("/api/drive/%d/send" % row["id"],
                         json={"users": [A, B], "groups": [g1, g2]})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_json()["n"] == 4

    direct = _q("SELECT to_uid FROM chat_msgs WHERE from_uid=? AND to_uid<>0", (me,))
    assert {x["to_uid"] for x in direct} == {A, B}
    grp = _q("SELECT conv_id, kind, file_name FROM chat_msgs WHERE from_uid=? AND to_uid=0", (me,))
    assert {x["conv_id"] for x in grp} == {g1, g2}
    assert all(x["file_name"] == "范文.pdf" and x["kind"] == "file" for x in grp)


def test_老客户端的单个好友写法还认(auth_client, me):
    """安卓壳 / 桌面壳的旧版本发的是 {"to": 3}，它们不会跟着应用一起更新。"""
    row = _up(auth_client, "旧壳.pdf")
    r = auth_client.post("/api/drive/%d/send" % row["id"], json={"to": A})
    assert r.status_code == 200 and r.get_json()["n"] == 1
    assert [x["to_uid"] for x in _q("SELECT to_uid FROM chat_msgs")] == [A]


def test_越权的目标被丢掉(auth_client, me):
    """不是好友、不在组里的，混进列表也不能发过去。"""
    row = _up(auth_client, "越权.pdf")
    other = _exec(("INSERT INTO conversations(kind,title,owner_id) VALUES('group','别人的组',?)", (OUT,)))
    r = auth_client.post("/api/drive/%d/send" % row["id"],
                         json={"users": [A, OUT], "groups": [other]})
    assert r.get_json()["n"] == 1, "只有那个好友该收到"
    assert not _q("SELECT 1 FROM chat_msgs WHERE to_uid=? OR conv_id=?", (OUT, other))


def test_一个对象都没选就别发(auth_client, me):
    row = _up(auth_client, "空.pdf")
    r = auth_client.post("/api/drive/%d/send" % row["id"], json={"users": [], "groups": []})
    assert r.status_code == 400


def test_收件人云盘里能找到这份文件(auth_client, me):
    row = _up(auth_client, "给你的.pdf")
    auth_client.post("/api/drive/%d/send" % row["id"], json={"users": [A]})
    got = _q("SELECT folder, name FROM drive_files WHERE owner_id=?", (A,))
    assert [(x["folder"], x["name"]) for x in got] == [("聊天文件", "给你的.pdf")]


# ---- 文件夹：打包成 zip ----

def test_文件夹发出去的是一个压缩包(auth_client, me):
    g = _group(auth_client)
    _up(auth_client, "一.txt", "真题集", "第一份".encode())
    _up(auth_client, "二.txt", "真题集", "第二份".encode())
    d = _q("SELECT id FROM drive_files WHERE owner_id=? AND is_dir=1 AND name='真题集'", (me,))[0]["id"]
    r = auth_client.post("/api/drive/%d/send" % d, json={"users": [A], "groups": [g]})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    names = {x["file_name"] for x in _q("SELECT file_name FROM chat_msgs WHERE from_uid=?", (me,))}
    assert names == {"真题集.zip"}, "应该只发出一个压缩包，而不是把里面的文件摊平逐个发"


def test_空文件夹发不出去也不留残骸(auth_client, me):
    auth_client.post("/api/drive/folder", json={"name": "空的", "parent": ""})
    d = _q("SELECT id FROM drive_files WHERE owner_id=? AND is_dir=1 AND name='空的'", (me,))[0]["id"]
    assert auth_client.post("/api/drive/%d/send" % d, json={"users": [A]}).status_code == 400
    left = [f for f in os.listdir(social._drive_dir(me)) if f.startswith(".tmp_zip_")]
    assert not left, "打包的临时文件没删掉：%s" % left


# ---- 资料库 → 聊天 ----

def test_资料发给好友(auth_client, me):
    m = _mat(auth_client, "申论范文.pdf")
    r = auth_client.post("/api/materials/%d/send" % m["id"], json={"users": [A]})
    assert r.status_code == 200 and r.get_json()["n"] == 1
    got = _q("SELECT file_name FROM chat_msgs WHERE to_uid=?", (A,))
    assert [x["file_name"] for x in got] == ["申论范文.pdf"]
    assert _q("SELECT 1 FROM drive_files WHERE owner_id=?", (A,)), "对方云盘里也该留一份，方便转存"


def test_资料发进小组要在自己云盘登记一行(auth_client, me):
    """群消息只存发送方那一份、file_id 指的就是那一行；资料库的文件不在云盘目录里，
    所以必须先登记进来，否则群里点开是 404。"""
    g = _group(auth_client)
    m = _mat(auth_client, "讲义.pdf", data="讲义正文".encode())
    assert auth_client.post("/api/materials/%d/send" % m["id"], json={"groups": [g]}).status_code == 200
    mine = _q("SELECT id, folder, name FROM drive_files WHERE owner_id=? AND is_dir=0", (me,))
    assert [(x["folder"], x["name"]) for x in mine] == [("聊天文件", "讲义.pdf")]
    msg = _q("SELECT file_id FROM chat_msgs WHERE conv_id=?", (g,))[0]
    assert msg["file_id"] == mine[0]["id"], "群消息该引用发送方云盘里的那一行"


def test_同一份内容发两次不重复占盘(auth_client, me):
    g = _group(auth_client)
    m = _mat(auth_client, "讲义.pdf", data="一模一样的内容".encode())
    for _ in range(2):
        auth_client.post("/api/materials/%d/send" % m["id"], json={"groups": [g]})
    rows = _q("SELECT stored_name FROM drive_files WHERE owner_id=? AND is_dir=0", (me,))
    assert len(rows) == 2 and len({x["stored_name"] for x in rows}) == 1, "两行该共用一份磁盘文件"


def test_别人的资料发不了(auth_client, me):
    """既不是自己的、也没共享给自己 —— 拿到 id 也不该发得出去。"""
    _exec(("INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
           "VALUES(?,'','','别人的','别人的.pdf','x.pdf','.pdf','',10)", (OUT,)))
    mid = _q("SELECT id FROM materials WHERE user_id=?", (OUT,))[0]["id"]
    assert auth_client.post("/api/materials/%d/send" % mid, json={"users": [A]}).status_code == 404


# ---- 分片通道：资料库也能走 ----

def _chunked(client, name, body, chunk=8, **extra):
    r = client.post("/api/drive/chunk/init", json=dict({"name": name, "size": len(body)}, **extra))
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    up = r.get_json()["upload_id"]
    for i, p in enumerate([body[i:i + chunk] for i in range(0, len(body), chunk)]):
        assert client.post("/api/drive/chunk/%s/%d" % (up, i), data=p,
                           content_type="application/octet-stream").status_code == 200
    return up


def test_分片传进资料库(auth_client, me):
    """资料库原先是一整个请求发完，撞 64MB 全局上限；接到分片通道上之后没有这堵墙。"""
    body = "资料库的大文件".encode() * 40
    up = _chunked(auth_client, "大讲义.pdf", body, target="materials", board="时政", title="八月要闻")
    r = auth_client.post("/api/drive/chunk/%s/done" % up)
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    row = r.get_json()
    assert row["board"] == "时政" and row["title"] == "八月要闻" and row["size"] == len(body)
    assert not _q("SELECT 1 FROM drive_files WHERE owner_id=? AND is_dir=0", (me,)), \
        "落资料库的不该同时在云盘里冒出来一行"
    items = auth_client.get("/api/materials").get_json()["items"]
    assert [x["title"] for x in items] == ["八月要闻"]


def test_分片上限不再是单请求那两百兆(auth_client, me):
    """分片之后单个请求只有 4MB，200MB 那个数没有理由继续压着它。"""
    assert social.BIG_MAX > social.DRIVE_MAX
    r = auth_client.post("/api/drive/chunk/init",
                         json={"name": "巨大.bin", "size": social.DRIVE_MAX + 1})
    assert r.status_code == 201, "刚过单请求上限就被拦，等于分片白做了"
    r = auth_client.post("/api/drive/chunk/init",
                         json={"name": "过分了.bin", "size": social.BIG_MAX + 1})
    assert r.status_code == 400


def test_乱写的落点当云盘处理(auth_client, me):
    up = _chunked(auth_client, "乱写.bin", "内容".encode(), target="随便写的")
    assert auth_client.post("/api/drive/chunk/%s/done" % up).status_code == 201
    assert _q("SELECT 1 FROM drive_files WHERE owner_id=? AND name='乱写.bin'", (me,))
