"""申论真题解析器的测试（P0.5）。

这套解析器的每一条规则都是被真实卷子打脸打出来的，用例就照那些坑写：

  ① 作答要求段头有 4 种变体、题号有 5 种变体 —— 只认「三、作答要求」+「一、」时
     21 份卷子切不出来，含 2025 国考三卷
  ② **两种排版互相冲突**：一种是「题面全在前、答案全在后」，另一种是「一道题紧跟它的答案」。
     在第一个「参考答案」处硬截能救前者、却把后者整份丢掉（16 份）；
     不截则把答案里的「一、加大医疗投入…」当成题目（有卷子因此出了 12 道题）。
     现在的判据是「题干必带分值或字数要求」，两种排版都得过 —— 这两个用例是这份文件的核心。
  ③ 字数「不超过500字」会被 PDF 折行成「不超 过500字」
  ④ 「撰写一份《…建议》」是应用文，「就…提出建议」是对策题 —— 只看「建议」两个字会错
"""
import sys

import pytest

from conftest import BASE  # noqa: F401  确保 sys.path 和测试库隔离已就位

sys.path.insert(0, str(BASE))
import ingest_shenlun as ing  # noqa: E402


MAT = "1. 某市推进老旧小区改造，居民满意度明显提升。" * 12


def _paper(task_head, qs, answers=""):
    return ("一、注意事项\n1.本题本由给定资料与作答要求两部分构成。\n"
            "二、给定资料\n" + MAT + "\n" + task_head + "\n" + qs + "\n" + answers)


# ---------- 段头 / 题号变体 ----------

TASK_HEADS = ["三、作答要求", "【作答要求】", "作答要求", "二、作答要求", "三、申论要求"]


@pytest.mark.parametrize("head", TASK_HEADS)
def test_task_head_variants(head):
    qs = ("一、\n请概括A市的做法。（10 分）要求：全面准确，不超过200字。\n"
          "二、\n请分析原因。（15 分）要求：条理清晰，不超过300字。\n"
          "三、\n请拟写一份工作简报。（25 分）要求：内容全面，不超过500字。\n")
    mat, got = ing.split_paper(_paper(head, qs))
    assert len(got) == 3, (head, got)
    assert "老旧小区" in mat


@pytest.mark.parametrize("qs,n", [
    ("问题一：概括做法。（10 分）不超过200字。\n问题二：分析原因。（15 分）不超过300字。\n"
     "问题三：拟写简报。（25 分）不超过500字。\n", 3),
    ("一、概括做法。（10 分）不超过200字。\n二、分析原因。（15 分）不超过300字。\n"
     "三、拟写简报。（25 分）不超过500字。\n", 3),
    ("1、概括做法。（10 分）不超过200字。\n2、分析原因。（15 分）不超过300字。\n"
     "3、拟写简报。（25 分）不超过500字。\n", 3),
    ("第一题 概括做法。（10 分）不超过200字。\n第二题 分析原因。（15 分）不超过300字。\n"
     "第三题 拟写简报。（25 分）不超过500字。\n", 3),
])
def test_qnum_variants(qs, n):
    _mat, got = ing.split_paper(_paper("三、作答要求", qs))
    assert len(got) == n, got


# ---------- 两种排版（互相冲突，必须都过）----------

def test_layout_answers_at_end():
    """题面全在前、参考答案全在后：答案里的分条**不能**被当成题目。"""
    qs = ("一、概括A市的做法。（10 分）要求：不超过200字。\n"
          "二、分析原因。（15 分）要求：不超过300字。\n"
          "三、拟写一份工作简报。（25 分）要求：不超过500字。\n")
    ans = ("参考答案\n"
           "一、加大投入，落实保障。1.申请资金；2.压实责任。\n"
           "二、健全机制，形成合力。1.成立小组；2.明确分工。\n"
           "三、强化监督，巩固成效。1.定期督查；2.通报排名。\n"
           "四、注重宣传，营造氛围。1.入户走访；2.媒体报道。\n")
    _mat, got = ing.split_paper(_paper("三、作答要求", qs, ans))
    assert len(got) == 3, "答案分条被当成题目了：%r" % got
    assert all("加大投入" not in g for g in got)


def test_layout_interleaved():
    """一道题紧跟它的答案：不能因为遇到第一个「参考答案」就只剩第一题。"""
    body = ("一、概括A市的做法。（10 分）要求：不超过200字。\n"
            "【试题一】参考答案\n加大投入，落实保障。\n"
            "二、分析原因。（15 分）要求：不超过300字。\n"
            "【试题二】参考答案\n机制不健全，合力不足。\n"
            "三、拟写一份工作简报。（25 分）要求：不超过500字。\n"
            "【试题三】参考答案\n某市老旧小区改造工作简报……\n")
    _mat, got = ing.split_paper(_paper("三、作答要求", body))
    assert len(got) == 3, "交错排版被截成了 %d 道" % len(got)
    # 题干里不许把答案带进来
    assert all("参考答案" not in g for g in got)
    assert "加大投入" not in got[0]


def test_out_of_range_is_left_to_caller():
    """切出的道数超出 2~6 时交回最接近的一组，由调用方标 suspect ——
    宁可整份不入库，也不能把垃圾题灌进去污染文种频次。"""
    qs = "".join("%s、题目%d。（10 分）要求：不超过200字。\n"
                 % (c, i) for i, c in enumerate("一二三四五六", 1))
    qs += "".join("（%s）另一层题目。（10 分）不超过200字。\n" % c for c in "一二三四五六七")
    _mat, got = ing.split_paper(_paper("三、作答要求", qs))
    assert not (ing.Q_LO <= len(got) <= ing.Q_HI) or len(got) <= ing.Q_HI


def test_looks_q():
    assert ing._looks_q("请概括做法。（10 分）")
    assert ing._looks_q("请拟写简报。不超过500字。")
    assert ing._looks_q("请分析。要求：条理清晰。")
    assert not ing._looks_q("一、加大投入，落实保障。1.申请资金；2.压实责任。")


# ---------- 字数 / 分值 / 要求 ----------

@pytest.mark.parametrize("q,want", [
    ("要求：不超过500字。", 500),
    ("要求：(4)不超 过450字。", 450),          # PDF 折行，实测漏过 7 道
    ("要求：字数800-1000字。", 1000),
    ("要求：1000字左右。", 1000),
    ("要求：不多于300字。", 300),
    ("要求：条理清晰。", 0),
])
def test_find_words(q, want):
    assert ing.find_words(q) == want


@pytest.mark.parametrize("q,want", [("（20 分）", 20), ("(35分)", 35), ("无分值", 0)])
def test_find_score(q, want):
    assert ing.find_score(q) == want


def test_split_require():
    stem, req = ing.split_require("三、请拟写一份工作简报。（25 分） 要求：内容全面，不超过500字。")
    assert "工作简报" in stem and "要求" not in stem
    assert "内容全面" in req


# ---------- 参考答案对齐 ----------

def test_split_answers_by_shiti():
    text = ("参考答案\n【试题一】参考答案\n答案甲\n【试题二】参考答案\n答案乙\n"
            "【试题三】参考答案\n答案丙\n")
    anchor, got = ing.split_answers(text, 3)
    assert anchor == "试题号", anchor
    assert [got[i].strip() for i in (1, 2, 3)] == ["答案甲", "答案乙", "答案丙"]


def test_split_answers_strips_analysis():
    """解析（审题/找点）不属于答案正文，要切掉——否则答案里混进一大段教学话术。"""
    text = ("参考答案\n【试题一】参考答案\n答案甲\n第一步——审题\n勾画题干关键词……\n"
            "【试题二】参考答案\n答案乙\n")
    _a, got = ing.split_answers(text, 2)
    assert got[1].strip() == "答案甲"
    assert "审题" not in got[1]


def test_split_answers_gives_up_when_count_off():
    """段数和题数差太远就是切错了，宁可不给。"""
    text = "参考答案\n" + "".join("%s、分条%d\n" % (c, i)
                                for i, c in enumerate("一二三四五六", 1))
    _a, got = ing.split_answers(text, 2)
    assert not got or len(got) <= 3


# ---------- 题型分类 ----------

@pytest.mark.parametrize("stem,kind,family", [
    # 应用文：有交办语 + 点名文种
    ("假如你是S县委组织部工作人员，请根据给定资料3撰写一篇乡村夜校情况的简报。（25 分）",
     "贯彻执行", "简报"),
    ("A市要召开座谈会，假如你是区政府办工作人员，请撰写一篇经验交流材料。（35 分）",
     "贯彻执行", "交流材料"),
    ("假如你是市场监管部门的参会代表，将在座谈会上发言，请根据给定资料2写发言稿。（20 分）",
     "贯彻执行", "交流材料"),
    ("假如你是叶教授，请根据给定资料3起草一份《关于加强凤凰河流域文化建设的建议》。（20 分）",
     "贯彻执行", "建议"),
    # 「就…提出建议」没有文种，是对策题 —— 加过一版通用上下文，把这类误判成应用文 6 道
    ("请根据给定资料3，就做好“小饭桌”管理工作提出建议，供领导参阅。（25 分）",
     "提出对策", ""),
    ("请根据给定资料3，就J市税务局如何强化举措提出工作建议。（20 分）", "提出对策", ""),
    # 大作文
    ("请结合对这句话的理解，参考给定资料，联系实际，自选角度，自拟题目，写一篇文章。（35 分）",
     "文章论述", ""),
    # 小题
    ("请根据给定资料1，概括A县发展山核桃产业的措施。（15 分）", "归纳概括", ""),
    ("请根据给定资料2，谈谈你对“对话”一词的理解。（20 分）", "综合分析", ""),
])
def test_classify(stem, kind, family):
    got_kind, _dt, got_fam, _form = ing.classify(stem)
    assert got_kind == kind, (stem[:30], got_kind)
    assert got_fam == family, (stem[:30], got_fam)


def test_classify_form():
    _k, _d, _f, form = ing.classify("请根据给定资料3，草拟一份汇报提纲。（20 分）")
    assert form == "outline"
    _k, _d, _f, form = ing.classify(
        "假如你是调研组成员，请拟写调研报告的“问题”和“建议”部分。（25 分）")
    assert form == "part"


# ---------- 文件名元信息 ----------

@pytest.mark.parametrize("name,exam,year,era", [
    ("2026年国家公考《申论》题（副省级）.pdf", "国考", 2026, "new"),
    ("2008年四川公务员考试《申论》真题及参考答案.pdf", "四川", 2008, "old"),
    ("2022年山东省公考《申论》题（A类）（网友回忆版）.pdf", "山东", 2022, "new"),
    ("2023年公务员多省联考《申论》题（四川县乡卷）.pdf", "四川", 2023, "new"),
])
def test_meta_of(name, exam, year, era):
    got_exam, got_year, _kind, got_era = ing.meta_of(name)
    assert (got_exam, got_year, got_era) == (exam, year, era)


def test_era_boundary():
    """标尺窗口卡在 2018：2000-2017 的贯彻执行题型还没定型，
    拿 2003 年的分布去校准 2027 年的出题是错的。"""
    assert ing.meta_of("2017年国考申论.pdf")[3] == "old"
    assert ing.meta_of("2018年国考申论.pdf")[3] == "new"
