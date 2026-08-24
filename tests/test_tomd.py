"""云盘「转成 Markdown」：mods/tomd.py + /api/drive/<id>/tomd。

用合成 PDF 而不是真讲义：这几条要钉死的行为都跟**版式**有关（字号、分栏、页眉、
跨页断句），合成的 PDF 才能把这些条件一个个摆出来，也才能在别的机器上重跑。

要钉死的：
1. 正文字号是**算出来的**（占字最多的那一档），不是写死的 —— 写死的话，
   一本 12pt 排的书会整本被判成标题；
2. 双栏页不能把左右栏的句子交错拼起来（那是这个功能第一版最严重的错）；
3. 页眉水印、页码不许进正文；
4. 段落在页末被切断要接回去；
5. 超长正文分卷，不许**静默截断** —— 用户拿到一份看起来完整、其实缺了后半本的
   文件，比报错还糟。
"""
import time

import pytest

from mods import tomd
from mods.social import _tomd_split, _tomd_titles

reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas          # noqa: E402
from reportlab.lib.pagesizes import A4       # noqa: E402

from mods.pdfkit import ensure_pdf_font      # noqa: E402

W, H = A4
HEAD = "样例讲义 内部资料"
# 页末被切断的一段：前半截在第 2 页末尾，后半截在第 3 页开头
CUT_A = "统筹发展和安全，加快构"
CUT_B = "建以国内大循环为主体的新发展格局。"


def _make_pdf(path):
    f = ensure_pdf_font()
    c = canvas.Canvas(str(path), pagesize=A4)

    def head_foot(n):
        c.setFont(f, 9)
        c.drawString(60, H - 40, HEAD)          # 页眉水印：三页都有，位置一样
        c.drawCentredString(W / 2, 28, "- %d -" % n)   # 页脚页码

    # 第 1 页：24pt 大标题 + 14pt 正文（正文占字最多 → 基准应判成 14）
    head_foot(1)
    c.setFont(f, 24)
    c.drawCentredString(W / 2, H - 120, "第一章 总纲")
    c.setFont(f, 14)
    for i, t in enumerate([
            "中国共产党是中国工人阶级的先锋队，同时是中国人民和中华民族的先锋队。",
            "党的最高理想和最终目标是实现共产主义，这是全党必须牢记的根本方向。",
            "党在社会主义初级阶段的基本路线是领导和团结全国各族人民自力更生。",
            "坚持党的基本路线不动摇，是国家兴旺发达长治久安的重要保证之一。"]):
        c.drawString(60, H - 180 - i * 26, t)
    c.showPage()

    # 第 2 页：双栏。左右两栏各 9 行，中线附近不放字
    head_foot(2)
    c.setFont(f, 20)
    c.drawCentredString(W / 2, H - 110, "第二章 组织制度")     # 跨栏标题（20pt → 二级）
    c.setFont(f, 14)
    left = ["民主集中制是党的根本组织原则。", "党员必须履行党章规定的各项义务。",
            "上级组织要经常听取下级意见。", "下级组织要向上级组织请示报告。",
            "党的各级委员会实行集体领导。", "重大问题由党委会集体讨论决定。",
            "个人服从组织是基本要求之一。", "少数服从多数是议事的准则。",
            "全党服从中央是最高的政治原则。"]
    right = ["党的地方组织按期召开代表大会。", "代表大会的职权由党章明确规定。",
             "委员会向代表大会负责并报告。", "党的基层组织是战斗堡垒。",
             "基层组织按照规定进行换届。", "党员的权利受到党章保护。",
             "党内选举实行无记名投票方式。", "选举结果依照程序予以确认。",
             CUT_A]
    for i, t in enumerate(left):
        c.drawString(50, H - 160 - i * 26, t)
    for i, t in enumerate(right):
        c.drawString(320, H - 160 - i * 26, t)
    c.showPage()

    # 第 3 页：接上一页被切断的那半句
    head_foot(3)
    c.setFont(f, 14)
    c.drawString(60, H - 120, CUT_B)
    c.drawString(60, H - 146, "这一段用来验证跨页的段落能接回去。")
    c.showPage()
    c.save()


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    p = tmp_path_factory.mktemp("tomd") / "样例.pdf"
    _make_pdf(p)
    return str(p)


@pytest.fixture(scope="module")
def out(pdf):
    return tomd.convert(pdf, ".pdf")


def test_正文字号是算出来的不是写死的(pdf, out):
    """基准取「占字最多的那一档」。

    这里刻意不写死数字：pdftohtml 给的 size 是按页面缩放后的像素，14pt 的正文出来是 21。
    断言的是「基准 == 正文那几行的字号」，写死 14 的测试只会掩盖这件事。
    """
    body_lines = [round(it["size"]) for pg in tomd.layout_pages(pdf, 1, 0)
                  for it in pg["items"] if "先锋队" in it["txt"]]
    assert body_lines and out["stats"]["body_size"] == body_lines[0]


def test_大标题按字号升到一级(out):
    assert "# 第一章 总纲" in out["md"]
    # 24pt 是正文的 1.7 倍 → 一级；20pt 是 1.43 倍 → 二级
    assert "## 第二章 组织制度" in out["md"]


def test_双栏不交错(out):
    """左栏读完才轮到右栏。交错的话，左栏第一句后面会直接跟上右栏第一句。"""
    md = out["md"]
    i_left_last = md.index("全党服从中央是最高的政治原则。")
    i_right_first = md.index("党的地方组织按期召开代表大会。")
    assert i_left_last < i_right_first, "右栏插到左栏中间了"


def test_页眉水印和页码不进正文(out):
    assert HEAD not in out["md"]
    assert "- 1 -" not in out["md"] and "- 2 -" not in out["md"]


def test_跨页断句接回去(out):
    """「…加快构」+「建以国内大循环为主体…」必须在同一段里，不能是两截。"""
    md = out["md"]
    assert CUT_A + CUT_B.rstrip() in md.replace("\n\n", "\n").replace("\n", "")


def test_没有空段落(out):
    assert "\n\n\n" not in out["md"]


def test_纯文本也能按中文序号分级():
    md = tomd.text_markdown("第一章 总纲\n党是先锋队。\n一、党的性质\n先进性是本质属性。")
    assert md.startswith("## 第一章 总纲")
    assert "### 一、党的性质" in md


def test_不支持的格式明说而不是给个空文件(tmp_path):
    p = tmp_path / "a.zip"
    p.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError):
        tomd.convert(str(p), ".zip")


# ---- 分卷 ----
def test_超长正文分卷且一个字不丢():
    md = "\n\n".join("第 %d 段。%s" % (i, "内" * 200) for i in range(60))
    parts = _tomd_split(md, 3000)
    assert len(parts) > 1
    assert "".join(parts).replace("\n", "") == md.replace("\n", "")


def test_分卷标题带卷号():
    assert _tomd_titles("讲义.pdf", 1) == ["讲义"]
    assert _tomd_titles("讲义.pdf", 3) == ["讲义（1/3）", "讲义（2/3）", "讲义（3/3）"]


# ---- 路由 ----
def _upload(client, path, name="样例.pdf"):
    with open(path, "rb") as f:
        r = client.post("/api/drive", data={"file": (f, name)},
                        content_type="multipart/form-data")
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    d = client.get("/api/drive").get_json()
    return [it for it in d["items"] if it["name"] == name][0]["id"]


def test_预检要快且说得出页数(auth_client, pdf):
    fid = _upload(auth_client, pdf)
    t = time.time()
    d = auth_client.get("/api/drive/%d/tomd/probe" % fid).get_json()
    assert time.time() - t < 5, "预检是用户点完菜单就在等的一步，不能慢"
    assert d["pages"] == 3 and d["scan_pages"] == 0


def test_转完落进AI产出(auth_client, pdf):
    fid = _upload(auth_client, pdf, "落库样例.pdf")
    tid = auth_client.post("/api/drive/%d/tomd" % fid, json={}).get_json()["task_id"]
    for _ in range(120):                       # 后台线程，最多等 30 秒
        t = auth_client.get("/api/drive/tomd/%d" % tid).get_json()
        if t["status"] != "running":
            break
        time.sleep(0.25)
    assert t["status"] == "done", t.get("message")
    items = auth_client.get("/api/aiout").get_json()["items"]
    hit = [i for i in items if i["title"] == "落库样例"]
    assert hit and hit[0]["kind"] == "md"
    body = auth_client.get("/api/aiout/%d" % hit[0]["id"]).get_json()["body"]
    assert "# 第一章 总纲" in body


def test_不支持的格式返回415(auth_client, tmp_path):
    p = tmp_path / "b.zip"
    p.write_bytes(b"PK\x03\x04zzz")
    fid = _upload(auth_client, str(p), "b.zip")
    assert auth_client.get("/api/drive/%d/tomd/probe" % fid).status_code == 415
    assert auth_client.post("/api/drive/%d/tomd" % fid, json={}).status_code == 415


def test_别人的文件转不了(client, auth_client, pdf):
    fid = _upload(auth_client, pdf, "私有.pdf")
    assert client.post("/api/drive/%d/tomd" % fid, json={}).status_code in (401, 403, 404)
