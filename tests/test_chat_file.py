"""聊天里的文件：预览、下载、转存，以及信息栏给的到底是谁的 id。

界面上「点一下文件」原来只有一种结果（下载），现在分成预览 / 下载 / 转存三条路，
这三条都落在同一个接口上：
  · /api/chat/file/<id>            → 下载（as_attachment）
  · /api/chat/file/<id>?view=1     → 应用内预览（内联，Office 转 PDF）
  · /api/chat/file/<id>?text=1     → 阅读模式取纯文字
  · /api/chat/file/<id>/save       → 转存进自己云盘

顺带钉住一个从上线起就错的地方：会话信息栏的「共享文件 / 图片」给前端的 id
是 **chat_msgs.id**，而这个接口认的是 **drive_files.id** —— 两张表的 id 对不上，
所以信息栏里点开一律 403、图片全是碎图。
"""
import io
import sqlite3

import pytest

from conftest import DB

A = 93001        # 好友


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


def _uid():
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def me(auth_client):
    u = _uid()
    _exec("DELETE FROM chat_msgs", "DELETE FROM friends", "DELETE FROM conv_members",
          "DELETE FROM conversations", "DELETE FROM drive_files", "DELETE FROM notifications")
    _exec(("INSERT OR REPLACE INTO users(id,username,password_hash) VALUES(?,?,?)", (A, "友甲93001", "x")),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (u, A)),
          ("INSERT OR REPLACE INTO friends(user_id,friend_id) VALUES(?,?)", (A, u)))
    yield u
    # 走的时候把云盘表擦干净：别的模块有按「全库 source='chat' 一共几行」下的断言，
    # 这里留几行下去，隔壁测试就会莫名其妙地红（同一个库、按文件名排的执行顺序）
    _exec("DELETE FROM drive_files", "DELETE FROM chat_msgs")


def _send(c, to, name, data="# 讲义\n\n第一节".encode("utf-8"), mime="text/markdown"):
    """发一个文件给 to，返回 (消息 id, 收件方那份 drive_files 的 id)。"""
    r = c.post("/api/chat/%d" % to,
               data={"file": (io.BytesIO(data), name)},
               content_type="multipart/form-data")
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    con = sqlite3.connect(DB, timeout=10)
    try:
        row = con.execute("SELECT id, file_id FROM chat_msgs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    return row[0], row[1]


def test_信息栏给的是文件id不是消息id(auth_client, me):
    mid, fid = _send(auth_client, A, "讲义.md")
    assert mid != fid, "这条测试要有意义，两个 id 必须真的不一样"
    d = auth_client.get("/api/chat/info?id=%d" % A).get_json()
    assert [f["id"] for f in d["files"]] == [fid], \
        "信息栏给的 id 必须能直接喂给 /api/chat/file/<id>（原来给的是消息 id，点开一律 403）"
    assert auth_client.get("/api/chat/file/%d" % d["files"][0]["id"]).status_code == 200


def test_信息栏的图片链接也能打开(auth_client, me):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    _send(auth_client, A, "图.png", png, "image/png")
    d = auth_client.get("/api/chat/info?id=%d" % A).get_json()
    assert d["images"], "刚发了一张图，信息栏里应该有"
    for url in (d["images"][0]["url"], d["images"][0]["thumb"]):
        assert auth_client.get(url).status_code == 200, url + " 打不开"


def test_下载是附件预览是内联(auth_client, me):
    _mid, fid = _send(auth_client, A, "讲义.md")
    dl = auth_client.get("/api/chat/file/%d" % fid)
    assert "attachment" in dl.headers.get("Content-Disposition", "")
    view = auth_client.get("/api/chat/file/%d?view=1" % fid)
    assert view.status_code == 200
    assert "attachment" not in view.headers.get("Content-Disposition", ""), \
        "预览要内联给，带 attachment 的话浏览器只会把它下下来"


def test_阅读模式取纯文字(auth_client, me):
    _mid, fid = _send(auth_client, A, "讲义.md")
    d = auth_client.get("/api/chat/file/%d?text=1" % fid).get_json()
    assert "第一节" in d["text"]


def test_不支持预览的格式明确回415(auth_client, me):
    _mid, fid = _send(auth_client, A, "素材.zip", b"PK\x03\x04zzz", "application/zip")
    r = auth_client.get("/api/chat/file/%d?view=1" % fid)
    assert r.status_code == 415, "压缩包看不了就该明说，不能把二进制当网页塞给 iframe"
    assert auth_client.get("/api/chat/file/%d" % fid).status_code == 200, "但下载照旧"


def test_消息里带着能不能预览的标记(auth_client, me):
    _send(auth_client, A, "讲义.md")
    _send(auth_client, A, "素材.zip", b"PK\x03\x04zzz", "application/zip")
    msgs = auth_client.get("/api/chat/%d" % A).get_json()["messages"]
    got = {m["file_name"]: m.get("file_view") for m in msgs if m["kind"] == "file"}
    assert got == {"讲义.md": True, "素材.zip": False}, \
        "后缀表只该有一份（服务端），前端照着这个标记决定给不给「预览」那一行"


def test_转存进自己云盘(auth_client, me):
    """对方发来的文件转存：内容按 sha256 共用，不重复占盘。"""
    _mid, fid = _send(auth_client, A, "讲义.md")
    # 上面那条是「我发给 A」，收件方那份属于 A —— 正好用来测「别人的那一份」
    con = sqlite3.connect(DB, timeout=10)
    try:
        owner = con.execute("SELECT owner_id FROM drive_files WHERE id=?", (fid,)).fetchone()[0]
    finally:
        con.close()
    assert owner == A, "一对一的 file_id 指的是收件人云盘里那一行"
    d = auth_client.post("/api/chat/file/%d/save" % fid).get_json()
    assert d["ok"] and d["existed"] is True, \
        "这份内容我自己云盘里本来就有（我是发送方），不该再存一份"


def test_转存别人发来的文件(auth_client, me):
    """A 发给我的那份属于 A，转存要在我的云盘「聊天文件」里真长出一行。"""
    import hashlib
    import os

    from mods.social import _drive_dir

    blob = "A 的独家讲义 %s" % os.getpid()
    body = blob.encode("utf-8")
    stored = "atest_%d.md" % os.getpid()
    with open(os.path.join(_drive_dir(A), stored), "wb") as f:
        f.write(body)
    afid = _exec(("INSERT INTO drive_files(owner_id,folder,name,stored_name,ext,mime,size,"
                  "is_dir,source,sha256) VALUES(?,'聊天文件','A的讲义.md',?,'.md','text/markdown',"
                  "?,0,'chat',?)", (A, stored, len(body), hashlib.sha256(body).hexdigest())))
    cid = _exec(("INSERT INTO conversations(kind,title) VALUES('direct','')", ()))
    _exec(("INSERT INTO chat_msgs(from_uid,to_uid,conv_id,kind,file_id,file_name,file_size) "
           "VALUES(?,?,?,'file',?,'A的讲义.md',?)", (A, me, cid, afid, len(body))))

    d = auth_client.post("/api/chat/file/%d/save" % afid).get_json()
    assert d["ok"] and not d.get("existed"), "第一次转存应该是真的存了一份"
    assert d["folder"] == "聊天文件"
    rows = auth_client.get("/api/drive?folder=%s" % "聊天文件").get_json()
    assert any(x["name"] == "A的讲义.md" for x in rows.get("files", rows.get("items", []))), \
        "转存完该在自己云盘的「聊天文件」里看得见"
    # 再转存一次不该又长一行
    again = auth_client.post("/api/chat/file/%d/save" % afid).get_json()
    assert again["existed"] is True, "同一份内容转存两次只该有一份"


def test_不相干的人碰不到(auth_client, me):
    _mid, fid = _send(auth_client, A, "讲义.md")
    _exec(("DELETE FROM chat_msgs WHERE file_id=?", (fid,)))     # 抹掉「这文件在我参与的会话里」
    assert auth_client.get("/api/chat/file/%d?view=1" % fid).status_code == 403
    assert auth_client.post("/api/chat/file/%d/save" % fid).status_code == 403
