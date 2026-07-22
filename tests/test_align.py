"""提纲 ↔ 正文 对齐（mods/align）。

这块是照实测数据长出来的：全库 38 篇扫过一遍，26 篇字面对不上，但拆开看绝大多数
段首**已经是**分论点句、只是换了说法（提纲「实干是成就事业的基石」／正文「执一而御万，
实干的底层逻辑归根到底在于坚持实事求是、群众路线」），真正「段首只有引言」的是少数。
所以判定不能只看字面 —— 得问 AI，但 AI 说「已经有了」时必须**指出段首里的原句**，
指不出来就不采信。这份测试盯的就是那几处「不采信」的闸门：闸门一松，
它就会拿段末的回扣句来交差，而回扣句恰恰证明段首没亮论点。
"""
import mods.align as A


# ---- 相似度：两档要拉得开，中间不能糊 ----
def test_sim_同一句多个补充从句仍算高分():
    assert A.sim("创新是引领发展的第一动力，需以制度创新突破瓶颈。",
                 "创新是引领发展的第一动力。") >= A.TH_EXACT


def test_sim_换了说法要低于阈值():
    # 同一个论点（实干/为民），但一个重字都不共用的写法 —— 字面判不出来，必须交给 AI
    assert A.sim("实干是成就事业的基石，需以人民为中心、扎根基层。",
                 "良法是善治之前提，高质量发展的落地成效归根结底取决于实干与为民的同向发力。") \
        < A.TH_EXACT


def test_split_outline_认标签也认条数():
    ol = ["总论点：甲", "分论点1：乙", "分论点2：丙", "分论点3：丁"]
    assert A.split_outline(ol) == ("甲", ["乙", "丙", "丁"])
    # 不写标签时按「4 条 = 1 总 + 3 分」猜
    assert A.split_outline(["甲", "乙", "丙", "丁"]) == ("甲", ["乙", "丙", "丁"])
    # 只有 3 条且带分论点标签 → 没有总论点，全是分论点
    assert A.split_outline(["分论点1：乙", "分论点2：丙", "分论点3：丁"]) == ("", ["乙", "丙", "丁"])


_OL = ["总论点：以创新实干推动高质量发展。",
       "分论点1：创新是引领发展的第一动力。",
       "分论点2：实干是成就事业的基石。",
       "分论点3：开放是繁荣发展的必由之路。"]
# 第 2 段段首原样就是分论点1；第 3 段段首是引言、论点句被顶掉了；第 4 段段首是分论点3 换了说法
_TXT = "\n".join([
    "当前形势复杂多变。以创新实干推动高质量发展。",
    "创新是引领发展的第一动力。某地靠制度创新突破了瓶颈，成效显著。唯有创新方能致远。",
    "善除害者察其本，善理疾者绝其源。廖俊波扎根基层三年，使县域经济跃至全省前列。"
    "唯有实干方能成事。",
    "以开放拓展发展空间，靠合作积蓄共赢势能。某自贸区吸引外资连年增长。",
    "让我们以创新实干书写新篇。",
])


def test_survey_段首原样命中算exact不用问AI():
    got = {(x["kind"], x["i"]): x for x in A.survey(_TXT, _OL)}
    assert got[("sub", 0)]["exact"] is True, "段首原样就是分论点1，不该再花一次 AI"
    assert got[("sub", 1)]["exact"] is False, "段首是引言，字面对不上"


def test_survey_分论点只看段首前两句():
    """段末的回扣句（「唯有实干方能成事。」）即使字面像，也不算「段首亮了论点」——
       学的人对着提纲在段首找不到，提纲就是废的。"""
    got = {(x["kind"], x["i"]): x for x in A.survey(_TXT, _OL)}
    assert "唯有实干" not in got[("sub", 1)]["quote"], "把段末回扣句当成了段首论点句"


def _stub(monkeypatch, items):
    def fake(_msgs, **_kw):
        import json
        return json.dumps({"items": items}, ensure_ascii=False), None
    monkeypatch.setattr(A, "_ai_call_or_error", fake)


def test_align_AI说has但引段末回扣句不采信(monkeypatch):
    """AI 最爱拿段末的「唯有…方能…」来交差。只查「正文里有没有这句」是拦不住的
       （正文里确实有），必须连位置一起核。核不过就不采信，也不硬插 —— 标 unsure 交给人。"""
    _stub(monkeypatch, [{"k": 2, "verdict": "has", "quote": "唯有实干方能成事。"}])
    content, outline, rep = A.align(_TXT, _OL)
    sub2 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 1][0]
    assert sub2["state"] == "unsure", "段末回扣句被当成了段首论点句"
    assert content == _TXT, "不采信就不该动正文"


def test_align_段首没亮论点就把提纲那句织进去(monkeypatch):
    _stub(monkeypatch, [{"k": 2, "verdict": "none", "point": "实干是成就事业的基石。",
                         "para": "实干是成就事业的基石。善除害者察其本，善理疾者绝其源。"
                                 "廖俊波扎根基层三年，使县域经济跃至全省前列。唯有实干方能成事。"}])
    content, outline, rep = A.align(_TXT, _OL)
    p3 = A.paras(content)[2]
    assert p3.startswith("实干是成就事业的基石。"), "论点句没进段首"
    assert "善除害者察其本" in p3, "原来的引言被删了——只该顺势后移，不该删"
    assert "廖俊波" in p3, "素材被删了"
    assert [x for x in rep["items"] if x["i"] == 1 and x["kind"] == "sub"][0]["state"] == "woven"


def test_align_AI把整段重写缩水时走机械兜底(monkeypatch):
    """它爱顺手「润色」，一润色素材就没了。段落缩水就丢掉这一版，改用机械前插。"""
    _stub(monkeypatch, [{"k": 2, "verdict": "none", "point": "实干是成就事业的基石。",
                         "para": "实干是成就事业的基石。"}])       # 素材全没了
    content, _outline, _rep = A.align(_TXT, _OL)
    p3 = A.paras(content)[2]
    assert p3.startswith("实干是成就事业的基石。")
    assert "廖俊波" in p3, "缩水的那一版被采用了，素材丢了"


def test_align_提纲跑题时照正文重拟并同步提纲(monkeypatch):
    _stub(monkeypatch, [{"k": 2, "verdict": "offtopic", "point": "扎根基层才能干成事。",
                         "para": "扎根基层才能干成事。善除害者察其本。廖俊波扎根基层三年，"
                                 "使县域经济跃至全省前列。唯有实干方能成事。"}])
    content, outline, rep = A.align(_TXT, _OL)
    assert A.paras(content)[2].startswith("扎根基层才能干成事。")
    assert "扎根基层才能干成事" in outline[2], "正文改了，提纲没跟着改 —— 又对不上了"
    assert [x for x in rep["items"] if x["i"] == 1 and x["kind"] == "sub"][0]["state"] == "rewritten"


def test_align_AI调用失败时不动正文(monkeypatch):
    monkeypatch.setattr(A, "_ai_call_or_error", lambda *_a, **_k: (None, ("boom", 502)))
    content, outline, rep = A.align(_TXT, _OL)
    assert content == _TXT and outline == _OL
    assert rep["changed"] is False


def test_quick_report_不调AI也给得出对照位置():
    # 人工编辑完正文用这个刷新：位置和段首最像的句子算得出，判不准的标 unsure
    got = A.quick_report(_TXT, _OL)
    sub1 = [x for x in got if x["kind"] == "sub" and x["i"] == 0][0]
    assert sub1["state"] == "exact" and sub1["para"] == 1
    assert [x for x in got if x["kind"] == "sub" and x["i"] == 1][0]["state"] == "unsure"


def test_survey_总论点在结尾段回扣时段号要指结尾段():
    """总论点归属开头段，但常常只在结尾段回扣。para（归属段）和 qpara（引文所在段）
       分开存，否则前端会说「正文第 1 段」却引一句结尾段的话。"""
    ol = ["总论点：唯有创新方能致远。", "分论点1：甲论点。", "分论点2：乙论点。"]
    txt = "\n".join(["今天天气不错，风和日丽，适合散步。", "甲论点。某地做了事。",
                     "乙论点。某人做了事。", "唯有创新方能致远，这是时代的答案。"])
    t = [x for x in A.survey(txt, ol) if x["kind"] == "thesis"][0]
    assert "唯有创新方能致远" in t["quote"]
    assert t["para"] == 0, "总论点归属开头段"
    assert t["qpara"] == 3, "引文明明在第 4 段，段号却报成了别处"


def test_survey_oi_覆盖每条提纲且无总论点时不错位():
    """前端照 oi 对号入座。提纲没有总论点时，第一条就是分论点1 ——
       让前端按「第一条必是总论点」自己推，整份对照会错一格。"""
    ol = ["分论点1：甲论点。", "分论点2：乙论点。", "分论点3：丙论点。"]
    txt = "\n".join(["开头段引材料。", "甲论点。某地做了事。", "乙论点。某人做了事。",
                     "丙论点。某区做了事。", "结尾段升华。"])
    got = A.survey(txt, ol)
    assert [x["oi"] for x in got] == [0, 1, 2], "没有总论点时 oi 应从 0 开始"
    assert all(x["kind"] == "sub" for x in got)
    # 有总论点时则整体后移一位
    ol2 = ["总论点：总的。"] + ol
    assert [x["oi"] for x in A.survey(txt, ol2)] == [0, 1, 2, 3]


def test_split_outline_非列表当没提纲():
    """AI 偶尔把 outline 写成字符串。字符串可迭代，不挡住就会被逐字拆成一堆提纲条目。"""
    assert A.split_outline("总论点：发展") == ("", [])
    assert A.split_outline(None) == ("", [])


def test_align_非列表提纲原样奉还不打散():
    txt = "\n".join(["开头段。", "第二段。", "第三段。", "结尾段。"])
    content, outline, rep = A.align(txt, "总论点：发展")
    assert outline == "总论点：发展", "字符串提纲被 list() 拆成逐字条目了"
    assert content == txt and rep["changed"] is False


def test_strip_label_不吃以论点开头的正常句子():
    """标签分隔符必须是必需的，否则「论点鲜明才立得住」会被剥成「鲜明才立得住」。"""
    assert A.strip_label("论点鲜明才立得住") == "论点鲜明才立得住"
    assert A.strip_label("分论点1：创新是第一动力") == "创新是第一动力"
    assert A.strip_label("总论点：以创新促发展") == "以创新促发展"


def test_align_总论点的AI改写按段末校验(monkeypatch):
    """开头段的规矩是「引材料 → 末尾亮总论点」。若拿段首去卡总论点，
       AI 写对了也会被判失败、白退回机械兜底。"""
    ol = ["总论点：唯有创新方能致远。", "分论点1：甲论点。", "分论点2：乙论点。"]
    txt = "\n".join(["今天天气不错，风和日丽，适合散步，是个好天气。", "甲论点。某地做了事。",
                     "乙论点。某人做了事。", "结尾段升华一下。"])
    _stub(monkeypatch, [{"k": 0, "verdict": "none", "point": "唯有创新方能致远。",
                         "para": "今天天气不错，风和日丽，适合散步，是个好天气。唯有创新方能致远。"}])
    content, _outline, rep = A.align(txt, ol)
    assert A.paras(content)[0].endswith("唯有创新方能致远。")
    assert "AI 织入" in rep["log"][0], "AI 那一版被误判成不合格，退回了机械兜底"


def test_align_正文不足三段不动它():
    content, outline, rep = A.align("就一段话，还没写完。", _OL)
    assert rep["changed"] is False and content == "就一段话，还没写完。"
