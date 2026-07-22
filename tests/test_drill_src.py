"""专项练的**题源开关**：真题练习 / AI 出题 / 混合。

这不是两套功能，是同一个板块下的两个题源：
  real —— 答案权威、风格 100% 真实，但就那么几千道，做完不会再有
  ai   —— 无限量、考点可控，风格靠 realprofile 那套画像往真题上对齐
  mix  —— 真题优先填，不够的用 ai 补

真题模式**没有 easy/mid/real 三档**：真题不带难度标签，硬套是假的
（原先「考场真实」这一档发的其实是 AI 题，名不副实）。改成按年份筛。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mods.drill as D  # noqa: E402

OPTS = json.dumps(["甲说法", "乙说法", "丙说法", "丁说法"], ensure_ascii=False)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(D, "uid", lambda: 1)      # 取题要按「我做过没」排序
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE real_questions(id INTEGER PRIMARY KEY, module TEXT, qtype TEXT,
            stem TEXT, material TEXT, options TEXT, answer TEXT, explain TEXT,
            has_answer INT, needs_asset INT, year_max INT);
        CREATE TABLE real_explains(qid INT, answer TEXT, qtype TEXT, agree INT,
            keypoint TEXT, steps TEXT, tip TEXT);
        CREATE TABLE real_attempts(id INTEGER PRIMARY KEY, user_id INT, qid INT,
            choice TEXT, correct INT, seconds REAL);
        CREATE TABLE real_figs(id INTEGER PRIMARY KEY, qid INT, ord INT, sha TEXT, ext TEXT);
        CREATE TABLE drill_bank(id INTEGER PRIMARY KEY, board TEXT, qtype TEXT, level TEXT,
            q TEXT, options TEXT, answer TEXT, explain TEXT, tip TEXT, source TEXT,
            sig TEXT, agree TEXT);
    """)
    return con


def _real(con, qid, qtype="语境分析", module="言语理解与表达", year=2024, material="",
          answer="A", explain=""):
    con.execute("INSERT INTO real_questions VALUES(?,?,?,?,?,?,?,?,1,0,?)",
                (qid, module, qtype, "真题题干%d" % qid, material, OPTS, answer, explain, year))


def _bank(con, board, qtype, n, level="mid"):
    for i in range(n):
        con.execute("INSERT INTO drill_bank(board,qtype,level,q,options,answer,explain,tip,"
                    "source,sig,agree) VALUES(?,?,?,?,?,'B','解析','技巧','来源',?, '1')",
                    (board, qtype, level, "AI题干%d" % i, OPTS, "sig%d" % i))


class TestSrc:
    def test_real只发真题(self, db):
        for i in range(6):
            _real(db, i + 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real")
        assert len(got) == 4 and {x["src"] for x in got} == {"real"}
        assert all(x["real_id"] for x in got), "少了 real_id，交卷时没法写 real_attempts"

    def test_ai不发真题(self, db):
        for i in range(6):
            _real(db, i + 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "ai")
        assert {x["src"] for x in got} == {"ai"}

    def test_mix真题优先不够才用AI补(self, db):
        """毛泽东思想这类题型真题只有个位数，正是 mix 的用武之地。"""
        for i in range(2):
            _real(db, i + 1, qtype="毛泽东思想", module="常识判断")
        _bank(db, "政治理论", "毛泽东思想", 6)
        got = D._drill_gen(db, "政治理论", "毛泽东思想", 5, "mid", "mix")
        kinds = [x["src"] for x in got]
        assert kinds.count("real") == 2 and kinds.count("ai") == 3
        assert kinds[:2] == ["real", "real"], "真题没排在前面"

    def test_真题不够时mix不静默降级(self, db):
        """每道题都带 src，调用方能看出哪道是真题、哪道是 AI 出的。"""
        _real(db, 1)
        _bank(db, "言语理解与表达", "语境分析", 6)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "mix")
        assert all("src" in x for x in got)


class TestOrder:
    def test_没做过的排前面(self, db):
        for i in range(1, 5):
            _real(db, i)
        db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct) VALUES(1,1,'A',1)")
        db.execute("INSERT INTO real_attempts(user_id,qid,choice,correct) VALUES(1,2,'B',0)")
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real")
        order = [x["real_id"] for x in got]
        assert set(order[:2]) == {3, 4}, "做过的题排到前面去了：%s" % order
        assert order[2] == 2, "做错过的应该排在做对过的前面：%s" % order

    def test_年份筛选(self, db):
        _real(db, 1, year=2018)
        _real(db, 2, year=2024)
        got = D._drill_gen(db, "言语理解与表达", "语境分析", 4, "mid", "real", year_min=2021)
        assert [x["real_id"] for x in got] == [2]


class TestPayload:
    def test_材料是纯文本原样带出(self, db):
        """真题的材料是一段文字，不是 figgen 那种 {type:'table'} 结构体 ——
           前端 dtMaterial 要能认字符串，否则会渲染出一张空图。"""
        _real(db, 1, qtype="比重", module="资料分析", material="2023 年甲市 GDP 为…")
        got = D._drill_gen(db, "资料分析", "比重", 1, "mid", "real")
        assert got[0]["material"] == "2023 年甲市 GDP 为…"

    def test_材料是字符串None时当没有(self, db):
        _real(db, 1, material="None")
        assert D._drill_gen(db, "言语理解与表达", "语境分析", 1, "mid", "real")[0]["material"] == ""

    def test_没有真题表也不崩(self, monkeypatch):
        """新库还没导真题，专项练本身照常能用。"""
        monkeypatch.setattr(D, "uid", lambda: 1)
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        assert D._real_take(con, "言语理解与表达", "语境分析", 4) == []
        assert D._real_counts(con, "言语理解与表达") == {}


class TestCount:
    def test_存量少的要报出来给前端置灰(self, db):
        """政治理论四个题型真题只有个位数、文章阅读一道都没有 ——
           这种就该明说「没有」，不该假装有。"""
        for i in range(3):
            _real(db, i + 1)
        assert D._real_counts(db, "言语理解与表达").get("语境分析") == 3
        assert 3 < D._REAL_SRC_MIN, "阈值定得太低，两三道题刷两轮就重复了"

    def test_存量要跟着年份筛(self, db):
        """前端切到「近 3 年」后，卡片上不能还写着全量道数——数字不能撒谎。"""
        _real(db, 1, year=2018)
        _real(db, 2, year=2024)
        assert D._real_counts(db, "言语理解与表达").get("语境分析") == 2
        assert D._real_counts(db, "言语理解与表达", 2021).get("语境分析") == 1


class TestExplain:
    def test_解析别缩水成一句keypoint(self, db):
        """实测定义判断 628 道里 562 道带完整原卷解析，re.steps 也有。
           只发 keypoint 的话，同一道题在真题模块是完整解析、在专项练里只剩一句。"""
        _real(db, 1)
        db.execute("INSERT INTO real_explains(qid,answer,agree,keypoint,steps) "
                   "VALUES(1,'A',1,'抓住定义要件',?)",
                   (json.dumps(["第一步：找主体", "第二步：比对行为"], ensure_ascii=False),))
        ex = D._drill_gen(db, "言语理解与表达", "语境分析", 1, "mid", "real")[0]["explain"]
        assert "抓住定义要件" in ex and "第一步：找主体" in ex and "第二步：比对行为" in ex

    def test_没有结构化解析就用原卷那段兜底(self, db):
        _real(db, 1, explain="第一步，看提问方式，本题属于选非题。")
        assert "选非题" in D._drill_gen(db, "言语理解与表达", "语境分析", 1, "mid", "real")[0]["explain"]

    def test_答案取不出ABCD的题不发(self, db):
        """drill_done 判分时 your == "" 恒为 False，用户做对也算错还要进错题本。"""
        _real(db, 1, answer="")
        db.execute("INSERT INTO real_explains(qid,answer,agree) VALUES(1,'',1)")
        assert D._drill_gen(db, "言语理解与表达", "语境分析", 1, "mid", "real") == []


class TestWrongq:
    """真题带**纯文本**材料时错题本会不会崩 —— 这条正是线上必现的 500。"""

    def _wq(self, db):
        # src_kind/src_key 是错题的**来源身份**（做题界面靠它认出「这题已经收过了」），
        # 桩表缺这两列的话 wq_upsert 直接 OperationalError —— 桩要跟着 schema 走
        db.execute("CREATE TABLE wrong_questions(id INTEGER PRIMARY KEY, user_id INT, board TEXT,"
                   "question TEXT, answer TEXT, qtype TEXT, points TEXT, method TEXT, skill TEXT,"
                   "steps TEXT, note TEXT, starred INT, src_kind TEXT, src_key TEXT,"
                   "created_at TEXT, updated_at TEXT)")

    def test_文字材料的真题做错能进错题本(self, db):
        self._wq(db)
        it = {"q": "比重约为：", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"], "answer": "A",
              "material": "2009年1-11月，全国规模以上工业企业……", "module": "资料分析",
              "qtype": "比重", "src": "real", "real_id": 1}
        n = D._dtest_to_wrongq(db, [it], [{"correct": False, "your": "B", "answer": "A"}])
        assert n == 1
        got = db.execute("SELECT question FROM wrong_questions").fetchone()[0]
        assert "2009年1-11月" in got, "材料没进错题本"

    def test_真题的图不该被当成图形推理(self, db):
        """真题的 figs 是文件名数组，figgen 的才是 {seq, opts}。
           只判真假的话，带统计图的资料分析题会被标成「图形推理」。"""
        self._wq(db)
        it = {"q": "增速最快的是：", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"], "answer": "A",
              "figs": ["abc123.png"], "module": "资料分析", "qtype": "增长率", "real_id": 2}
        D._dtest_to_wrongq(db, [it], [{"correct": False, "your": "B", "answer": "A"}])
        got = db.execute("SELECT question FROM wrong_questions").fetchone()[0]
        assert "图形推理" not in got, got[:60]


class TestAssemble:
    """一批题的答案字母分布 —— 用户点名要求过：一次出题不能所有题都选同一个选项。"""

    @staticmethod
    def _mk(i):
        return {"q": "题干" + "X" * 80, "right": "对%d" % i,
                "wrong": ["a%d" % i, "b%d" % i, "c%d" % i],
                "why_right": "因为", "why_wrong": ["甲错", "乙错", "丙错"]}

    def test_四道题就该用满四个字母(self):
        for _ in range(20):                       # 洗牌有随机性，多跑几轮
            ready, _st = D._assemble_items([self._mk(i) for i in range(4)], None)
            assert len(set(r[2] for r in ready)) == 4

    def test_题数少于四道也不会永远是A(self):
        """原先按题数铺固定表，1 道时整批全是 A（实测 8 道喂进去全 A）。"""
        seen = set()
        for _ in range(40):
            ready, _st = D._assemble_items([self._mk(0)], None)
            seen.add(ready[0][2])
        assert len(seen) == 4, "单道题的答案位置不是随机的：%s" % seen

    def test_连续两副牌不构成固定循环(self):
        """按题数铺表时 want=4 会得到 DBACDBAC，前四道之后完全可预测。"""
        same = 0
        for _ in range(40):
            ready, _st = D._assemble_items([self._mk(i) for i in range(8)], None)
            L = [r[2] for r in ready]
            if L[:4] == L[4:]:
                same += 1
        assert same < 20, "前后两副牌总是一样，能背下来蒙"

    def test_被拒的题不占位置名额(self):
        """一批里刷掉一半时，剩下那半的字母分布不能失衡。"""
        bad = {"q": "太短", "right": "对", "wrong": ["a", "b", "c"],
               "why_right": "因", "why_wrong": ["x", "y", "z"]}
        got = []
        for i in range(4):
            got += [bad, self._mk(i)]             # 好坏交替
        prof = {"med": 100, "stem": (80, 200), "opt": (1, 40)}
        ready, st = D._assemble_items(got, prof)
        assert st["style"] == 4 and len(ready) == 4
        assert len(set(r[2] for r in ready)) == 4, "被拒的题吃掉了位置名额"

    def test_计数一并返回而不是只靠改写入参(self):
        ready, st = D._assemble_items([{"q": "x"}], None)
        assert ready == [] and st["bad"] == 1


class TestSrcBlock:
    """真题模式的门槛：既不能放行两道题的「练习」，也不能误伤本来出得来的。"""

    def test_存量够门槛就放行(self):
        assert D._real_src_block("言语理解与表达", "语境分析", {"语境分析": 30}, 10) == ""

    def test_存量不够但请求数够就放行(self):
        """库里 4 道、他只要 3 道，完全出得来 —— 一刀切会误伤。"""
        assert D._real_src_block("言语理解与表达", "语境分析", {"语境分析": 4}, 3) == ""

    def test_存量和请求数都不够才拦(self):
        msg = D._real_src_block("言语理解与表达", "语境分析", {"语境分析": 2}, 10)
        assert msg and "2 道" in msg

    def test_混合练看够刷的题型数不看总量(self):
        """10 个题型各 3 道，总量 30 看着很多，但逐题型分名额时每型都出不满。"""
        cnt = {t[0]: 3 for t in D.DRILL_TYPES["言语理解与表达"]}
        assert D._real_src_block("言语理解与表达", "", cnt, 10), "按总量放行了"
        cnt[D.DRILL_TYPES["言语理解与表达"][0][0]] = 50
        assert D._real_src_block("言语理解与表达", "", cnt, 10), "只有一个题型够也不算混合练"
        cnt[D.DRILL_TYPES["言语理解与表达"][1][0]] = 50
        assert D._real_src_block("言语理解与表达", "", cnt, 10) == ""


class TestSessionLevel:
    def test_整场一致就记那个难度(self):
        assert D._session_level([{"level": "real"}, {"level": "real"}], "mid") == "real"

    def test_混着就记mix别拿第一道冒充(self):
        """实测 mix 出的 6 道是 2 real + 4 mid，取 items[0] 会记成 real。"""
        items = [{"level": "real"}, {"level": "real"}] + [{"level": "mid"}] * 4
        assert D._session_level(items, "mid") == "mix"

    def test_题上没有level就用请求参数兜底(self):
        assert D._session_level([{}, {}], "easy") == "easy"


class TestYearArg:
    def test_两个入口同一个口径(self):
        assert D._year_arg("2021") == 2021
        assert D._year_arg("2021年") == 0          # 非纯数字：当没筛，别 500
        assert D._year_arg(None) == 0
        assert D._year_arg("99999999999") == 2030  # 钳住，别让存量全变 0


class TestSlotLetters:
    def test_给了n就只发n张(self):
        assert len(list(D._slot_letters(6))) == 6

    def test_无限模式只能next(self):
        g = D._slot_letters()
        assert len({next(g) for _ in range(40)}) == 4
