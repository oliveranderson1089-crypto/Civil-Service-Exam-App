"""全国考情：爬虫的抽取规则 + 列表接口。

crawl_exam.py 是 systemd 定时器（gongkao-exam.timer）直接拉起的**独立脚本**，
没人 import 它 —— 和 summarize_ai.py 一个处境（那次连崩两晚没人知道）。所以这里
**真跑**一遍 main()：桩掉网络和 AI、走测试库，既拦 import 断链，也拦「函数体里才炸」的断链。

抽取规则也必须钉住。它面对的是 30 多个随时改版的外站，规则一松就把仲裁公告、
采购比选、银行招聘全收进来（实测四川省厅首页 5 条命中里 3 条是这种）；一紧就整个省
再也不更新，而且是**静默**的 —— 页面上只看得到「这个省没公告」。
"""
import sqlite3

import pytest

import crawl_exam as C
from conftest import DB

LIST_HTML = """
<ul class="list">
  <li><a href="/2026/0728/2869479.html">2026年湖南株洲市炎陵县公开招聘事业单位工作人员16人公告</a><span>2026-07-28</span></li>
  <li><a href="https://sc.huatu.com/2025/1027/2041579.html">2026年四川省级机关公开考试录用公务员的公告（85人）</a></li>
  <li><a href="//bj.huatu.com/2026/0715/1244287.html">推荐 2026北京市考补充录用公务员公告 07-15</a></li>
  <li><a href="/rst/gsgg/2026/7/28/abc.shtml">四川省劳动人事争议仲裁委员会公告</a></li>
  <li><a href="/rst/gsgg/2026/7/28/def.shtml">考务用车租赁服务采购项目比选流标公告</a></li>
  <li><a href="/2026/0728/bank.html">2026年民生银行总行社会招聘公告</a></li>
  <li><a href="/zt/peixun.html">2026省考公告解读峰会免费领取</a></li>
</ul>
"""
PAGE = "https://sc.huatu.com/gwy/"


def _titles(rows):
    return [r["title"] for r in rows]


def test_抽取只留真招考():
    rows = C.extract(LIST_HTML, PAGE)
    got = _titles(rows)
    assert "2026年湖南株洲市炎陵县公开招聘事业单位工作人员16人公告" in got
    assert "2026年四川省级机关公开考试录用公务员的公告（85人）" in got
    # 仲裁 / 采购比选 / 银行 / 培训广告：全是带「公告」但和招考无关的，一条都不该进来
    for bad in ("仲裁", "比选", "银行", "峰会"):
        assert not any(bad in t for t in got), "%s 混进来了：%s" % (bad, got)


def test_人行和政策性银行不算商业银行招聘():
    """「银行」一刀切会把人行招录也丢掉——那是国考序列、每年和国考同期报名，
       公考人必看。而且丢得悄无声息：页面上只表现为「今年怎么没有人行」。"""
    html = "".join(
        '<li><a href="/2026/0728/%d.html">%s</a></li>' % (i, t) for i, t in enumerate([
            "中国人民银行2026年度招收人员公告",
            "中国人民银行成都分行2026年度考试录用公告",
            "国家开发银行2026年度校园招聘公告",
            "2026年民生银行总行社会招聘公告",
            "2026年渤海银行沈阳分行社会招聘公告"]))
    got = _titles(C.extract("<ul>%s</ul>" % html, PAGE))
    assert sum("人民银行" in t for t in got) == 2, got
    assert any("国家开发银行" in t for t in got), got
    assert not any(x in t for t in got for x in ("民生银行", "渤海银行")), got


def test_标题两头的角标和日期都要切掉():
    rows = C.extract(LIST_HTML, PAGE)
    t = [x for x in _titles(rows) if "北京" in x][0]
    assert t == "2026北京市考补充录用公务员公告", repr(t)


def test_相对链接与协议相对链接都要补全():
    def url_of(kw):
        return next(r["url"] for r in C.extract(LIST_HTML, PAGE) if kw in r["title"])

    assert url_of("炎陵县") == "https://sc.huatu.com/2026/0728/2869479.html"
    # `//host/path` 既不是绝对地址也不以单斜杠开头，漏掉它整站链接全是坏的
    assert url_of("北京市考") == "https://bj.huatu.com/2026/0715/1244287.html"


@pytest.mark.parametrize("url, want", [
    ("https://sc.huatu.com/2026/0728/2041579.html", "2026-07-28"),   # 华图：月日粘一起
    ("https://rst.sc.gov.cn/rst/gsgg/2026/7/28/abc.shtml", "2026-07-28"),  # 政务站：斜杠分开
])
def test_发布日优先从URL捞(url, want):
    assert C.pick_date("某某公告", "", url) == want


def test_未来的日期不当发布日():
    """抓到过 2026-12-30 —— 那是公告里的报名截止日。当成发布日会窜到列表最顶上。"""
    assert C.pick_date("某某公告", "报名截止 2099-12-30", "/a/b.html") == ""


def test_没日期的条目一律丢掉():
    items = [{"title": "a", "url": "u1", "pub_date": ""},
             {"title": "b", "url": "u2", "pub_date": "2099-01-01"}]
    assert [x["url"] for x in C.fresh(items, 30)] == ["u2"]


def test_AI条数对不上就整批作废():
    """错位比缺失危险：把 A 省的人数安到 B 省头上，用户是照着它去报名的。"""
    assert C._parse_rows('[{"kind":"省考"}]', 3) == []
    assert C._parse_rows('{"items":[{"kind":"省考"},{"kind":"事考"}]}', 2)[1]["kind"] == "事考"
    assert C._parse_rows("```json\n[{\"kind\":\"国考\"}]\n```", 1)[0]["kind"] == "国考"


def test_真跑一遍主流程_桩掉网络和AI(monkeypatch):
    """定时器拉起来的就是这条路。桩两头，中间全走真代码。"""
    monkeypatch.setattr(C, "DB", DB)
    monkeypatch.setattr(C, "fetch", lambda url, timeout=25: LIST_HTML)
    monkeypatch.setattr(C, "sources", lambda: [
        ("四川", "测试源", "https://sc.huatu.com/gwy/", "省考")])
    seen = {}

    def fake_ai(batch, default_kind, region):
        seen["n"] = len(batch)
        return [{"kind": "省考", "region": "四川", "headcount": "85", "brief": "省级机关招录"}
                for _ in batch]

    monkeypatch.setattr(C, "ai_classify", fake_ai)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)

    C.main([])
    assert seen.get("n"), "AI 归类根本没被调到，说明条目在入库前就全被过滤没了"

    con = sqlite3.connect(DB)
    rows = con.execute("SELECT kind, region, headcount, source FROM exam_notices "
                       "WHERE source='测试源'").fetchall()
    # 再跑一遍不能出重复：url 是唯一键，重复抓取是常态（定时器一天跑两次）
    C.main([])
    again = con.execute("SELECT COUNT(*) FROM exam_notices WHERE source='测试源'").fetchone()[0]
    con.close()
    assert rows and rows[0] == ("省考", "四川", "85", "测试源")
    assert again == len(rows), "重复抓取产生了重复条目"


# ---------------------------------------------------------------- 接口
def test_列表接口能筛能搜(auth_client):
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM exam_notices WHERE url LIKE 'api-test%'")
    for i, (kind, region, title) in enumerate([
            ("国考", "全国", "2026年度中央机关公开考试录用公务员公告"),
            ("省考", "四川", "四川省2026年度考试录用公务员公告"),
            ("事考", "广东", "广东省属事业单位2026年集中公开招聘公告")]):
        db.execute("INSERT INTO exam_notices(kind,region,title,url,source,pub_date) "
                   "VALUES(?,?,?,?,?,?)",
                   (kind, region, title, "api-test-%d" % i, "测试", "2026-07-%02d" % (20 + i)))
    db.commit()
    db.close()

    r = auth_client.get("/api/exam/notices?kind=省考")
    assert r.status_code == 200
    assert all(x["kind"] == "省考" for x in r.get_json()["items"])

    r = auth_client.get("/api/exam/notices?q=集中公开招聘")
    assert [x["region"] for x in r.get_json()["items"]] == ["广东"]


def test_只看关注地区时国考不能被藏掉(auth_client):
    """「只看四川」不等于「不看国考」——国考对谁都算数。"""
    r = auth_client.put("/api/exam/follow", json={"regions": ["四川"]})
    assert r.status_code == 200 and r.get_json()["regions"] == ["四川"]

    got = auth_client.get("/api/exam/notices?region=follow").get_json()
    regions = {x["region"] for x in got["items"]}
    assert regions <= {"四川", "全国"}, regions
    assert "全国" in regions, "全国性公告被关注地区筛掉了"


def test_关注清空后不许兜回默认值(auth_client):
    """设成空数组是一个明确的操作（我不想只看四川），兜回默认就等于这个操作永远无效。"""
    auth_client.put("/api/exam/follow", json={"regions": []})
    got = auth_client.get("/api/exam/notices?region=follow").get_json()
    assert got["follow"] == []
    assert {x["region"] for x in got["items"]} <= {"全国"}
