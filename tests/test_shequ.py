"""社区专职工作者（资中县）：判分口径与整卷接口。

这份测试盯的是**最容易静默出错的那两件事**：

  ① 多选题「多选、少选、错选均不得分」。这是从真题原卷标题上抄下来的口径，
     一旦被改成「按比例给分」，做题的人不会看到任何报错，只会练出一个
     和考场不一样的手感 —— 而那正是练题的全部意义所在。
  ② 存疑题不许发出去。源卷是回忆版，答案本身可能是错的；校对闸门没盖 ok 的题
     既不能出现在卷子里，也不能在交卷时被判分。
"""
import json

import pytest

from mods import sqscore


# ---------------------------------------------------------------- 判分口径
class Test判分:
    def test_单选选对得分(self):
        assert sqscore.is_correct("single", "A", "A")
        assert sqscore.score_of("single", "A", "A", 1) == 1.0

    def test_单选选错不得分(self):
        assert not sqscore.is_correct("single", "B", "A")
        assert sqscore.score_of("single", "B", "A", 1) == 0.0

    def test_单选交上来多个字母算没作答(self):
        # **不要挑第一个字母**当他的答案：那等于替用户做决定，而他永远不知道
        assert sqscore.norm_chosen("single", "AB") == ""
        assert not sqscore.is_correct("single", "AB", "A")

    def test_多选全对才得分(self):
        assert sqscore.is_correct("multi", "ABC", "ABC")
        assert sqscore.score_of("multi", "ABC", "ABC", 1) == 1.0

    def test_多选少选一个也是零分(self):
        assert not sqscore.is_correct("multi", "AB", "ABC")
        assert sqscore.score_of("multi", "AB", "ABC", 1) == 0.0

    def test_多选多选一个也是零分(self):
        assert not sqscore.is_correct("multi", "ABCD", "ABC")
        assert sqscore.score_of("multi", "ABCD", "ABC", 1) == 0.0

    def test_多选顺序不影响(self):
        assert sqscore.is_correct("multi", "CBA", "ABC")
        assert sqscore.is_correct("multi", "c b a", "ABC")

    def test_多选能说清漏选和多选(self):
        # 对/错两态说不清「少选」，而少选恰恰是这类题最常见的丢分方式
        miss, extra = sqscore.miss_and_extra("multi", "AB", "ABC")
        assert (miss, extra) == ("C", "")
        miss, extra = sqscore.miss_and_extra("multi", "ABD", "ABC")
        assert (miss, extra) == ("C", "D")

    def test_判断题认得各种写法(self):
        for raw in ("T", "对", "√", "true", "正确"):
            assert sqscore.norm_chosen("judge", raw) == "T"
        for raw in ("F", "错", "×", "false", "错误"):
            assert sqscore.norm_chosen("judge", raw) == "F"

    def test_判断题判错不倒扣(self):
        assert sqscore.score_of("judge", "F", "T", 1) == 0.0

    def test_主观题不在这儿判分(self):
        assert sqscore.score_of("case", "写了一大段", "参考答案", 12) == 0.0

    def test_没作答一律不得分(self):
        for part in ("single", "multi", "judge"):
            assert sqscore.score_of(part, "", "A", 1) == 0.0


class Test能不能发出去:
    def test_只有过闸的才发(self):
        assert sqscore.servable({"verify": "ok"})

    def test_没校对过的不发(self):
        # verify 为空 = 还没校对，一律当存疑看待，**不是「默认可用」**
        assert not sqscore.servable({"verify": ""})
        assert not sqscore.servable({"verify": "doubt"})
        assert not sqscore.servable({"verify": "bad"})

    def test_SQL判据和Python判据同义(self):
        assert sqscore.SERVABLE_SQL == "q.verify='ok'"


# ---------------------------------------------------------------- 校对闸门的判定
class Test校对闸门:
    def _j(self, *a, **kw):
        import verify_shequ
        return verify_shequ.judge(*a, **kw)

    def test_两方独立作答与源一致才过闸(self):
        assert self._j("B", [("甲", "B", ""), ("乙", "B", "")])[0] == "ok"

    def test_只有一方答得出来不许盖章(self):
        # 少了这一条，一方调用失败时闸门会悄悄降级成「单模型说了算」，
        # 还照样报「与源卷一致」—— 比不校对更糟，因为它给了一个并不存在的保证
        v, sug, why = self._j("B", [("甲", "B", ""), ("乙", "", "调用失败")])
        assert v == "doubt" and "两方以上" in why

    def test_多数反对就判存疑并给建议(self):
        v, sug, _ = self._j("B", [("甲", "A", ""), ("乙", "A", "")])
        assert (v, sug) == ("doubt", "A")

    def test_答案分散谁也不占多数就是存疑(self):
        assert self._j("A", [("甲", "B", ""), ("乙", "C", "")])[0] == "doubt"

    def test_本地事实题不许给改答案的建议(self):
        # 招录人数这类只写在当地公告里的数字，模型是在编。实测三方各自「援引公告」
        # 给出三个互相矛盾的数字，而源卷和同一份卷子里的多选题对得上。
        v, sug, why = self._j("A", [("甲", "B", ""), ("乙", "B", "")], local=True)
        assert v == "doubt", "分歧还是要报出来"
        assert sug == "", "本地事实题不该提出改答案的建议"
        assert "源卷更可信" in why

    def test_本地事实题答案分散时也要带上那句提醒(self):
        # 分歧可能来自「多数反对」也可能来自「答案分散」，两条路都得说同一句话；
        # 少说一条，那道题就会带着一个幻觉出来的建议摆在裁决台上
        v, sug, why = self._j("A", [("甲", "B", ""), ("乙", "C", "")], local=True)
        assert (v, sug) == ("doubt", "")
        assert "源卷更可信" in why

    def test_本地事实题一致时照样能过闸(self):
        assert self._j("A", [("甲", "A", ""), ("乙", "A", "")], local=True)[0] == "ok"


# ---------------------------------------------------------------- 接口
@pytest.fixture
def paper(auth_client):
    """造一份两道客观题 + 一道主观题的小卷子，其中一道存疑。"""
    from core import DB
    import sqlite3
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM sq_attempts")
    con.execute("DELETE FROM sq_records")
    con.execute("DELETE FROM sq_questions")
    con.execute("DELETE FROM sq_papers")
    con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region) "
                "VALUES(1,9001,'测试卷.pdf',2025,'招聘','资中县')")
    # **id 要显式写死**：sq_questions.id 是 AUTOINCREMENT，删了重插不会从 1 开始，
    # 下一个用例里 id 就漂成 6..10 了 —— 单跑过、连跑挂，最难查的那种。
    rows = [
        (1, 1, 1, "single", 1, "社区知识", "单选题干", '["甲","乙","丙","丁"]', "A", "", 1, "ok"),
        (2, 2, 1, "multi", 1, "社区知识", "多选题干", '["甲","乙","丙","丁"]', "ABC", "", 1, "ok"),
        (3, 3, 1, "judge", 1, "社区知识", "判断题干", "[]", "T", "", 1, "ok"),
        (4, 4, 1, "single", 2, "社区知识", "存疑题干", '["甲","乙","丙","丁"]', "B", "", 1, "doubt"),
        (5, 5, 1, "case", 1, "社会工作", "案例题面", "[]", "参考答案正文", "", 12, "ok"),
    ]
    for r in rows:
        con.execute("INSERT INTO sq_questions(id,seq,paper_id,part,part_seq,qtype,stem,options,"
                    "answer,explain,score,verify) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", r)
    con.commit()
    con.close()
    return 1


class Test整卷接口:
    def test_模考不带答案出去(self, auth_client, paper):
        d = auth_client.get("/api/shequ/paper/1?mode=exam").get_json()
        assert d["items"], "卷子是空的"
        for it in d["items"]:
            assert "answer" not in it, "模考模式把答案发给前端了，等于让人作弊"

    def test_背题带答案(self, auth_client, paper):
        d = auth_client.get("/api/shequ/paper/1?mode=study").get_json()
        assert all("answer" in it for it in d["items"])

    def test_存疑题不进卷子(self, auth_client, paper):
        d = auth_client.get("/api/shequ/paper/1?mode=study").get_json()
        stems = [it["stem"] for it in d["items"]]
        assert "存疑题干" not in stems, "存疑题被发出去做了"
        assert d["held"] == 1, "没如实报出扣着几道题"

    def test_概览里待裁决数是现算的(self, auth_client, paper):
        # sq_papers.n_doubt 那一列会过期（校对跑到一半、裁决完没回写）。
        # 卡片上「待裁决 N」和「可练 M」摆在一起，读两个来源就会自相矛盾。
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("UPDATE sq_papers SET n_doubt=999 WHERE id=1")   # 故意写脏
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/overview").get_json()
        p = d["papers"][0]
        assert p["n_doubt"] == 1, "读了 sq_papers 存的那一列，会跟 servable 对不上"
        assert p["servable"] == 3, "servable 该只数客观题，跟 n_doubt 同一个分母"

    def test_主观题照发(self, auth_client, paper):
        # 主观题不过校对闸门（没有客观答案可校），但要出现在卷子里
        d = auth_client.get("/api/shequ/paper/1?mode=study").get_json()
        assert any(it["part"] == "case" for it in d["items"])

    def test_交卷按口径判分(self, auth_client, paper):
        r = auth_client.post("/api/shequ/submit", json={
            "paper_id": 1, "mode": "exam", "seconds": 60,
            "answers": {"1": "A", "2": "AB", "3": "T", "5": "我写的答案"},
        }).get_json()
        # 单选对 1 分；多选少选 0 分；判断对 1 分 → 2 分
        assert r["obj_score"] == 2.0, r
        assert r["obj_full"] == 3.0, "满分应该只算过闸的三道客观题"
        assert r["n_sub"] == 1

    def test_交卷时存疑题即使发上来也不判(self, auth_client, paper):
        r = auth_client.post("/api/shequ/submit", json={
            "paper_id": 1, "mode": "exam", "answers": {"4": "B"},
        }).get_json()
        assert r["obj_score"] == 0.0
        assert not [x for x in r["detail"] if x["qid"] == 4]

    def test_多选漏选要说清漏了哪个(self, auth_client, paper):
        r = auth_client.post("/api/shequ/submit", json={
            "paper_id": 1, "mode": "exam", "answers": {"2": "AB"},
        }).get_json()
        got = [x for x in r["detail"] if x["qid"] == 2][0]
        assert got["miss"] == "C" and got["extra"] == ""

    def test_每次作答独立留痕(self, auth_client, paper):
        from core import DB
        import sqlite3
        for chosen in ("B", "A"):
            auth_client.post("/api/shequ/submit", json={
                "paper_id": 1, "mode": "study", "answers": {"1": chosen}})
        con = sqlite3.connect(DB)
        n = con.execute("SELECT COUNT(*) FROM sq_attempts WHERE qid=1").fetchone()[0]
        con.close()
        assert n >= 2, "第二次作答把第一次覆盖了，看不出有没有进步"


class Test资中专项:
    @pytest.fixture
    def facts(self, auth_client):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("DELETE FROM sq_facts")
        con.execute("INSERT INTO sq_facts(grp,k,v,unit,note,src,year,proven,ord) "
                    "VALUES('招聘公告','选聘总名额','72','名','','2026 公告',2026,1,0)")
        con.execute("INSERT INTO sq_facts(grp,k,v,unit,note,src,year,proven,ord) "
                    "VALUES('县情与经济','GDP','383.53','亿元','','统计公报',2025,0,1)")
        con.commit()
        con.close()

    def test_真题考过的那组排在前面(self, auth_client, facts):
        # 8 道本地题全部出自招聘公告参数，没有一道考县情 GDP —— 两档不能混着摆
        d = auth_client.get("/api/shequ/facts").get_json()
        assert d["groups"][0]["grp"] == "招聘公告"
        assert d["groups"][0]["proven"] == 1
        assert d["groups"][-1]["proven"] == 0

    def test_每条都带来源和年份(self, auth_client, facts):
        # 不标年份的本地数据是会过期的假知识
        d = auth_client.get("/api/shequ/facts").get_json()
        for g in d["groups"]:
            for it in g["items"]:
                assert it["src"] and it["year"], "有条目没带来源或年份：%r" % it

    def test_专项卷不混进真题列表(self, auth_client, paper):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region) "
                    "VALUES(9,9009,'资中专项 · 地方必得分',2026,'专项','资中县')")
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/overview").get_json()
        names = [p["name"] for p in d["papers"]]
        assert "资中专项 · 地方必得分" not in names, "专项是生成的练习集，混进去像考过三套卷"


class Test出题构造:
    def test_答案字母是轮流发的(self):
        # 单纯 shuffle 实测偏成 D8/C5/A3/B2，「蒙 D」就能多对几道
        import json as _j
        import build_zizhong as B
        m = _j.load(open("zizhong_meta.json", encoding="utf-8"))
        qs = B.gen_questions(B.facts_of(m), m)
        from collections import Counter
        c = Counter(q["answer"] for q in qs)
        assert max(c.values()) - min(c.values()) <= 1, "答案字母分布不均：%r" % dict(c)

    def test_每道题四个选项互不相同(self):
        import json as _j
        import build_zizhong as B
        m = _j.load(open("zizhong_meta.json", encoding="utf-8"))
        for q in B.gen_questions(B.facts_of(m), m):
            assert len(set(q["options"])) == 4, q["stem"]

    def test_正确答案确实在选项里那一格(self):
        import json as _j
        import build_zizhong as B
        m = _j.load(open("zizhong_meta.json", encoding="utf-8"))
        for q in B.gen_questions(B.facts_of(m), m):
            assert q["options"]["ABCD".index(q["answer"])] is not None


class Test考点树解析:
    """parse_shequ 的三种考点行形态 —— 这批资料一册一个写法，
       改这条正则前必须全量新旧对比（改共用规则的规矩）。"""

    def _p(self, text, title="某某资料.pdf"):
        import ingest_basics as I
        return I.parse_shequ([(1, text)], "社会工作", title)

    def test_书名占第一层(self):
        nodes, _ = self._p("第一章 通用过程\n1、会谈的技巧：倾听。")
        assert nodes[0]["level"] == 1 and nodes[0]["title"] == "某某资料"

    def test_章和考点分别是二三层(self):
        nodes, _ = self._p("第一章 通用过程\n1、会谈的技巧：倾听。")
        lv = {n["level"]: n["title"] for n in nodes}
        assert lv[2].startswith("第一章") and lv[3] == "会谈的技巧"

    def test_冒号后面是正文不是标题(self):
        nodes, blocks = self._p("第一章 通用过程\n1、会谈的技巧：主动介绍自己、倾听。")
        assert [n for n in nodes if n["level"] == 3][0]["title"] == "会谈的技巧"
        assert "主动介绍自己" in blocks[0]["md"]

    def test_序号后面没分隔符也认(self):
        # 社区知识 14 页必背是「4社会工作的重要目标：促进发展。」这种写法
        nodes, _ = self._p("4社会工作的重要目标：促进发展。")
        assert any(n["title"] == "社会工作的重要目标" for n in nodes)

    def test_法条也当考点(self):
        nodes, _ = self._p("第一章 总则\n第一条 为了坚持和加强党对信访工作的全面领导。")
        assert any(n["level"] == 3 and n["title"].startswith("第一条") for n in nodes)

    def test_考点N破折号那种也认(self):
        nodes, _ = self._p("一、总则亮点\n考点 1——紧急情况下的救助义务")
        assert any("紧急情况" in n["title"] for n in nodes)

    def test_年份不会被当成考点(self):
        # 「2020 年 5 月 28 日通过」这种正文行若被当成考点 2020，一页能切出几十个空节点
        nodes, _ = self._p("第一章 概述\n2020 年 5 月 28 日十三届全国人大三次会议通过。")
        assert not [n for n in nodes if n["level"] == 3], [n["title"] for n in nodes]

    def test_部分不会被切成部加分(self):
        nodes, _ = self._p("第一部分 社会工作综合能力\n1、含义：某某。")
        assert [n for n in nodes if n["level"] == 2][0]["title"] == "第一部分 社会工作综合能力"

    def test_没有章的册子自动补一章(self):
        nodes, _ = self._p("1、社区的由来：起源于睦邻运动。")
        assert [n for n in nodes if n["level"] == 2][0]["title"] == "全书"

    def test_长句没冒号时标题取首个短语正文留全(self):
        long = "了解服务对象的来源（主动、转介、外展）和类型及现有与潜在服务对象。"
        nodes, blocks = self._p("第一章 通用过程\n1、" + long)
        t = [n for n in nodes if n["level"] == 3][0]["title"]
        assert len(t) < len(long) and long[:6] in t
        assert long in blocks[0]["md"], "整句必须原样留在正文里，一个字都不能丢"


class Test裁决台:
    def test_体检单只数客观题(self, auth_client, paper):
        # 主观题没有客观答案可校、压根不过这道闸；算进 todo 会显示成
        # 「还有 N 道没校对」，让人以为闸门漏了活
        d = auth_client.get("/api/shequ/doubts").get_json()
        h = d["health"][0]
        assert h["obj"] == 4, "把主观题也数进来了"
        assert h["todo"] == 0

    def test_列出存疑题(self, auth_client, paper):
        d = auth_client.get("/api/shequ/doubts").get_json()
        assert [x for x in d["items"] if x["stem"] == "存疑题干"]

    def test_采信建议答案后就能做了(self, auth_client, paper):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("UPDATE sq_questions SET verify_note=? WHERE id=4",
                    (json.dumps({"suggest": "C"}),))
        con.commit()
        con.close()
        auth_client.post("/api/shequ/doubt/4", json={"act": "accept"})
        d = auth_client.get("/api/shequ/paper/1?mode=study").get_json()
        got = [it for it in d["items"] if it["stem"] == "存疑题干"]
        assert got and got[0]["answer"] == "C", "裁决后答案没改过来"
        assert d["held"] == 0

    def test_判定不能用的题永不发出(self, auth_client, paper):
        auth_client.post("/api/shequ/doubt/4", json={"act": "drop"})
        d = auth_client.get("/api/shequ/paper/1?mode=study").get_json()
        assert not [it for it in d["items"] if it["stem"] == "存疑题干"]
