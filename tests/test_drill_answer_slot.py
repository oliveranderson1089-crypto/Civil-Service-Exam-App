"""正确答案排第几位，**由我们定，不问模型**。

模型自己排的话正确项严重偏前：实测题库 A 39.3% / B 28.6% / C 24.8% / D **7.4%**，
真题则是各占四分之一。试过在提示词里逐题指定位置，**实测无效** ——
照做之后 A 反而升到 45%、D 仍是 8.3%。

所以改成让模型只交「正确项内容 + 三个干扰项内容」，字母一个都不写，
由 _bank_fill 把正确项插到指定位置、自己拼字母、自己拼解析。
这是构造性保证，和模型听不听话无关。这组测试守的就是这个保证。
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mods.drill import _compose_explain, _split_rw  # noqa: E402

NEW = {"q": "题干", "right": "对的那项", "wrong": ["错一", "错二", "错三"],
       "why_right": "因为它对", "why_wrong": ["错一的毛病", "错二的毛病", "错三的毛病"],
       "source": "考点"}


def _place(slots, n):
    """复刻 _bank_fill 里的位置分配，用来验证分布性质。"""
    return [slots[i % len(slots)] for i in range(n)]


class TestSlots:
    def test_按want均匀铺满(self):
        """⚠️ 绝不能先生成再截断。原先写的
           `[c for c in "ABCD" for _ in range((want+3)//4)][:want]`
           在 want=6 时是 A×2 B×2 C×2 **D×0**、want=10 时 D×1 ——
           反而加重了它本来要修的偏斜。而 warm_drill_bank 的 want 恰好取 6/8/10/12。
        """
        for want in (1, 4, 6, 8, 10, 12, 13, 40):
            slots = ["ABCD"[i % 4] for i in range(max(1, want))]
            c = Counter(slots)
            assert max(c.values()) - min(c.values()) <= 1, \
                "want=%d 分配不均：%s" % (want, dict(c))

    def test_一批题不会全落在同一个选项(self):
        """用户明确要求过：一次出题不能所有题都选同一个字母。"""
        for want in (4, 8, 12):
            slots = ["ABCD"[i % 4] for i in range(want)]
            assert len(set(_place(slots, want))) == 4, "want=%d 只用到了 %s" % (want, set(slots))


class TestSplit:
    def test_新格式拆得出来且允许重排(self):
        right, wrong, why_r, why_w, can_place = _split_rw(NEW)
        assert right == "对的那项" and wrong == ["错一", "错二", "错三"]
        assert why_r == "因为它对" and len(why_w) == 3
        assert can_place is True

    def test_老格式仍然认但不许重排(self):
        """老格式的解析正文里带字母引用（「故 D 错误」），一重排就全指错选项。"""
        old = {"q": "题干", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"],
               "answer": "C", "explain": "故 A、B、D 均错，选 C。"}
        right, wrong, why_r, why_w, can_place = _split_rw(old)
        assert right == "丙" and wrong == ["甲", "乙", "丁"]
        assert can_place is False, "老格式被允许重排了，解析会指错选项"
        assert why_r == "故 A、B、D 均错，选 C。" and why_w == []

    def test_缺字段就判不合格(self):
        for bad in ({"q": "x"}, {"q": "x", "right": "对", "wrong": ["只有一个"]},
                    {"q": "x", "options": ["A. 甲"], "answer": "A"},
                    {"q": "x", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"], "answer": "X"}):
            right, wrong, _r, _w, _p = _split_rw(bad)
            assert not (right and len(wrong) == 3), bad


class TestComposeExplain:
    def test_字母按最终位置填(self):
        """正确项插到 C 位之后，解析里说的就必须是 C。"""
        right, wrong, why_r, why_w, _ = _split_rw(NEW)
        body = wrong[:2] + [right] + wrong[2:]      # 正确项放第 3 位 = C
        txt = _compose_explain("C", why_r, why_w, wrong, body)
        assert txt.startswith("正确答案 C：因为它对")
        # 错一、错二在正确项之前（A、B），错三被挤到 D
        assert "A 项错在：错一的毛病" in txt
        assert "B 项错在：错二的毛病" in txt
        assert "D 项错在：错三的毛病" in txt

    def test_正确项放A时干扰项顺延(self):
        right, wrong, why_r, why_w, _ = _split_rw(NEW)
        body = [right] + wrong
        txt = _compose_explain("A", why_r, why_w, wrong, body)
        assert "B 项错在：错一的毛病" in txt and "D 项错在：错三的毛病" in txt

    def test_老格式的解析原样返回(self):
        """why_wrong 为空 = 老格式兜底，别硬拼，把模型写好的整段带回去。"""
        assert _compose_explain("C", "故 A、B、D 均错，选 C。", [], [], []) == "故 A、B、D 均错，选 C。"

    def test_干扰项文本对不上就跳过那条(self):
        """模型偶尔会在 wrong 和 why_wrong 之间改写法，找不到就别瞎填字母。"""
        txt = _compose_explain("A", "对的理由", ["甲的毛病"], ["库里没有的那项"], ["对的那项", "甲"])
        assert "项错在" not in txt and txt == "正确答案 A：对的理由。"

    def test_不拼出句号加分号(self):
        """模型每条都自带句号，直接用「；」拼会拼出「…符合语境。；B 项错在…」。"""
        txt = _compose_explain("A", "它对。", ["甲", "乙"], ["甲错。", "乙错。"],
                               ["它对。", "甲", "乙"])
        assert "。；" not in txt and txt.endswith("。")
