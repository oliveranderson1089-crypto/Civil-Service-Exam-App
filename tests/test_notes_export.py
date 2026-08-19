"""小记导出：六种格式 + 筛选口径（集成）。

盯三件事：
  1) **筛选口径和界面一致** —— 板块/标签/搜索词导出来的就是屏幕上那几条，
     搜索那条前端是自己过滤的，服务端必须照抄同一套判断，否则「导出当前这些」名不副实；
  2) **只导自己的** —— 别人的小记不能混进我的导出文件；
  3) 每种格式都真能生成，且正文确实在里面（PDF 只验能出字节且是 %PDF 开头）。
"""
import io
import json
import os
import sqlite3
import zipfile

import pytest

from conftest import DB


def _uid(name="tester"):
    con = sqlite3.connect(DB, timeout=10)
    try:
        return con.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _clean(auth_client):
    con = sqlite3.connect(DB, timeout=10)
    try:
        con.execute("DELETE FROM notes")
        con.commit()
    finally:
        con.close()


def _mknote(c, content, **kw):
    data = {"content": content}
    for k in ("board",):
        if kw.get(k):
            data[k] = kw[k]
    for k in ("todos", "tags"):
        if kw.get(k) is not None:
            data[k] = json.dumps(kw[k], ensure_ascii=False)
    r = c.post("/api/notes", data=data)
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    return r.get_json()["id"]


def _exp(c, **params):
    from urllib.parse import urlencode
    return c.get("/api/notes/export?" + urlencode(params))


def test_六种格式都能导出(auth_client):
    _mknote(auth_client, "# 标题\n正文**加粗**和`代码`\n- 项一\n- 项二",
            tags=["申论"], todos=[{"text": "背成语", "done": True}])
    for fmt in ("md", "txt", "html", "json", "zip", "pdf"):
        r = _exp(auth_client, fmt=fmt)
        assert r.status_code == 200, "%s: %s" % (fmt, r.get_data(as_text=True)[:200])
        body = r.get_data()
        assert body, fmt
        if fmt == "pdf":
            assert body[:4] == b"%PDF"
        elif fmt == "zip":
            z = zipfile.ZipFile(io.BytesIO(body))
            assert "小记.md" in z.namelist() and "notes.json" in z.namelist()
            assert "正文" in z.read("小记.md").decode("utf-8")
        else:
            assert "正文" in body.decode("utf-8")


def test_markdown_保留待办勾选与标签(auth_client):
    _mknote(auth_client, "复习", tags=["行测", "常识"],
            todos=[{"text": "做完一套", "done": True}, {"text": "订正", "done": False}])
    txt = _exp(auth_client, fmt="md").get_data(as_text=True)
    assert "- [x] 做完一套" in txt and "- [ ] 订正" in txt
    assert "#行测" in txt and "#常识" in txt


def test_纯文本剥掉_markdown_记号(auth_client):
    _mknote(auth_client, "## 小标题\n这里**很重要**，看[链接](http://x.cn)")
    txt = _exp(auth_client, fmt="txt").get_data(as_text=True)
    assert "**" not in txt and "##" not in txt
    assert "【小标题】" in txt and "很重要" in txt and "链接" in txt


def test_html_是自包含单文件(auth_client):
    _mknote(auth_client, "> 引用一句\n\n```\ncode here\n```")
    html = _exp(auth_client, fmt="html").get_data(as_text=True)
    assert html.startswith("<!doctype html>")
    assert "<blockquote>" in html and "<pre><code>" in html
    assert "http://" not in html.split("<style>")[0]      # 不外链任何东西


def test_json_字段完整可回灌(auth_client):
    nid = _mknote(auth_client, "备份我", board="申论", tags=["范文"])
    d = json.loads(_exp(auth_client, fmt="json").get_data(as_text=True))
    assert d["count"] == 1
    n = d["notes"][0]
    assert n["id"] == nid and n["content"] == "备份我" and n["board"] == "申论"
    assert n["tags"] == ["范文"] and "created_at" in n


def test_按板块和标签筛选(auth_client):
    _mknote(auth_client, "甲条", board="申论", tags=["范文"])
    _mknote(auth_client, "乙条", board="行测", tags=["图推"])
    t = _exp(auth_client, fmt="md", board="申论").get_data(as_text=True)
    assert "甲条" in t and "乙条" not in t
    t = _exp(auth_client, fmt="md", tag="图推").get_data(as_text=True)
    assert "乙条" in t and "甲条" not in t


def test_搜索词口径与前端一致(auth_client):
    _mknote(auth_client, "正文里有关键词")
    _mknote(auth_client, "正文无关", tags=["关键词"])
    _mknote(auth_client, "也无关", todos=[{"text": "关键词在待办里", "done": False}])
    _mknote(auth_client, "彻底无关")
    t = _exp(auth_client, fmt="md", q="关键词").get_data(as_text=True)
    assert "正文里有关键词" in t and "正文无关" in t and "也无关" in t
    assert "彻底无关" not in t


def test_只导指定的几条(auth_client):
    a = _mknote(auth_client, "要这条")
    _mknote(auth_client, "不要这条")
    t = _exp(auth_client, fmt="md", ids=str(a)).get_data(as_text=True)
    assert "要这条" in t and "不要这条" not in t


def test_顺序可翻转(auth_client):
    _mknote(auth_client, "先写的")
    _mknote(auth_client, "后写的")
    desc = _exp(auth_client, fmt="md").get_data(as_text=True)
    asc = _exp(auth_client, fmt="md", order="asc").get_data(as_text=True)
    assert desc.index("后写的") < desc.index("先写的")     # 默认与界面一致：新在上
    assert asc.index("先写的") < asc.index("后写的")


def test_不导别人的小记(auth_client, flask_app):
    _mknote(auth_client, "我的小记")
    con = sqlite3.connect(DB, timeout=10)
    try:
        other = _uid() + 999
        con.execute("INSERT INTO notes(user_id,board,content) VALUES(?,?,?)",
                    (other, "", "别人的小记"))
        con.commit()
    finally:
        con.close()
    t = _exp(auth_client, fmt="md").get_data(as_text=True)
    assert "我的小记" in t and "别人的小记" not in t


def test_空结果和坏格式都给明确错误(auth_client):
    r = _exp(auth_client, fmt="md")
    assert r.status_code == 400 and "没有可导出" in r.get_json()["error"]
    _mknote(auth_client, "有内容了")
    r = _exp(auth_client, fmt="docx")
    assert r.status_code == 400 and "不支持的格式" in r.get_json()["error"]


def test_关掉待办和标签就不出现在导出里(auth_client):
    _mknote(auth_client, "正文", tags=["标签甲"], todos=[{"text": "待办甲", "done": False}])
    t = _exp(auth_client, fmt="md", todos=0, tags=0).get_data(as_text=True)
    assert "正文" in t and "标签甲" not in t and "待办甲" not in t


def test_post_与_get_结果一致(auth_client):
    _mknote(auth_client, "两条路一样")
    g = _exp(auth_client, fmt="md").get_data(as_text=True)
    p = auth_client.post("/api/notes/export", json={"fmt": "md"}).get_data(as_text=True)
    # 只差生成时间那一行
    assert [x for x in g.split("\n") if "导出于" not in x] == \
           [x for x in p.split("\n") if "导出于" not in x]


def _png_bytes():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 60, 60)).save(b, "PNG")
    b.seek(0)
    return b


def test_带图片的三种格式各自把图带上(auth_client):
    """图片是小记里最容易被导丢的东西：md 单文件带不走（只留引用），
    html 要内嵌成 data URI，zip 要放进 images/ 且文件名对得上哪条小记。"""
    r = auth_client.post("/api/notes", data={
        "content": "配图那条", "images": (_png_bytes(), "shot.png")},
        content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    nid = r.get_json()["id"]

    html = _exp(auth_client, fmt="html").get_data(as_text=True)
    assert "data:image/png;base64," in html

    z = zipfile.ZipFile(io.BytesIO(_exp(auth_client, fmt="zip").get_data()))
    rel = "images/%04d-1.png" % nid
    assert rel in z.namelist()
    assert rel in z.read("小记.md").decode("utf-8")      # md 里的引用要指得到包里的图
    assert z.read(rel)[:4] == b"\x89PNG"

    assert _exp(auth_client, fmt="pdf").get_data()[:4] == b"%PDF"

    md = _exp(auth_client, fmt="md").get_data(as_text=True)
    assert "导出 ZIP" in md                              # 单文件里得说清楚图去哪了
    # 单文件 md 和包里那份 md，图片引用必须是**同一条路径**：
    # 各写一套的那一版，单文件引用的是库里的 note_<uuid>.png，照着它去包里找图必然扑空
    assert rel in md


def test_关掉图片就不打进压缩包(auth_client):
    auth_client.post("/api/notes", data={"content": "配图那条", "images": (_png_bytes(), "s.png")},
                     content_type="multipart/form-data")
    z = zipfile.ZipFile(io.BytesIO(_exp(auth_client, fmt="zip", imgs=0).get_data()))
    assert not [n for n in z.namelist() if n.startswith("images/")]


def test_board_参数只当筛选不当显示开关(auth_client):
    """踩过的坑：body.board 既想当「筛选哪个板块」又想当「正文里标不标板块」，
    两者同层，board="" 时后者被当成关掉 —— 时间那行就整行没了。"""
    _mknote(auth_client, "甲条", board="申论")
    t = auth_client.post("/api/notes/export", json={"fmt": "md", "board": ""}).get_data(as_text=True)
    assert "申论" in t                                    # 不筛板块 ≠ 不显示板块
    t = auth_client.post("/api/notes/export", json={"fmt": "md", "board": "申论"}).get_data(as_text=True)
    assert "甲条" in t
    t = auth_client.post("/api/notes/export",
                         json={"fmt": "md", "time": False}).get_data(as_text=True)
    assert "申论" not in t                                # 关掉才是真关掉


@pytest.mark.skipif(not __import__("shutil").which("pdftotext"),
                    reason="没装 pdftotext，跳过 PDF 取字检查")
def test_pdf_不用中文字体没有的字形(auth_client):
    """uming.ttc / STSong 没有 ☑ ☐ 📎 这些字形，直接印会变成空白或黑块 ——
    屏幕上用什么符号是另一回事，进 PDF 得换成字体真有的字。"""
    import shutil
    import subprocess
    import tempfile
    r = auth_client.post("/api/notes", data={
        "content": "带附件那条", "attachments": (io.BytesIO(b"hello"), "讲义.txt")},
        content_type="multipart/form-data")
    assert r.status_code == 201
    _mknote(auth_client, "带待办那条", todos=[{"text": "做完", "done": True},
                                              {"text": "没做", "done": False}])
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fp:
        fp.write(_exp(auth_client, fmt="pdf").get_data())
        path = fp.name
    try:
        txt = subprocess.run([shutil.which("pdftotext"), path, "-"],
                             capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
    finally:
        os.unlink(path)
    assert "做完" in txt and "讲义.txt" in txt
    for bad in ("☑", "☐", "📎"):
        assert bad not in txt, "PDF 里出现了字体没有的字形：%s" % bad
    assert "√" in txt and "□" in txt
