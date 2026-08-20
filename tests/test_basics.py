"""机构讲义（优路精讲 / 三色速记 / 考点对照）的读取接口。

重点盯两处**结构性**的东西，它们错了界面会静默变空，而不是报错：

  1. 对照视图走 basic_map 的多对多，且是按 nkey 关联的 —— 直接挂 node_id 的话，
     ingest_basics.py --reparse 重建节点后 id 全变，对照页当场清空。
  2. entries 只统计 level>=2，板块页据此决定摆不摆卡片；把章也算进去会让
     只有目录、没正文的板块也长出入口。
"""
import pytest

from conftest import appmod
from core import get_db


@pytest.fixture
def seeded(auth_client):
    """灌一小份两套资料 + 一个对齐好的考点。"""
    with appmod.app.app_context():
        db = get_db()
        db.execute("DELETE FROM basic_map")
        db.execute("DELETE FROM basic_topics")
        db.execute("DELETE FROM basic_blocks")
        db.execute("DELETE FROM basic_nodes")
        db.execute("DELETE FROM basic_sources")
        ids = {}
        for source, title in (("youlu", "优路讲义"), ("sanse", "三色笔记")):
            cur = db.execute(
                "INSERT INTO basic_sources(source,board,title,stored_name,pages) "
                "VALUES(?,?,?,?,?)", (source, "资料分析", title, source + ".pdf", 10))
            sid = cur.lastrowid
            ch = db.execute(
                "INSERT INTO basic_nodes(source_id,source,board,level,title,sort,"
                "page_from,nkey) VALUES(?,?,?,1,?,0,1,?)",
                (sid, source, "资料分析", "第一章", "资料分析|1|第一章|0|" + source)).lastrowid
            leaf = db.execute(
                "INSERT INTO basic_nodes(source_id,source,board,parent_id,level,title,"
                "sort,page_from,nkey) VALUES(?,?,?,?,2,?,1,3,?)",
                (sid, source, "资料分析", ch, "增长率", "资料分析|2|增长率|1|" + source)).lastrowid
            db.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md,page) "
                       "VALUES(?,0,'concept',?,3)", (leaf, "{{r|增长率}}=增长量/基期"))
            db.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md,page) "
                       "VALUES(?,1,'example',?,3)", (leaf, "【例 1】…"))
            ids[source] = {"chapter": ch, "leaf": leaf,
                           "nkey": "资料分析|2|增长率|1|" + source}
        tid = db.execute("INSERT INTO basic_topics(board,name,sort) VALUES('资料分析','增长率',0)").lastrowid
        for source in ("youlu", "sanse"):
            db.execute('INSERT INTO basic_map(topic_id,board,source,nkey,"by") '
                       "VALUES(?,'资料分析',?,?,'ai')", (tid, source, ids[source]["nkey"]))
        db.commit()
        ids["topic"] = tid
    return auth_client, ids


class Test入口:
    def test_只统计考点不统计章(self, seeded):
        c, _ids = seeded
        d = c.get("/api/basics/entries").get_json()
        assert d["boards"]["资料分析"] == {"youlu": 1, "sanse": 1, "compare": 1}

    def test_目录树带块数(self, seeded):
        c, ids = seeded
        d = c.get("/api/basics/tree?board=资料分析&source=sanse").get_json()
        leaf = [n for n in d["nodes"] if n["level"] == 2][0]
        assert leaf["title"] == "增长率" and leaf["blocks"] == 2
        assert [n for n in d["nodes"] if n["level"] == 1][0]["kids"] == 1

    def test_板块或来源写错要400(self, seeded):
        c, _ids = seeded
        assert c.get("/api/basics/tree?board=资料分析&source=xx").status_code == 400
        assert c.get("/api/basics/tree?board=没这个板块&source=youlu").status_code == 400


class Test正文:
    def test_带面包屑和三色标记(self, seeded):
        c, ids = seeded
        d = c.get("/api/basics/node/%d" % ids["youlu"]["leaf"]).get_json()
        assert d["title"] == "增长率"
        assert [p["title"] for p in d["path"]] == ["第一章"]
        assert "{{r|增长率}}" in d["blocks"][0]["md"], "三色标记必须原样送到前端上色"
        assert [b["kind"] for b in d["blocks"]] == ["concept", "example"]

    def test_不存在的考点404(self, seeded):
        c, _ids = seeded
        assert c.get("/api/basics/node/999999").status_code == 404


class Test对照:
    def test_两套资料都挂上了(self, seeded):
        c, ids = seeded
        d = c.get("/api/basics/compare?board=资料分析").get_json()
        assert d["topics"] == [{"id": ids["topic"], "name": "增长率", "youlu": 1, "sanse": 1}]
        one = c.get("/api/basics/compare?board=资料分析&topic_id=%d" % ids["topic"]).get_json()
        assert len(one["youlu"]) == 1 and len(one["sanse"]) == 1
        assert one["youlu"][0]["blocks"][0]["md"].startswith("{{r|")

    def test_重解析换了node_id对照仍在(self, seeded):
        """--reparse 会重建 basic_nodes；映射按 nkey 挂，所以对照不该受影响。"""
        c, ids = seeded
        with appmod.app.app_context():
            db = get_db()
            rows = db.execute("SELECT * FROM basic_nodes ORDER BY id").fetchall()
            blocks = db.execute("SELECT * FROM basic_blocks ORDER BY id").fetchall()
            db.execute("DELETE FROM basic_blocks")
            db.execute("DELETE FROM basic_nodes")
            db.execute("UPDATE sqlite_sequence SET seq=seq+500 WHERE name='basic_nodes'")
            old2new = {}
            for r in rows:                       # 原样重建，只是 id 全变了
                cur = db.execute(
                    "INSERT INTO basic_nodes(source_id,source,board,parent_id,level,"
                    "title,sort,page_from,nkey) VALUES(?,?,?,?,?,?,?,?,?)",
                    (r["source_id"], r["source"], r["board"], old2new.get(r["parent_id"]),
                     r["level"], r["title"], r["sort"], r["page_from"], r["nkey"]))
                old2new[r["id"]] = cur.lastrowid
            for b in blocks:
                db.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md,page) "
                           "VALUES(?,?,?,?,?)", (old2new[b["node_id"]], b["sort"],
                                                 b["kind"], b["content_md"], b["page"]))
            db.commit()
        d = c.get("/api/basics/compare?board=资料分析&topic_id=%d" % ids["topic"]).get_json()
        assert len(d["youlu"]) == 1 and len(d["sanse"]) == 1, "重解析后对照不该清空"
        assert d["youlu"][0]["id"] not in (ids["youlu"]["leaf"], ids["sanse"]["leaf"])


class Test学完就练:
    """考点 → 真题：考点存的是 qtype 列表（不给每道题打标签），一个考点可能对应几个题型。"""

    def _seed_q(self, module, qtype, n):
        db = get_db()
        for i in range(n):
            db.execute(
                "INSERT INTO real_questions(module,qtype,stem,options,answer,has_answer,"
                "needs_asset,qhash) VALUES(?,?,?,'[]','A',1,0,?)",
                (module, qtype, "题干%s%d" % (qtype, i), "h-%s-%d" % (qtype, i)))
        db.commit()

    def test_一个考点合并多个题型(self, seeded):
        c, ids = seeded
        with appmod.app.app_context():
            db = get_db()
            db.execute("DELETE FROM real_questions")
            self._seed_q("资料分析", "增长率", 3)
            self._seed_q("资料分析", "基期量", 2)
            self._seed_q("资料分析", "比重", 5)          # 别的考点，不该混进来
            db.execute("UPDATE basic_topics SET qtypes_json=? WHERE id=?",
                       ('["增长率","基期量"]', ids["topic"]))
            db.commit()
        d = c.get("/api/basics/compare?board=资料分析&topic_id=%d" % ids["topic"]).get_json()
        assert d["practice"]["count"] == 5, "两个题型要合起来算"
        assert d["practice"]["qtypes"] == ["增长率", "基期量"]
        r = c.post("/api/real/quiz", json={"mode": "type", "module": "资料分析",
                                           "qtypes": d["practice"]["qtypes"], "n": 5})
        got = {x["qtype"] for x in r.get_json()["items"]}
        assert got == {"增长率", "基期量"}, "不该混进「比重」的题"

    def test_没接题型就不显示练习入口(self, seeded):
        c, ids = seeded
        with appmod.app.app_context():
            db = get_db()
            db.execute("UPDATE basic_topics SET qtypes_json='[]' WHERE id=?", (ids["topic"],))
            db.commit()
        d = c.get("/api/basics/compare?board=资料分析&topic_id=%d" % ids["topic"]).get_json()
        assert d["practice"] is None


class Test解析器不变量:
    """这几条都是 code review 抓出来的：错了不会报错，只会静默丢东西。"""

    def test_nkey不含全局位置(self):
        """解析规则一改、书里前面多一个节点，后面所有节点的对齐不该跟着失效。"""
        import ingest_basics as ib
        before = ib.nkey("资料分析", 2, "增长率", 0, "第一章")
        after = ib.nkey("资料分析", 2, "增长率", 0, "第一章")   # 同父同名第 0 个，位置无关
        assert before == after
        # 同父下真正重名的第二个才换 key
        assert ib.nkey("资料分析", 2, "增长率", 1, "第一章") != before
        # 换了父节点也换 key（不同章下的「一、」不是同一个东西）
        assert ib.nkey("资料分析", 2, "增长率", 0, "第二章") != before

    def test_页眉整行和行内都要滤掉(self):
        import ingest_basics as ib
        assert ib.RE_JUNK.match("   www.youlu.com            优路公考 “公”无不克")
        assert ib.RE_JUNK.match("官方网站:www.youlu.com")
        assert ib.RE_JUNK.match("   -2-")
        assert not ib.RE_JUNK.match("增长率是表述基期量与现期量变化的相对量。")
        # 页眉和页码挤在一行：抠掉页眉后剩下的页码要能被当成页脚滤掉
        line = ib.RE_HDR_INLINE.sub(" ", "官方网站:www.youlu.com                -3-")
        assert ib.RE_JUNK.match(line), "抠完页眉剩下的页码也该滤掉"
        # 正文里出现「优路小结」这种词不能被当页眉整行删掉
        assert not ib.RE_JUNK.match("优路小结")

    def test_目录行要连页码一起认(self):
        import ingest_basics as ib
        assert ib.RE_TOC.search("高频考点1：对称性..........................16")
        assert not ib.RE_TOC.search("②“通过对比”“经与……对比”“相较之下”"), "正文里的省略号不是目录"

    def test_例题按题号一题一块(self):
        """章节演练十道题连成一块的话，跨 6 页，「看原书」只能指到其中一页。"""
        import ingest_basics as ib
        rows = [(7, "章节演练\n1.（2017 国考）从所给四个选项中，选择最合适的一个：\n"
                    "2.（2021上海）下列选项中，符合所给图形变化规律的是："),
                (8, "3.从所给四个选项中，选择最合适的一个填入问号处：")]
        nodes, blocks = ib.parse_youlu([(7, "第一节 位置变化\n" + rows[0][1]), rows[1]],
                                       "判断推理")
        ex = [b for b in blocks if b["kind"] == "example"]
        assert len(ex) == 3, "三道题应切成三块，实得 %d" % len(ex)
        assert ex[-1]["page"] == 8 and ex[0]["page"] == 7

    def test_块的页码是自己的范围(self):
        import ingest_basics as ib
        nodes, blocks = ib.parse_youlu(
            [(3, "第一节 平移\n讲解第一行"), (4, "讲解续行"), (5, "第二节 旋转\n另一节")],
            "判断推理")
        first = blocks[0]
        assert (first["page"], first["page_to"]) == (3, 4), \
            "跨页块要记起止，不能记 flush 那一刻的页（那是下一节的页）"


class Test整章速览:
    """一次把一章的考点连正文全给出来 —— 速记资料印出来就是这个读法。

    盯的是「摊开」这件事本身：章下面的考点、考点自己的子条目、以及挂在章上的
    引子正文，少任何一层界面上都会缺一块，而接口照样返回 200。
    """

    def test_一章的考点连正文一次给全(self, seeded):
        c, ids = seeded
        d = c.get("/api/basics/sweep?nid=%d" % ids["youlu"]["chapter"]).get_json()
        assert d["title"] == "第一章"
        assert [it["title"] for it in d["items"]] == ["增长率"]
        kinds = [b["kind"] for b in d["items"][0]["blocks"]]
        assert kinds == ["concept", "example"]          # 正文和例题都要，顺序照书里的
        assert "增长量/基期" in d["items"][0]["blocks"][0]["md"]

    def test_带上出自哪本书(self, seeded):
        c, ids = seeded
        d = c.get("/api/basics/sweep?nid=%d" % ids["youlu"]["chapter"]).get_json()
        assert d["book"] == "优路讲义"                   # 同名考点在多册里都有，得说清是哪本

    def test_考点的子条目也摊开(self, seeded):
        c, ids = seeded
        with appmod.app.app_context():
            db = get_db()
            sub = db.execute(
                "INSERT INTO basic_nodes(source_id,source,board,parent_id,level,title,"
                "sort,page_from,nkey) SELECT source_id,source,board,?,3,'基期量',0,3,"
                "'资料分析|3|基期量|0|youlu' FROM basic_nodes WHERE id=?",
                (ids["youlu"]["leaf"], ids["youlu"]["leaf"])).lastrowid
            db.execute("INSERT INTO basic_blocks(node_id,sort,kind,content_md,page) "
                       "VALUES(?,0,'concept','基期量=现期量/(1+r)',3)", (sub,))
            db.commit()
        d = c.get("/api/basics/sweep?nid=%d" % ids["youlu"]["chapter"]).get_json()
        kids = d["items"][0]["kids"]
        assert [k["title"] for k in kids] == ["基期量"]
        assert "1+r" in kids[0]["blocks"][0]["md"]

    def test_章节不存在时说清楚而不是给空壳(self, seeded):
        c, _ids = seeded
        r = c.get("/api/basics/sweep?nid=99999")
        assert r.status_code == 404


class Test三层树:
    """社区那条线一个板块摞十几册，树是「书 → 章/节 → 考点」三层。

    早先前端把树写死成两层，2590 个考点全长在第三层 —— 界面上一个都看不到，
    点开章节只有一片空白。接口这边要保证：三层结构原样给出去，
    而板块页的考点计数只数叶子（章节是分组，不是考点）。
    """

    @pytest.fixture
    def deep(self, seeded):
        c, ids = seeded
        with appmod.app.app_context():
            db = get_db()
            # 在「增长率」下面再挂一层考点，把 youlu 那本变成三层
            db.execute(
                "INSERT INTO basic_nodes(source_id,source,board,parent_id,level,title,"
                "sort,page_from,nkey) SELECT source_id,source,board,?,3,'基期量',0,4,"
                "'资料分析#1|3|基期量|0' FROM basic_nodes WHERE id=?",
                (ids["youlu"]["leaf"], ids["youlu"]["leaf"]))
            db.commit()
        return c, ids

    def test_树把三层都给出来(self, deep):
        c, ids = deep
        d = c.get("/api/basics/tree?board=资料分析&source=youlu").get_json()
        lv = sorted({n["level"] for n in d["nodes"]})
        assert lv == [1, 2, 3]
        mid = next(n for n in d["nodes"] if n["level"] == 2)
        assert mid["kids"] == 1          # 前端据此决定摆成分组还是摆成叶子

    def test_考点计数只数叶子(self, deep):
        c, _ids = deep
        d = c.get("/api/basics/entries").get_json()
        # 「增长率」现在是分组不是考点，youlu 这边只剩「基期量」一个叶子
        assert d["boards"]["资料分析"]["youlu"] == 1
