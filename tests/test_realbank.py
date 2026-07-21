"""真题解析的回归测试。

这里每一条都对应一个**真踩过的坑**——历年卷面格式换过好几轮，
凭想象写的规则一上真素材就漏，所以样例全是从云盘那批卷子里原样抠出来的片段。

最要命的是「答案错开一位」那个：整卷答案偏移一格，抽查五道全错，
而单看一份卷子完全看不出异常。它值这里最长的两条测试。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import realbank as R  # noqa: E402


class TestSplitOptions:
    def test_四个选项挤在一行也要拆得开(self):
        # 2002 国考原文：B、C 前面没有换行，按行拆会把四个选项当成两个
        block = ("香烟点燃后，冒出的烟雾看上去是蓝色的，这是因为（    ）。\n"
                 "A、烟雾的颗粒本身是蓝色的B、烟雾将光线中其他色光滤掉，只有蓝光透射出来\n"
                 "C、烟雾的颗粒对蓝色光散射强烈D、烟雾的颗粒吸收光线后，发出蓝色荧光")
        stem, opts = R._split_options(block)
        assert len(opts) == 4
        assert stem.startswith("香烟点燃后")
        assert opts[0] == "烟雾的颗粒本身是蓝色的"
        assert opts[3] == "烟雾的颗粒吸收光线后，发出蓝色荧光"

    def test_选项只用空格分隔(self):
        # 2022 上半年四川：「A ①②③④   B ①③②④」，没有顿号也没有点
        stem, opts = R._split_options(
            "按其反映的中国革命发展进程排序正确的是：\n"
            "A ①②③④          B ①③②④          C ③①②④          D ③②①④")
        assert opts == ["①②③④", "①③②④", "③①②④", "③②①④"]

    def test_题干里的字母不能当成选项(self):
        # 「DNA」「A 股」这类：选项标记必须按 A→B→C→D 的顺序往后找才不会误命中
        stem, opts = R._split_options(
            "DNA是人类进行亲子鉴定的主要依据。就DNA的组成，下面说法正确的是（  ）。\n"
            "A、DNA由核糖、碱基和磷酸组成B、DNA由脱氧核糖、磷酸和碱基组成\n"
            "C、DNA由脱氧核糖、磷酸、碱基和蛋白质组成D、DNA由脱氧核糖、磷酸、碱基和脂肪组成")
        assert len(opts) == 4
        assert stem.startswith("DNA是人类")

    def test_拆不出四个就整段退回(self):
        stem, opts = R._split_options("这是一段材料，没有选项。")
        assert opts == []


class TestModuleHead:
    def test_三种分节写法都要认(self):
        for text, want in [
            ("第一部分 常识判断\n1、题", "常识判断"),
            ("一、常识判断，根据题目要求，在四个选项中选出一个最恰当的答案。\n1、题", "常识判断"),
            ("二.言语理解与表达：本部分包括…\n1、题", "言语理解与表达"),
            ("五、资料分析。所给出的图、表…\n1、题", "资料分析"),
        ]:
            spans = R.module_spans(text)
            assert spans and spans[0][1] == want, text[:20]

    def test_康熙部首伪装成汉字(self):
        # 2022 四川那份用的是 U+2F00（康熙部首「一」），肉眼和 U+4E00 没区别，正则全不命中
        text = "⼀.常识判断：第⼀部分常识判断。\n题干\nA.甲\nB.乙\nC.丙\nD.丁"
        assert R.module_spans(text) == []            # 不转换就认不出
        assert R.module_spans(text.translate(R._KANGXI_TAB))[0][1] == "常识判断"


class TestParseAnswers:
    def test_正确答案三个字也要认(self):
        """这是「整卷答案错开一位」的根因。

        格式是「1 、正确答案：D」，比「1、【答案】D」多了「正确」二字、
        数字后还多个空格。认不出就会退到最弱的兜底模式，然后错位。
        """
        text = ("1 、正确答案：D，全站正确率：45%，易错项：B。\n解析\n第一步，本题考查管理知识。\n"
                "因此，选择 D 选项。\n"
                "2 、正确答案：A，全站正确率：75%，易错项：C。\n解析\n第二题的解析。\n"
                "因此，选择 A 选项。\n")
        ans, synth = R.parse_answers(text)
        assert synth is False
        assert ans[1][0] == "D" and ans[2][0] == "A"
        # 关键：第 1 题的解析里**不能**混进第 2 题的内容
        assert "第二题" not in ans[1][1]

    def test_六种排版(self):
        for text, seq, want in [
            ("1、【答案】B\n【解析】因为如此。\n2、【答案】C\n【解析】另一题。", 1, "B"),
            ("第【1】题\n正确答案:【B】\n解析\n讲解内容。\n第【2】题\n正确答案:【C】\n解析\nx", 1, "B"),
            ("1.A【解析】这段话的主旨…故正确答案为 A。\n2.C【解析】另一题。", 1, "A"),
            ("1.解析\n第一步，本题考查中共党史。\n因此，选择 C 选项。\n"
             "2.解析\n第二题。\n因此，选择 D 选项。", 1, "C"),
        ]:
            ans, synth = R.parse_answers(text)
            assert ans.get(seq, ("",))[0] == want, text[:24]

    def test_答案速览表(self):
        """卷首那块「题号区间 + 连续字母」的总表 —— 一页顶全卷，最可靠的一种。

        括号写法很随意（【】[] {}），扫描件 OCR 还会把 [ 认成 {，所以两边都要放宽。
        """
        t = ("【1-5】ACDAD [6-10] BCCCA    [11-15] BBBDB    { 16-20] BCDCB\n"
             "[21-25] DDCAC [26-30] BBADC")
        ans, synth = R.parse_answers(t)
        assert len(ans) == 30
        assert [ans[i][0] for i in range(1, 11)] == list("ACDADBCCCA")
        # 表里的题号是原卷明写的，**不是合成的** —— 判错会让调用方弃用整卷答案
        assert synth is False

    def test_速览表字母数对不上区间就整段不要(self):
        """OCR 把字母认漏一个，硬填会让整段答案错位，宁可不要。"""
        assert R.parse_answers("【1-5】ACD")[0] == {}

    def test_题号丢了的要自报合成(self):
        """第 ⑤ 种：题号在转档时丢了，只剩光秃秃的「解析」当分隔。

        只能按出现顺序编号 —— 少一条就整体错位，所以必须自报 synth=True，
        让调用方拒绝拿它去挂题。
        """
        text = "".join("解析\n本题考查第%d题。\n故正确答案为%s。\n" % (i, "ABCD"[i % 4])
                       for i in range(1, 30))
        ans, synth = R.parse_answers(text)
        assert synth is True
        assert len(ans) > 20

    def test_扫描件返回空而不是报错(self):
        ans, synth = R.parse_answers("\x0c\x0c\x0c")
        assert ans == {} and synth is False


class TestParsePaper:
    PAPER = ("2020年国家公务员录用考试《行测》真题（地市级）\n\n"
             "一、常识判断。根据题目要求，在四个选项中选出一个最恰当的答案。\n"
             "1、下列有关主题教育的说法正确的是：\nA、甲说法\nB、乙说法\nC、丙说法\nD、丁说法\n"
             "2、下列关于文化的说法不正确的是：\nA、第一项    B、第二项    C、第三项    D、第四项\n"
             "三、数量关系。在这部分试题中…\n"
             "3、某餐厅有桌子若干张，问有几张？\nA、2    B、4    C、6    D、8\n")

    def test_题号模块选项都对(self):
        qs = R.parse_paper(self.PAPER)
        assert len(qs) == 3
        assert [q["seq"] for q in qs] == [1, 2, 3]
        assert qs[0]["module"] == "常识判断"
        assert qs[2]["module"] == "数量关系"
        assert all(q["synth_seq"] == 0 for q in qs)

    def test_没有题号时走兜底并标记合成序号(self):
        """整份卷子不印题号（2022 四川那两份）。切得出题，但序号是编的 ——
           必须标 synth_seq=1，否则拿去对答案卷的题号必然错位。"""
        text = "常识判断\n" + "".join(
            "第%d道题的题干写在这里，够长。\nA.甲%d\nB.乙%d\nC.丙%d\nD.丁%d\n\n" % (i, i, i, i, i)
            for i in range(1, 6))
        qs = R.parse_paper(text)
        assert len(qs) >= 4
        assert all(q["synth_seq"] == 1 for q in qs)


class TestPairing:
    """题目卷 ↔ 答案卷 的配对。

    这里守的是**整条管线里最严重的一个 bug**：原先按 (考试,年份,卷种,半年) 配对，
    《2005 国考真题卷（一）》和《卷（二）》撞进同一个桶，两份内容完全不同的卷子
    拿到了同一份答案（124 题里 123 题答案相同）。而「题号命中率」这类校验完全拦不住
    —— 两卷题号都是 1..124，命中率 100%。
    """
    def test_答案卷能配上对应的题目卷(self):
        for q, a in [
            ("2005年国家公务员考试《行测》真题卷（一）.doc",
             "2005年国家公务员考试《行测》真题卷（一）答案及解析.pdf"),
            ("2006年国家公务员考试《行测》真题卷（二）.doc",
             "2006年国家公务员考试《行测》真题卷（二）参考答案及解析.pdf"),
            ("2020年0725四川公务员考试《行测》真题.docx",
             "2020年0725四川公务员考试《行测》真题参考答案及解析.pdf"),
            ("2022年四川下半年公务员录用考试《行测》 试题.docx",
             "2022年四川下半年公务员录用考试《行测》 答案解析.docx"),
            ("2023年国家公务员录用考试《行测》题（副省级）.docx",
             "2023年国家公务员录用考试《行测》题（副省级）答案及解析.docx"),
            ("1-【行政执法】2024年国考-无答案版.pdf",
             "2-【行政执法】2024年国考-答案和解析.pdf"),
        ]:
            assert R.pair_key(q) == R.pair_key(a), q
            assert R.variant_tokens(q) == R.variant_tokens(a), q

    def test_同年不同卷绝不互配(self):
        """名字只差一个字，任何相似度算法都会认成同一份 —— 只能靠卷别令牌硬卡。"""
        for a, b in [
            ("2005年国家公务员考试《行测》真题卷（一）.doc",
             "2005年国家公务员考试《行测》真题卷（二）答案及解析.pdf"),
            ("2020年0725四川公务员考试《行测》真题.docx",
             "2020年1206四川公务员考试《行测》真题参考答案及解析.pdf"),
            ("2023年国家公务员录用考试《行测》题（副省级）.docx",
             "2023年国家公务员录用考试《行测》题（地市级）答案及解析.docx"),
            ("1-【行政执法】2024年国考-无答案版.pdf",
             "3-【地市卷】2024年国考-无答案版（1月23日修订）.pdf"),
        ]:
            same = R.pair_key(a) == R.pair_key(b) and R.variant_tokens(a) == R.variant_tokens(b)
            assert not same, "%s 不该配上 %s" % (a, b)


class TestPaperRole:
    """题目卷 / 答案卷 的判定。

    坑：原先只要目录路径里出现「答案」二字就判成答案卷，而
    「1、2025国考【行测】真题试卷及答案」是**混装目录** —— 题目卷和答案卷都在里面。
    结果《2025国考行测题（副省级）》这类题目卷被判成答案卷，**它们的题目从此不会被解析**
    （提取只处理 role='q'），还白白拿去跑了 OCR。
    """
    def test_混装目录里的题目卷不算答案卷(self):
        for name in ("2025年国家公务员录用考试《行测》题（副省级）.pdf",
                     "2026年国考《证监会》（网友回忆）.pdf"):
            assert R.paper_meta(
                name, "公考/国考公务员2000-2026真题/1、2025国考【行测】真题试卷及答案"
            )["is_answer"] is False, name

    def test_纯答案目录仍然算答案卷(self):
        assert R.paper_meta("2007年四川省公务员考试《行测》真题.pdf",
                            "公考/四川公务员考试真题/行测（07-25）/答案及解析")["is_answer"] is True

    def test_嵌套在答案目录下的也算(self):
        """…/01、26国考行测答案（已更新）/国考地市卷/x.pdf —— 最后一段没有「答案」，
           但上层有，所以要**逐段**看而不是只看最后一段。"""
        assert R.paper_meta("26国考行测真题解析.pdf",
                            "公考/2026国考行测真题试卷和答案/01、26国考行测答案（已更新）/国考地市卷"
                            )["is_answer"] is True

    def test_无答案版是题目卷不是答案卷(self):
        """「无答案版」说的是**没有**答案，可它里面就带着「答案」二字。

        直接 search("答案") 会把 2024 国考那三份「无答案版」判成答案卷 ——
        白跑一遍 OCR 不说，抠出来的东西还会当成答案去和题目卷配对
        （它俩的 pair_key 恰好相同，真答案卷反而可能被顶掉）。
        """
        for n in ("1-【行政执法】2024年国考-无答案版.pdf",
                  "3-【地市卷】2024年国考-无答案版（1月23日修订）.pdf",
                  "5-【副省卷】2024年国考-无答案版（1月28日更新）.pdf"):
            m = R.paper_meta(n, "")
            assert m["is_answer"] is False, n
            assert m["paper"], "卷种不能因为提前返回而丢：" + n
        # 真答案卷不受影响
        assert R.paper_meta("2-【行政执法】2024年国考-答案和解析.pdf", "")["is_answer"] is True

    def test_文件名自己说了就不看目录(self):
        assert R.paper_meta("2005年国考《行测》真题答案及解析.pdf", "公考/随便什么目录"
                            )["is_answer"] is True


class TestTailTrim:
    def test_D选项不吞后面的分节说明(self):
        """D 是最后一个标记，天然取到块尾，下一节的说明/例题/页脚会全被吞进去。
           实测 4.6% 的题中招，D 存成「…\\n\\n第二部分 数量关系\\n(共15题…)【例题】…」。"""
        block = ("对上面这段话中的“涟漪”理解正确的是：\n"
                 "A、指风行水上留下的波纹\nB、指内心深处的触动\n"
                 "C、指抑制不住的联翩浮想\nD、指引起深深的共鸣\n\n"
                 "第二部分 数量关系\n(共15题，参考时限10分钟)\n"
                 "【例题】1，3，5，7，9，（ ）。\n请开始答题：")
        stem, opts = R._split_options(block)
        assert len(opts) == 4
        assert opts[3] == "指引起深深的共鸣"
        assert "第二部分" not in opts[3] and "例题" not in opts[3]

    def test_没有多余尾巴时不误伤(self):
        stem, opts = R._split_options(
            "下列说法正确的是：\nA、甲\nB、乙\nC、丙\nD、丁而且这一项写得比较长一些")
        assert opts[3] == "丁而且这一项写得比较长一些"


class TestStemNotEaten:
    def test_题干里的孤立A不该把题干切走(self):
        """题干出现「A、B 两地」这类写法时，从块首找 A 会命中它，
           题干被截断、真正的 A 选项内容跑进 stem、B/C/D 整体错位一格。"""
        block = ("A、B 两地相距 400 米，甲乙两人同时出发相向而行，问几分钟后相遇？\n"
                 "A、2分钟\nB、4分钟\nC、6分钟\nD、8分钟")
        stem, opts = R._split_options(block)
        assert len(opts) == 4
        assert opts == ["2分钟", "4分钟", "6分钟", "8分钟"]
        assert stem.startswith("A、B 两地相距")


class TestTrimNext:
    def test_解析正文里的编号行不该被当成下一题(self):
        """「3、解析该条款时应注意…」和题头长得一模一样，
           只有题号**大于当前题**才可能是下一题的开头。"""
        body = ("本题考查行政处罚。\n参见下述三种情形：\n"
                "2、解析该条款时应注意主体资格。\n因此，选择 B 选项。")
        assert R._trim_next(body, cur_seq=44) == body          # 2 < 44，是正文
        assert "解析该条款" not in R._trim_next(body, cur_seq=1)  # 2 > 1，当作下一题切掉

    def test_真的下一题题头要切掉(self):
        body = "第一步，本题考查几何。\n因此，选择 C 选项。\n44 、正确答案：B，全站正确率：77%。"
        out = R._trim_next(body, cur_seq=43)
        assert "44" not in out and "正确答案：B" not in out


class TestJunkStem:
    def test_分节说明里的例题不算题(self):
        """说明块里的例题有题干有 ABCD，长得和真题一模一样。收进来的后果不止是脏数据：
           各年份的说明文字一字不差，去重时会把它们并成一条，再挂上不相干的答案。"""
        paper = ("二、演绎推理：共15题，每题给出一段陈述。\n"
                 "【例题】对于穿鞋来说，重要的是合脚。\n"
                 "A.不合脚的鞋不能在冷天穿\nB.毛衣的大小只是式样问题\n"
                 "C.不合身的衣物有时仍有使用价值\nD.买礼物时尺寸不如用途重要\n"
                 "解答：只有C是可以直接推出的，应选C。\n"
                 "1、下列关于宪法的说法正确的是：\nA.甲说法\nB.乙说法\nC.丙说法\nD.丁说法\n")
        qs = R.parse_paper(paper)
        assert [q["seq"] for q in qs] == [1]
        assert "例题" not in qs[0]["stem"] and "演绎推理" not in qs[0]["stem"]


class TestQhash:
    def test_排版差异不该算成两道题(self):
        """同一道题的 word 版和 PDF 版，括号/空格往往不一样。
           指纹要把这些抹平，否则去重时会当成两道题。"""
        a = "下列说法正确的是（    ）。"
        b = "下列说法正确的是(  )。"
        c = "下列说法正确的是（ ）。"
        assert R.qhash_text(a) == R.qhash_text(b) == R.qhash_text(c)

    def test_不同的题仍要分得开(self):
        assert R.qhash_text("甲说法正确") != R.qhash_text("乙说法正确")


def test_ans_numbered_block_ocr_bracket_ambiguity():
    """⑨「【解析 N】」：右括号被 OCR 认成 1 时，别把「解析 2】」读成第 21 题。

    这是 2024 国考那批 A0 扫描件的排版。真正的第 21 题也长「【解析 21]」，
    单看一行分不清，只能靠「解析块按题号顺序排」这个事实消歧。
    """
    parts = []
    for i in range(1, 26):
        close = "1" if i in (2, 3) else "】"     # 前几块的 】 被认成了 1
        parts.append("【解析 %d%s\n这里是解析正文。因此，选择 %s 选项。"
                     % (i, close, "ABCD"[i % 4]))
    ans, synth = R.parse_answers("\n".join(parts))
    assert synth is False, "号是卷子上印的，不该标成合成号"
    assert len(ans) == 25 and max(ans) == 25, ans.keys()
    assert ans[2][0] == "C", "「【解析 21」在第 2 块的位置上应判成第 2 题"
    assert ans[21][0] == "B", "第 21 块才是真的第 21 题"


def test_ans_numbered_block_survives_gaps():
    """⑨ 的价值就在这儿：中间吞了几块，剩下的照样挂在**正确**的题号上。

    换成 ⑤ 的顺序编号，缺一块后面就全体错位一格 —— 那比没有答案还糟。
    """
    parts = ["【解析 %d】\n解析正文。因此，选择 %s 选项。" % (i, "ABCD"[i % 4])
             for i in range(1, 31) if i not in (9, 12, 20)]
    ans, synth = R.parse_answers("\n".join(parts))
    assert synth is False
    assert 9 not in ans and 12 not in ans and 20 not in ans
    assert ans[30][0] == "C" and ans[13][0] == "B", "缺块之后的题号不能整体挪位"


def test_ans_numbered_block_rejects_garbage_numbers():
    """号读废的块超过一成，就别信这批号 —— 退回 ⑤ 按顺序编、自报 synth 让题数闸兜底。"""
    parts = ["【解析 %d】\n解析正文。因此，选择 A 选项。" % n
             for n in [7, 3, 9, 1, 5, 2, 8, 4, 6] * 3]      # 号完全乱序 = OCR 认废了
    ans, synth = R.parse_answers("\n".join(parts))
    assert synth is True, "乱序的号不可信，必须退回顺序编号并自报 synth"
