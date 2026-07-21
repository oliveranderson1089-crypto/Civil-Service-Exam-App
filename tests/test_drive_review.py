"""代码审查查出来的坑，每条配一个能复现的回归测试。

前三条是**实测复现过的静默数据丢失**（不报错，东西就是没了），后面几条是资源泄漏
和边界。写在一个文件里，是为了下次谁动这块能一眼看见「这些地方栽过」。
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
    return [i["name"] for i in
            client.get("/api/drive", query_string={"folder": folder}).get_json()["items"]]


def _dir_id(client, name, folder=""):
    m = [i for i in client.get("/api/drive", query_string={"folder": folder}).get_json()["items"]
         if i["name"] == name and i["is_dir"]]
    return m[0]["id"] if m else None


# ---- ① folder 名里的 LIKE 通配符 ----

def test_删带下划线的文件夹不会波及同形的兄弟目录(auth_client):
    """`_` 在 LIKE 里是「任意一个字符」。不转义的话删 a_b 会把 aXb 里的东西一起删掉。
    带下划线的目录名很常见（xwechat_files 之类），这条栽过。"""
    _up(auth_client, "受害者.txt", "a_b/inner")
    _up(auth_client, "无辜者.txt", "aXb/inner")
    auth_client.delete("/api/drive/%d" % _dir_id(auth_client, "a_b"))
    assert _ls(auth_client, "aXb/inner") == ["无辜者.txt"], "删 a_b 把 aXb 的东西也删了"


def test_重命名带下划线的文件夹不会改到兄弟目录(auth_client):
    _up(auth_client, "x.txt", "m_n/sub")
    _up(auth_client, "y.txt", "mQn/sub")
    auth_client.patch("/api/drive/%d" % _dir_id(auth_client, "m_n"), json={"name": "改了"})
    assert _ls(auth_client, "mQn/sub") == ["y.txt"], "mQn 的子孙被 m_n 的改名带走了"
    assert _ls(auth_client, "改了/sub") == ["x.txt"]


def test_复制带下划线的文件夹不会顺手复制兄弟目录(auth_client):
    _up(auth_client, "本体.txt", "c_d/sub")
    _up(auth_client, "别人.txt", "cZd/sub")
    auth_client.post("/api/drive/%d/copy" % _dir_id(auth_client, "c_d"), json={"folder": "存放"})
    assert _ls(auth_client, "存放/c_d/sub") == ["本体.txt"]
    assert _ls(auth_client, "存放/cZd/sub") == [], "把兄弟目录也复制过来了"


# ---- ② 回收站串批 ----

def test_对回收站里的东西再删一次不会把它从恢复批次里踢出去(auth_client):
    """搜索结果跨目录，用户可能同时选中父目录和它的子文件后批量删除 ——
    子文件会被删两次。第二次若重打 del_batch，恢复父目录时它就再也回不来了。"""
    _up(auth_client, "孩子.txt", "父/子")
    top = _dir_id(auth_client, "父")
    auth_client.delete("/api/drive/%d" % top)
    kid = [i for i in auth_client.get("/api/drive/trash").get_json()["items"]
           if i["name"] == "孩子.txt"][0]
    r = auth_client.delete("/api/drive/%d" % kid["id"])       # 再删一次（已经在回收站里了）
    assert r.status_code == 404, "回收站里的东西不该还能再删一次"
    auth_client.post("/api/drive/trash/%d/restore" % top)
    assert _ls(auth_client, "父/子") == ["孩子.txt"], "恢复父目录时孩子没跟着回来"


# ---- ③ 移动目标路径未归一化 ----

def test_移动到带空格的路径也落在点得进去的目录里(auth_client):
    """_ensure_folder_path 会把每段 strip 掉。若不用它归一化后的结果，
    会建出「甲/乙」而文件落在「甲/ 乙」—— 列表按 folder 精确匹配，文件就此消失。"""
    a = _up(auth_client, "要搬的.txt", "起点")
    r = auth_client.patch("/api/drive/%d" % a["id"], json={"folder": "目标/ 子层 "})
    assert r.status_code == 200
    assert r.get_json()["folder"] == "目标/子层"
    assert _ls(auth_client, "目标/子层") == ["要搬的.txt"], "文件落在了一个点不进去的目录"


def test_归一化后的重名也能被检出(auth_client):
    _up(auth_client, "占位.txt", "撞名夹")
    b = _up(auth_client, "占位.txt", "别处")
    r = auth_client.patch("/api/drive/%d" % b["id"], json={"folder": " 撞名夹 "})
    assert r.status_code == 400, "带空格绕过了重名检查"


# ---- ④ Office 预览缓存泄漏 ----

def test_删文件时连转换出的PDF缓存一起删(auth_client):
    """_office_to_pdf 会在原文件旁边留一个同名 .pdf。只删原件的话它成了孤儿：
    没记录引用、不计配额、也没人再清 —— 每个预览过又删掉的 Office 文件都白占一份。"""
    a = _up(auth_client, "报告.docx", "缓存", b"fake docx")
    blob = os.path.join(social._drive_dir(1), a["stored_name"])
    cached = os.path.splitext(blob)[0] + ".pdf"
    open(cached, "wb").write("%PDF-1.4 假装是转换结果".encode())     # 模拟预览生成的缓存
    auth_client.delete("/api/drive/%d" % a["id"])
    auth_client.delete("/api/drive/trash/%d" % a["id"])
    assert not os.path.exists(blob)
    assert not os.path.exists(cached), "转换缓存留在磁盘上，永远没人清"


# ---- ⑤ 分片暂存不受约束 ----

def test_分片传得比声明的多会被拦下(auth_client):
    """init 只校验「声明的大小」。不看实际落盘量的话，客户端可以一直灌块把磁盘写满，
    而这些字节不属于任何记录，配额也数不到。"""
    r = auth_client.post("/api/drive/chunk/init", json={"name": "撑爆.bin", "size": 10})
    up = r.get_json()["upload_id"]
    over = b"z" * (social.CHUNK_SLACK + 1024)
    r = auth_client.post("/api/drive/chunk/%s/0" % up, data=over,
                         content_type="application/octet-stream")
    assert r.status_code == 400, "灌了远超声明大小的数据也照收"


# ---- ⑥ .tmp_ 暂存泄漏 ----

def test_过期的上传暂存会被清掉(auth_client):
    d = social._drive_dir(1)
    stale = os.path.join(d, ".tmp_" + "a" * 32)
    open(stale, "wb").write("半截文件".encode())
    os.utime(stale, (0, 0))                                   # 假装是很久以前的
    fresh = os.path.join(d, ".tmp_" + "b" * 32)
    open(fresh, "wb").write("刚开始传".encode())                       # 正在用的，不能误删
    social._sweep_stale(1)
    assert not os.path.exists(stale), "中断上传留下的暂存件没人清，磁盘会慢慢被吃光"
    assert os.path.exists(fresh), "把正在上传的暂存件也删了"


# ---- ⑦ 清空回收站的 SQL 参数上限 ----

def test_清空一个很大的回收站不会撞上SQL参数上限(auth_client):
    """一次一个占位符的话，几百上千项会超过 SQLite 的宿主参数上限（老版本 999），
    抛异常时前面的 blob 已经删了，留下半清空的烂摊子。"""
    for i in range(1200):
        _up(auth_client, "批量%d.txt" % i, "大回收站", data=b"n%d" % i)
    auth_client.delete("/api/drive/%d" % _dir_id(auth_client, "大回收站"))
    r = auth_client.post("/api/drive/trash/empty")
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert auth_client.get("/api/drive/trash").get_json()["items"] == []
