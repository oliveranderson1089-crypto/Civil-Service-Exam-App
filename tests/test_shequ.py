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

    def test_题库册子不混进真题列表(self, auth_client, paper):
        # 只排除「专项」而没排除后来加的「题库」时，75 份练习册全跑进了真题列表。
        # 所以改成白名单：将来再加什么 kind 都不会漏进来。
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region) "
                    "VALUES(8,9008,'社区概论练习1',0,'题库','通用')")
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/overview").get_json()
        assert "社区概论练习1" not in [p["name"] for p in d["papers"]]

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


class Test主观题采分点:
    """社区案例的采分点是**规则从参考答案拆的**（参考答案本来就是分点写的），
       不像申论要靠 AI 从材料里标。所以这套拆分必须钉死。"""

    def _sp(self, text, full=12):
        from mods import sqgrade
        return sqgrade.split_points(text, full)

    def test_编号式参考答案拆得出点(self):
        pts = self._sp("1. 安抚接待：分别约谈双方。\n2. 政策宣讲：讲解补贴政策。\n"
                       "3. 搭建平台：召开议事会。")
        assert [p["point"] for p in pts] == ["安抚接待", "政策宣讲", "搭建平台"]

    def test_无编号的短标题加冒号也拆得出(self):
        # 2025 卷那两道就是这种写法
        pts = self._sp("分类建档：建立台账。\n逐项处置：逐条处理。\n长效机制：每日巡查。")
        assert [p["point"] for p in pts] == ["分类建档", "逐项处置", "长效机制"]

    def test_分值加起来正好是满分(self):
        for n, full in ((3, 12), (4, 13), (5, 12), (5, 13)):
            text = "\n".join("%d. 点%d：内容。" % (i + 1, i + 1) for i in range(n))
            pts = self._sp(text, full)
            assert abs(sum(p["score"] for p in pts) - full) < 0.01, (n, full)

    def test_子要素归到上一个点不单独算点(self):
        pts = self._sp("分类建档：建台账。\n逐项处置：\n（1）用电隐患：换线路。\n"
                       "（2）占道经营：联合整治。\n长效机制：每日巡查。")
        assert len(pts) == 3
        assert "用电隐患" in pts[1]["detail"] and "占道经营" in pts[1]["detail"]

    def test_折行的续行接到子要素后面(self):
        # PDF 折行会把「…张贴安全」和「提示，纳入巡查」拆成两行；接错地方
        # 会让点的正文读起来前言不搭后语
        pts = self._sp("逐项处置：\n（1）用电隐患：上门更换线路，张贴安全\n提示，纳入每周巡查。\n"
                       "长效机制：每日巡查。")
        assert "张贴安全提示，纳入每周巡查" in pts[0]["detail"]

    def test_拆不动就返回空不硬凑(self):
        # 硬凑一个点会把满分全压上去，比不判分更糟
        assert self._sp("这是一整段没有分点的参考答案，读起来很顺但拆不出采分点。") == []

    def test_骨架按题面判两类(self):
        from mods.sqgrade import skeleton_of
        assert skeleton_of("排查发现 3 项问题：占道经营、邻里纠纷、多次报警") == "grid"
        assert skeleton_of("社区青年小李，失业半年，自我否定，求助社区") == "case"

    def test_骨架判不出来就不给(self):
        # 给错骨架比不给更误导
        from mods.sqgrade import skeleton_of
        assert skeleton_of("请谈谈你对社区工作的理解") is None

    def test_公文按结构部件给分且合计十五分(self):
        from mods.sqgrade import gongwen_points
        pts = gongwen_points()
        assert len(pts) == 6 and abs(sum(p["score"] for p in pts) - 15) < 0.01
        assert any("落款" in p["point"] for p in pts)


class Test主观题判定合并:
    def _m(self, raw):
        from mods import sqgrade
        pts = [{"point": "甲", "detail": "d1", "score": 4},
               {"point": "乙", "detail": "d2", "score": 4}]
        return sqgrade.merge(pts, raw)

    def test_沾边给一半分(self):
        assert self._m([{"verdict": "partial"}, {"verdict": "hit"}])[0]["got"] == 2

    def test_不采信AI报的分数(self):
        # AI 报的 got 经常和它自己的 verdict 对不上，分数一律由 verdict 算
        r = self._m([{"verdict": "hit", "got": 999}, {"verdict": "miss", "got": 4}])
        assert r[0]["got"] == 4 and r[1]["got"] == 0

    def test_AI少给几条时按miss补齐(self):
        # 绝不因为 AI 漏了一条就少扣分
        r = self._m([{"verdict": "hit"}])
        assert len(r) == 2 and r[1]["verdict"] == "miss"

    def test_认不得的判定当miss(self):
        assert self._m([{"verdict": "很好"}, {}])[0]["verdict"] == "miss"

    def test_总分按逐点加起来(self):
        from mods.sqgrade import total_of
        assert total_of(self._m([{"verdict": "hit"}, {"verdict": "partial"}])) == 6


class Test题库对齐:
    """练习册的题干和答案分处两地，**错位一格就是整册答案全错，而且题数照样对得上**。
       这几条把踩过的坑钉住。"""

    def _p(self, text, ans=None):
        import ingest_sqbank as B
        return B.parse_bank(text, ans)

    def test_题号每个题型重编时不许串答案(self):
        # 单选第 1 题和多选第 1 题都叫「1」，只按题号做键会让多选拿到单选的答案
        text = ("一、单选题\n1.甲问题（ ）\nA.甲1\nB.甲2\n"
                "二、多选题\n1.乙问题（ ）\nA.乙1\nB.乙2\nC.乙3\n"
                "参考答案\n一、单选题\n1.答案：A\n二、多选题\n1.答案：BC\n")
        items, rep = self._p(text)
        got = {i["part"]: i["answer"] for i in items}
        assert got == {"single": "A", "multi": "BC"}, got

    def test_答案超出选项范围的题不要(self):
        # 三个选项的题答案是 D —— 多半是答案区错位，这种题一道都不能收
        text = ("一、单选题\n1.问题（ ）\nA.甲\nB.乙\nC.丙\n"
                "参考答案\n一、单选题\n1.答案：D\n")
        items, rep = self._p(text)
        assert items == [] and rep["n_ok"] == 0

    def test_一行多个答案要全部认出来(self):
        # `1.E  2.D  3.A` 这种排版；为解析册加的「数字+字母+空格」模式会劫走它，
        # 实测把一册 93 条答案吃成 22 条、对齐率 99%→23%，所以多对要先试
        text = ("一、单选题\n1.甲（ ）\nA.a\nB.b\n2.乙（ ）\nA.a\nB.b\n3.丙（ ）\nA.a\nB.b\n"
                "参考答案\n一、单选题\n1.A    2.B   3.A\n")
        items, _ = self._p(text)
        assert [i["answer"] for i in items] == ["A", "B", "A"]

    def test_判断题按选项文字折成对错(self):
        # 册子印成「A.正确 / B.错误」，答案给 A/B。按字母顺序猜会在反着印的册子上全判反
        text = ("三、判断题\n1.人口是社区发展的基础。（ ）\nA.正确\nB.错误\n"
                "2.社区就是社会。（ ）\nA.错误\nB.正确\n"
                "参考答案\n三、判断题\n1.答案：B\n2.答案：A\n")
        items, _ = self._p(text)
        assert [i["answer"] for i in items] == ["F", "F"], [i["answer"] for i in items]
        assert all(i["options"] == [] for i in items), "判断题不该带选项"

    def test_共享题干那节整节丢掉(self):
        # 几道题共用一段材料，单独抠出来是残缺的，收了就是发一道做不了的题
        text = ("一、单选题\n1.甲（ ）\nA.a\nB.b\n"
                "四、共享题干题\n1.乙（ ）\nA.a\nB.b\n"
                "参考答案\n一、单选题\n1.答案：A\n四、共享题干题\n1.答案：B\n")
        items, _ = self._p(text)
        assert len(items) == 1 and items[0]["stem"].startswith("甲")

    def test_跨册对齐要按章加题型加题号(self):
        q = ("第一章 总则\n一、单选题\n1.甲（ ）\nA.a\nB.b\n"
             "第二章 分则\n一、单选题\n1.乙（ ）\nA.a\nB.b\n")
        a = ("第一章 总则\n一、单选题\n1.答案：A\n"
             "第二章 分则\n一、单选题\n1.答案：B\n")
        items, _ = self._p(q, a)
        assert [i["answer"] for i in items] == ["A", "B"]

    def test_对齐率算的是可用比例(self):
        text = ("一、单选题\n1.甲（ ）\nA.a\nB.b\n2.乙（ ）\nA.a\nB.b\n"
                "参考答案\n一、单选题\n1.答案：A\n")
        _, rep = self._p(text)
        assert rep["n_all"] == 2 and rep["n_ok"] == 1 and abs(rep["rate"] - 0.5) < 0.01


class Test备考方向:
    """两条线并存：切换只是视图开关，**数据一条不删**（用户明说考完社区还要接着考公）。"""

    def _ln(self):
        from mods import line
        return line

    def test_两条线的板块零交集(self):
        L = self._ln()
        assert not (L.line_boards(L.GONGKAO) & L.line_boards(L.SHEQU))

    def test_手打的板块名按名字归队(self):
        # 错题本里有用户自己打的名：一律「两边都显示」的话，社区线里会混进行测错题
        L = self._ln()
        assert L.guess_line("行测·数量关系") == L.GONGKAO
        assert L.guess_line("言语理解") == L.GONGKAO          # 标准名的前缀
        assert L.guess_line("社会工作实务（社区工作者）") == L.SHEQU

    def test_认不出的板块两边都留(self):
        # 因为我们的分类不认识它就把人家记的错题藏起来，是最糟的做法
        L = self._ln()
        assert L.guess_line("我自己瞎起的名字") == ""
        assert L.in_line("我自己瞎起的名字", L.GONGKAO)
        assert L.in_line("我自己瞎起的名字", L.SHEQU)

    def test_SQL判据和Python判据同义(self, auth_client):
        # 两处判据说不到一块去时，列表条数和统计数字会对不上，而且不报错
        from core import DB
        import sqlite3
        L = self._ln()
        con = sqlite3.connect(DB)
        con.execute("DELETE FROM wrong_questions")
        for b in ("常识判断", "社区知识", "行测·数量关系", "社会工作实务（社区工作者）", "怪名字"):
            con.execute("INSERT INTO wrong_questions(user_id,board,question) VALUES(1,?,'x')", (b,))
        con.commit()
        for ln in (L.GONGKAO, L.SHEQU):
            frag, args = L.sql_filter("board", ln, con)
            got = {r[0] for r in con.execute(
                "SELECT board FROM wrong_questions WHERE " + frag, args)}
            want = {b for b in ("常识判断", "社区知识", "行测·数量关系",
                                "社会工作实务（社区工作者）", "怪名字") if L.in_line(b, ln)}
            assert got == want, (ln, got, want)
        con.close()

    def test_切换只改一个字段不动数据(self, auth_client):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        before = con.execute("SELECT COUNT(*) FROM wrong_questions").fetchone()[0]
        auth_client.post("/api/me/line", json={"line": "shequ"})
        auth_client.post("/api/me/line", json={"line": "gongkao"})
        after = con.execute("SELECT COUNT(*) FROM wrong_questions").fetchone()[0]
        con.close()
        assert before == after, "切换方向动了数据"

    def test_不认识的方向名要拒绝(self, auth_client):
        r = auth_client.post("/api/me/line", json={"line": "随便写的"})
        assert r.status_code == 400


class Test题库混排:
    """这批册子是**混排**的：答案有三种写法、选项有三种摆法。
       靠对齐率判断该不该收，不靠文件名猜格式。"""

    def _i(self, text):
        import ingest_sqbank as B
        return B.parse_inline(text)

    def test_答案跟在题后面(self):
        items, rep = self._i("1.甲问题（ ）\nA.a\nB.b\nC.c\nD.d\n答案： C\n")
        assert items and items[0]["answer"] == "C"

    def test_方括号答案后面跟着整段解析(self):
        # `【答案】B。A 项错误，…` —— 要求字母后面是句号/顿号，
        # 否则和正文里的「B 项正确」分不开
        items, _ = self._i("1.甲（ ）\nA.a\nB.b\nC.c\nD.d\n"
                           "【答案】B。A 项错误，某某；B 项正确，某某。\n")
        assert items and items[0]["answer"] == "B"

    def test_四个选项挤在一行(self):
        items, _ = self._i("1.下列表述正确的有几项?\nA.2 项 B. 3 项 C. 4 项 D. 5 项\n答案： C\n")
        assert items and items[0]["options"] == ["2 项", "3 项", "4 项", "5 项"]

    def test_选项混在题干那一行(self):
        items, _ = self._i("1、社会工作是一种（）。 A 自发助人活动 B 营利活动 "
                           "C 专业助人活动 D 其他活动\n正确答案：C\n")
        assert items and len(items[0]["options"]) == 4
        assert "社会工作是一种" in items[0]["stem"]

    def test_多选按答案字母个数回判题型(self):
        # 这几份押题里单选多选混排，章节标题靠不住
        items, _ = self._i("一、单选题\n1.甲（ ）\nA.a\nB.b\nC.c\nD.d\n答案： ABC\n")
        assert items[0]["part"] == "multi"

    def test_答案越界的题照样不要(self):
        items, rep = self._i("1.甲（ ）\nA.a\nB.b\n答案： D\n")
        assert items == [] and rep["n_ok"] == 0


class TestOCR文本修复:
    """扫描件 OCR 出来的题册，比文字层多两道加工：还原被认错的字符、切开双栏。
       顺序反了或漏了任一步，都会静默产出选项残缺的题。"""

    def _r(self, text):
        import ingest_sqbank as B
        return B.ocr_repair(text).splitlines()

    def test_选项C被认成5要还原(self):
        # 实测千题斩全书 799 行以「5.」开头，其中 748 行其实是选项 C
        out = self._r("A. 一至三年\n5. 三至七年                    D.五至七年")
        assert any(l.strip().startswith("C.") for l in out), out

    def test_真的第五题不能被改成C(self):
        out = self._r("上一行是正文。\n5. 社区的构成要素有哪些？")
        assert any(l.strip().startswith("5.") for l in out), out

    def test_双栏一行两个选项要切开(self):
        out = self._r("A.支持                                B. 同感")
        assert [l.strip() for l in out] == ["A.支持", "B. 同感"]

    def test_题干后面跟选项时不切(self):
        # 「题干  D.某某」不能被当成双栏，否则题干会被截断
        out = self._r("下列哪项属于社区服务？  D.养老助餐")
        assert len(out) == 1

    def test_还原C必须在切双栏之前(self):
        # 顺序反了：左半是「5. 面质」时守卫认不出它是选项，整行切不开，右边的 D 也丢
        out = self._r("5. 面质                                   D. 自我表露")
        assert sum(1 for l in out if l.strip()[:2] in ("C.", "D.")) == 2, out


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


# ---------------------------------------------------------------- 模拟卷
class Test模拟卷:
    """模拟卷是**整卷、但不是真题**。这一组盯的是三件会静默出错的事：
       ① 它别混进真题列表；② 缺口要如实报；③ 答案区串行的册子一份都不许收。"""

    def test_模拟卷不混进真题列表(self, auth_client, paper):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region,n_obj,n_bad) "
                    "VALUES(11,9011,'2025年社区工作者考试模拟试题及答案 (1)',0,'模拟','通用',66,27)")
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/overview").get_json()
        assert "2025年社区工作者考试模拟试题及答案 (1)" not in [p["name"] for p in d["papers"]], \
            "模拟卷跑进真题列表了 —— 真题一共只有两套，混着摆像考过七八回"
        assert [p["name"] for p in d["mocks"]] == ["2025年社区工作者考试模拟试题及答案 (1)"]

    def test_模拟卷要如实报出缺口(self, auth_client, paper):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region,n_obj,n_bad) "
                    "VALUES(12,9012,'模拟卷甲',0,'模拟','通用',37,59)")
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/overview").get_json()
        assert d["mocks"][0]["n_bad"] == 59, \
            "只报收下的那些题，卷子看着是满的，人会以为自己做完了一整套"

    def test_整卷才叫模拟卷_题册不算(self):
        import ingest_sqbank as B
        assert B.kind_of("2025年社区工作者考试模拟试题及答案 (1).pdf") == "模拟"
        assert B.kind_of("2025年社区工作者-社会工作法规与政策押题试卷及答案.pdf") == "押题"
        # 「1月份时政押题」是一本题库、不是一套卷。认不出就当题册，别摆成整卷骗人去做
        assert B.kind_of("1月份时政押题.pdf") == "题库"
        assert B.kind_of("社区概论练习1.pdf") == "题库"

    def test_答案区串行的册子一道都不收(self):
        """闸门要按**掉下来的原因**判，不是按一个总分数判。

        OCR 把选项吃了 → 丢题，可以忍；答案区串行 → 发错题，一道都不能忍。
        这两件事在「对齐率」上长得一模一样，所以另算一个「错位嫌疑率」。
        """
        import ingest_sqbank as B
        bad = {"n_all": 100, "bad": [({}, "答案 D 超出本题 3 个选项的范围")] * 19}
        ok = {"n_all": 100, "bad": [({}, "选项少于 2 个")] * 40}
        assert B._misalign(bad) > 0.05, "答案串行的册子没被算成高危"
        assert B._misalign(ok) == 0.0, "OCR 掉字被误算成答案串行，好卷子会被整份扔掉"

    def test_题号回到1就是换了题型段(self):
        """扫描件常把「二、多项选择题」那行页脚粘掉。没有这条退路的话，
           多选的 1~40 会去撞单选已占的号，setdefault 让先来的赢，
           **整段多选一条答案都取不到** —— 实测一套卷丢了 32 道。"""
        import ingest_sqbank as B
        tail = "参考答案\n一、单项选择题\n" \
               + "\n".join("%d. A %d. B" % (i, i + 1) for i in range(1, 60, 2)) \
               + "\n1. ABDE 2. ABCE 3. BCD 4. ABCE\n"
        got = B._scan_answers(tail)
        assert got.get(("", "multi", 1)) == "ABDE", "多选段没被认出来：%r" % (
            [k for k in got if k[1] == "multi"][:5])
        assert got.get(("", "single", 1)) == "A", "单选段被换段规则误伤了"

    def test_题号被OCR认错不算换段(self):
        """同一册里「28.」被认成「98.」，下一条 29 比 98 小。按「只要变小就换段」
           写会在这儿凭空劈出一段来 —— 所以判据是「回到 1」，不是「变小」。"""
        import ingest_sqbank as B
        tail = "参考答案\n一、单项选择题\n25. D 26. B 27. A 98. D 29. A 30. B\n"
        got = B._scan_answers(tail)
        assert got.get(("", "single", 29)) == "A", "被 OCR 错号骗着劈段了：%r" % got

    def test_一段答案的题型按答案形状判(self):
        import ingest_sqbank as B
        assert B._kind_by_shape(["ABD", "BCD", "AC", "ABCE"]) == "multi"
        assert B._kind_by_shape(["T", "F", "T", "F"]) == "judge"
        assert B._kind_by_shape(["A", "B", "C", "D"]) == "single"


# ---------------------------------------------------------------- 主观题扩容
class Test主观题分档:
    """外省题库带来了一百多道主观题。它们能用，但**不能冒充资中考情** ——
       简答论述这个题型资中两套原卷上根本没有。"""

    def test_简答论述不算在四十分里(self):
        assert "short" not in sqscore.PAPER_PARTS, \
            "简答论述混进了卷面题型，会让人以为资中考简答"
        assert "short" in sqscore.SUB_PARTS, "但它得能当主观题批改"

    def test_题型清单只有一份(self):
        # SQL 里手写 IN ('case','gongwen') 的地方，加了题型就会有的认有的不认
        assert sqscore.sql_in(("case", "gongwen")) == "('case','gongwen')"

    def test_主观题按来源分档(self, auth_client, paper):
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region) "
                    "VALUES(13,NULL,'近五年多省份主观题真题题库',0,'主观题库','通用')")
        for seq, (qid, part, stem) in enumerate(
                ((21, "case", "外省案例题面"), (22, "short", "简答题面")), 1):
            con.execute("INSERT INTO sq_questions(id,seq,paper_id,part,part_seq,qtype,stem,"
                        "options,answer,explain,score,verify) "
                        "VALUES(?,?,13,?,1,'社会工作',?,'','1. 甲\n2. 乙','',12,'ok')",
                        (qid, seq, part, stem))
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/subjective").get_json()
        by = {it["stem"]: it for it in d["items"]}
        assert by["案例题面"]["group"] == "real"
        assert by["外省案例题面"]["group"] == "offsite"
        assert by["简答题面"]["group"] == "short"
        assert [g["key"] for g in d["groups"]] == ["real", "offsite", "short"]

    def test_没年份的题不许显示成N年真题(self, auth_client, paper):
        # year=0 照原样渲染会变成「0 年真题」，看着像资中 0 年考过
        from core import DB
        import sqlite3
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO sq_papers(id,file_id,name,year,kind,region) "
                    "VALUES(14,NULL,'近五年多省份主观题真题题库',0,'主观题库','通用')")
        con.execute("INSERT INTO sq_questions(id,seq,paper_id,part,part_seq,qtype,stem,"
                    "options,answer,explain,score,verify) "
                    "VALUES(23,1,14,'case',1,'社会工作','外省题面','','1. 甲\n2. 乙','',12,'ok')")
        con.commit()
        con.close()
        d = auth_client.get("/api/shequ/subjective").get_json()
        it = [x for x in d["items"] if x["stem"] == "外省题面"][0]
        assert not it["year"] and it["src"], "没年份时得说得出它出自哪本册子"


class Test主观题入库:
    def test_两本册子按分节和题号对齐(self):
        """题干在一本、答案在另一本。**只按题号做键**的话，案例分析第 1 题
           会拿到简答论述第 1 题的答案 —— 题数照样对得上，答案全错。"""
        import ingest_sqsub as S
        q = ("简答、论述题真题题库\n1、简答题一问，题面也要写够十五个字才不会被当成 OCR 吃了题面\n2、简答题二问，题面也要写够十五个字才不会被当成 OCR 吃了题面\n"
             "案例分析题真题题库\n1、案例一的题面写得长一些够长了吧\n")
        a = ("简答、论述题题库参考答案\n1、【参考答案】\n简答一的答案正文，这里要写够三十个字才收得下来，不然会被当成没抠全而丢掉\n"
             "2、【参考答案】\n简答二的答案正文，这里要写够三十个字才收得下来，不然会被当成没抠全而丢掉\n"
             "案例分析题题库参考答案\n1、【参考答案】\n案例一的答案正文，这里要写够三十个字才收得下来，不然会被当成没抠全而丢掉\n")
        merged, drop, orphan = S.scan_pair(q, a)
        assert merged[("案例分析", 1)]["answer"].startswith("案例一的答案"), \
            "案例第 1 题拿到了简答第 1 题的答案 —— 这就是错位"
        assert merged[("案例分析", 1)]["part"] == "case"
        assert merged[("简答", 1)]["part"] == "short"

    def test_整节没答案就整节不收(self):
        import ingest_sqsub as S
        q = "写作真题题库\n1、写一篇议论文题面够长了吗应该够了吧\n"
        merged, drop, orphan = S.scan_pair(q, "写作题题库参考答案\n")
        assert not merged, "把没有参考答案的题发出去了"
        assert drop and "没有参考答案" in drop[0][1]

    def test_OCR认花的条目号要还原(self):
        import ingest_sqsub as S
        got = S.ocr_points("(1T)第一条\n(2)第二条\n(4第四条")
        assert got.splitlines()[0].startswith("(1)")
        assert got.splitlines()[2].startswith("(4)")

    def test_句中的圈码不许凭空补号(self):
        """行首的圈码是采分点边界、按顺序补号是合理的；句中那种
           （`包括: @家庭矛盾，@教育方式`）补号就是在编数字了。"""
        import ingest_sqsub as S
        got = S.ocr_points("困境主要有: @家庭矛盾，@教育方式不当")
        assert "·家庭矛盾" in got and "(1)" not in got

    def test_顶层括号编号要提成采分点(self):
        """sqgrade 把「（N）」当子要素，那条规则是为资中真题写的、没错；
           外省这批答案顶层就是用 (1)(2)(3) 编的，不提的话一个点都拆不出来。"""
        import ingest_sqsub as S
        from mods import sqgrade
        raw = "作为社区工作者，我将:\n(1)召集业主大会。\n(2)制定居民公约。\n(3)及时公示信息。"
        assert not sqgrade.split_points(raw, 12), "前提变了，这个用例要重写"
        assert len(sqgrade.split_points(S.promote_points(raw), 12)) == 3

    def test_已有顶层编号时不动人家的层级(self):
        import ingest_sqsub as S
        raw = "1. 接案:\n(1)倾听\n(2)建立信任\n2. 预估:\n(1)核心问题"
        assert S.promote_points(raw) == raw, "把带层级的答案压平了"

    def test_两个解析器对同一份输入给同样的选项(self):
        """「四个选项挤一行」的修复原先只写在 parse_inline 里，parse_bank 没有。

        同族的两条解析路径（答案在卷末 / 答案跟在题后）**必须吃同一份修复** ——
        少一处的下场不是报错，是那一路把好题判成「选项少于 2 个」，
        报出来看着像题册残缺，而不像我们少做了一步。
        """
        import ingest_sqbank as B
        body = "1.管仲辅佐（  ）成为春秋首霸。\nA.晋文公 B.楚庄王 C.齐桓公 D.秦穆公\n"
        a, _ = B.parse_bank(body + "参考答案\n一、单项选择题\n1. C\n")
        b, _ = B.parse_inline(body + "答案：C\n")
        assert a and b, "两条路各自都得解析得出来：%r / %r" % (a, b)
        assert a[0]["options"] == b[0]["options"] == ["晋文公", "楚庄王", "齐桓公", "秦穆公"], \
            "两个解析器给出的选项不一样：%r vs %r" % (a[0]["options"], b[0]["options"])

    def test_选项开头的残标点要削掉(self):
        # 原卷印的是「A、澄清」，OCR 认成「A，澄清」——「，」不在分隔符里，
        # 于是被当成正文留下来，界面上就是「，澄清」。实测占模拟卷选项的 16%
        import ingest_sqbank as B
        items = [{"stem": "题干", "options": ["，澄清", "， 倾听", "同感"], "no": 1}]
        B.repair_options(items)
        assert items[0]["options"] == ["澄清", "倾听", "同感"]
