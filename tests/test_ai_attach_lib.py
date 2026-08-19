"""AI 附件：直接引用云盘 / 资料库里已经有的文件（不重新上传一遍）。

来由：用户在云盘里右键「复制」，到 AI 助手里粘贴 —— 什么都没发生。
云盘的「复制」只是把 id 记在前端一个数组里（系统剪贴板碰不到应用内的文件），
而 /api/ai/extract 当时只认 multipart 上传，两头对不上。

这里钉住三件事：
1. 给个 drive_id / material_id 就能读成附件（几十 MB 的讲义不必下下来再传回去）；
2. **原件一根汗毛都不能动** —— 图片附件那条路会把临时文件 os.replace 进暂存目录，
   要是对云盘原件也这么干，用户的文件就当场从云盘里消失了；
3. 别人的、已删的、文件夹、超大的，一律给一句人话，不是 500。
"""
import io
import os

import pytest

from mods import attach


def _up_drive(client, name, folder="", data="云盘里的正文".encode()):
    r = client.post("/api/drive", data={"file": (io.BytesIO(data), name), "folder": folder},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()


def _drive_row(client, name, folder=""):
    d = client.get("/api/drive", query_string={"folder": folder}).get_json()
    return next(it for it in d["items"] if it["name"] == name)


def _extract(client, **body):
    return client.post("/api/ai/extract", json=body)


def test_云盘文件可以直接当附件(auth_client):
    _up_drive(auth_client, "讲义.txt", data="社区工作者考试要点".encode())
    fid = _drive_row(auth_client, "讲义.txt")["id"]
    d = _extract(auth_client, drive_id=fid).get_json()
    assert d.get("error") is None, d
    assert "社区工作者考试要点" in d["text"]
    assert d["name"] == "讲义.txt"          # 附件条上显示的是云盘里那个名字


def test_读完之后云盘原件还在(auth_client, monkeypatch):
    """图片走的是「把文件搬进暂存目录」那条路。对上传的临时文件搬走没问题，
    对云盘原件搬走 = 用户的文件从云盘里凭空消失 —— 这条就是防它的。"""
    monkeypatch.setattr(attach, "vision_configured", lambda: False)
    monkeypatch.setattr(attach, "_ocr_image", lambda p: "图里的字")
    _up_drive(auth_client, "题目.png", data=b"\x89PNG\r\n\x1a\nfake")
    row = _drive_row(auth_client, "题目.png")
    d = _extract(auth_client, drive_id=row["id"]).get_json()
    assert d["text"] == "图里的字"
    assert d.get("image"), "原图没留档，这一轮就用不上视觉模型了"
    # 留档的是**副本**，云盘那份必须原地不动
    assert os.path.exists(os.path.join(attach.AI_IMG_DIR, d["image"]))
    assert auth_client.get("/api/drive/%d/download" % row["id"]).status_code == 200, \
        "云盘原件被搬走了 —— 用户会发现文件从云盘里消失了"
    assert any(it["name"] == "题目.png" for it in
               auth_client.get("/api/drive").get_json()["items"])


def test_资料库文件也能当附件(auth_client):
    r = auth_client.post("/api/materials", data={
        "file": (io.BytesIO("申论评分标准".encode()), "标准.txt"), "board": "申论"},
        content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    mid = r.get_json()["id"]
    d = _extract(auth_client, material_id=mid).get_json()
    assert "申论评分标准" in d["text"]


def test_文件夹给一句人话而不是崩掉(auth_client):
    _up_drive(auth_client, "a.txt", folder="备考资料")
    fid = _drive_row(auth_client, "备考资料")["id"]
    r = _extract(auth_client, drive_id=fid)
    assert r.status_code == 404
    assert "文件夹" in r.get_json()["error"]


@pytest.mark.parametrize("body", [{"drive_id": 99999}, {"material_id": 99999},
                                  {"drive_id": "abc"}])
def test_拿不到的文件回一句话不回500(auth_client, body):
    r = _extract(auth_client, **body)
    assert r.status_code == 404
    assert r.get_json()["error"]


def test_太大的文件先说清楚再让人换个法子(auth_client, monkeypatch):
    """这条路绕过了 HTTP 上传，Flask 的 MAX_CONTENT_LENGTH 挡不住它 ——
    没有自己这道闸，一份 96MB 的讲义会让人对着转圈等到以为坏了。"""
    _up_drive(auth_client, "大讲义.pdf", data=b"x" * 4096)
    fid = _drive_row(auth_client, "大讲义.pdf")["id"]
    monkeypatch.setattr(attach, "ATT_SRC_MAX", 1024)
    r = _extract(auth_client, drive_id=fid)
    assert r.status_code == 404
    assert "上限" in r.get_json()["error"]


def test_不带来源也不带文件还是老话术(auth_client):
    r = _extract(auth_client)
    assert r.status_code == 400
    assert r.get_json()["error"] == "没有文件"
