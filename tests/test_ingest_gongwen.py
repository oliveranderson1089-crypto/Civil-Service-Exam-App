"""公文题库的 docx 解析（ingest_gongwen）。

这批资料的命门不是答案对齐（答案就跟在题后面，错不了），而是**同一批文件里
混着两种写法**，以及**同一道题印了两条答案标记**。下面每条都对应一个真跑出来的坑。
"""
import ingest_gongwen as G


def _one(text):
    got = G.parse([x.strip() for x in text.splitlines() if x.strip()])
    return got


class Test两种写法:
    def test_有题号有题型标注的(self):
        got = _one("""
        1. （单选题）下列选项中，不属于行政公文的是（  ）。
        A. 公告
        B. 通告
        C. 简报
        D. 报告
        【答案】C【解析】《党政机关公文处理工作条例》第 8 条规定…
        """)
        assert len(got) == 1
        q = got[0]
        assert q["stem"] == "下列选项中，不属于行政公文的是（  ）。"      # 题号和题型标注都剥掉
        assert q["options"] == ["A. 公告", "B. 通告", "C. 简报", "D. 报告"]
        assert q["answer"] == "C" and q["part"] == "single"
        assert "第 8 条" in q["explain"]

    def test_没题号选项挤一行的(self):
        got = _one("""
        慰问信是向对方表示关怀、慰问的信函，信中可以使用：(    )。
        A.感谢用语 B.关心鼓励用语
        C.祝愿用语 D.适度的抒情手法
        【答案】BCD。解析：慰问信是表示向对方关怀、慰问的信函。
        """)
        assert len(got) == 1
        q = got[0]
        assert q["part"] == "multi" and q["answer"] == "BCD"
        assert len(q["options"]) == 4                      # 一行两个选项要拆开
        assert q["options"][1] == "B. 关心鼓励用语"
        assert "慰问信是表示" in q["explain"]               # 解析写成「解析：」也要认

    def test_判断题(self):
        got = _one("""
        3. （判断题）公务文书就是社会合法组织在公务活动中形成和使用的应用文书。 正确 错误
        【答案】N。解析：还要求是依法成立的组织。
        """)
        assert got[0]["part"] == "judge" and got[0]["answer"] == "F"
        assert got[0]["options"] == []
        assert got[0]["stem"].endswith("应用文书。")        # 「正确 错误」是作答提示，不是题干


class Test重复答案标记:
    """同一道题印两条答案（`【答案】B【解析】…` 之后又来 `【解析】【答案】B。解析：…`）。
    全库 1612 个标记里 305 个是这种，按行倒推时表现为「空块」。"""

    def test_不当成新题并且拿更全的解析补上(self):
        got = _one("""
        1. （单选题）通告适用于（  ）。
        A. 宣布重要事项
        B. 公布应当遵守的事项
        【答案】B【解析】略
        【解析】【答案】B。解析：《党政机关公文处理工作条例》第 8 条规定，通告适用于在一定范围内公布应当遵守或者周知的事项。
        """)
        assert len(got) == 1, "第二条答案标记被当成了新题"
        assert "第 8 条" in got[0]["explain"], "更全的那条解析没补上来"


class Test题干不许粘上一题的解析:
    def test_有题号时从最后一个题号切起(self):
        """上一题的解析常续到下一行，落进本题的块里。抽查 6 道中过 4 道，
        而体检单全绿（题干够长、选项齐、答案在范围内）—— 光看数字发现不了。"""
        got = _one("""
        1. （单选题）甲题（  ）。
        A. 甲
        B. 乙
        【答案】A【解析】前半段
        故本题答案选 A。专用公文是指在一定业务范围内使用的文件。
        5. （单选题）广义的公文一般指（  ）。
        A. 应用文
        B. 公务文书
        【答案】B【解析】略
        """)
        assert len(got) == 2
        assert got[1]["stem"] == "广义的公文一般指（  ）。", got[1]["stem"]

    def test_没题号时靠解析的收尾话切(self):
        got = _one("""
        故本题答案为 ABCD。声明可以在报刊登载，也可以通过广播播发。
        讲话稿的正文要写：( )。
        A.署名 B.称谓 C.开头 D.主体
        【答案】CD。解析：讲话稿由标题、称谓、正文、落款等部分组成。
        """)
        assert got[0]["stem"] == "讲话稿的正文要写：( )。", got[0]["stem"]


class Test体检:
    def test_范文被当成题干的要剔掉(self):
        ok, bad = G.check([{
            "stem": "加强组织领导。成立工作专班，压实责任。2.注意方式方法。因地制宜、稳妥推进，"
                    "不搞“一刀切”。3.强化督导检查。建立常态化督导机制，定期通报情况。4.建立长效机制。",
            "options": ["A. 甲", "B. 乙"], "answer": "A", "explain": "", "part": "single"}])
        assert not ok and bad[0]["why"] == "题干像范文正文，不像题目"

    def test_正常题干不许误伤(self):
        ok, bad = G.check([
            {"stem": "用于不相隶属机关之间沟通、协调工作的函是：", "options": ["A. 甲", "B. 乙"],
             "answer": "A", "explain": "", "part": "single"},
            {"stem": "下列文种中属于党政机关法定公文的是（  ）。", "options": ["A. 甲", "B. 乙"],
             "answer": "B", "explain": "", "part": "single"}])
        assert len(ok) == 2 and not bad

    def test_答案超出选项范围的不要(self):
        ok, bad = G.check([{"stem": "下列属于公文的是（  ）。", "options": ["A. 甲", "B. 乙"],
                            "answer": "D", "explain": "", "part": "single"}])
        assert not ok and bad[0]["why"] == "答案落在选项范围之外"
