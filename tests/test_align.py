"""提纲 ↔ 正文 对照（mods/align）。

对齐现在**只展示、不改写已有正文**：提纲归提纲、全文归全文。
  · 同义表述（正文换了说法，讲的还是这条分论点）→ 正文一字不动，state=same，
    把正文里对应那句摘出来当「另一种写作思路」并排显示；
  · 补充缺失（某条分论点在正文里根本没有对应段落）→ 参考提纲补写**一段**，
    插在结尾段之前，且补完全文仍须 ≤ wmax 字，塞不下就只报出来（nopara）。
唯一会动正文的就是「补写一段原本缺失的分论点段落」，其余任何情况都不碰已有段落。

这份测试盯的就是这两条边界：同义句绝不回改正文、补写受字数上限约束。
"""
import mods.align as A


# ---- 相似度：两档要拉得开，中间不能糊 ----
def test_sim_同一句多个补充从句仍算高分():
    assert A.sim("创新是引领发展的第一动力，需以制度创新突破瓶颈。",
                 "创新是引领发展的第一动力。") >= A.TH_EXACT


def test_sim_换了说法要低于阈值():
    # 同一个论点（实干/为民），但一个重字都不共用的写法 —— 字面判不出来，当同义表述并排展示
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

# 正文只有两个论证段（段 2、段 3），提纲却有三条分论点 —— 分论点3 在正文里没有对应段落
_OL_MISS = _OL
_TXT_MISS = "\n".join([
    "开头段引材料。以创新实干推动高质量发展。",
    "创新是引领发展的第一动力。某地靠制度创新突破了瓶颈，成效显著。",
    "实干是成就事业的基石。廖俊波扎根基层三年，使县域经济跃至全省前列。",
    "让我们以创新实干书写新篇。",
])


def _stub(monkeypatch, items):
    def fake(_msgs, **_kw):
        import json
        return json.dumps({"items": items}, ensure_ascii=False), None
    monkeypatch.setattr(A, "_ai_call_or_error", fake)


def _no_ai(monkeypatch):
    """没有缺失分论点时绝不该调 AI —— 调了就让测试当场炸。"""
    def boom(*_a, **_k):
        raise AssertionError("不该调 AI：没有缺失的分论点，只是展示对照")
    monkeypatch.setattr(A, "_ai_call_or_error", boom)


def test_survey_段首原样命中算exact不用问AI():
    got = {(x["kind"], x["i"]): x for x in A.survey(_TXT, _OL)}
    assert got[("sub", 0)]["exact"] is True, "段首原样就是分论点1，算 exact"
    assert got[("sub", 1)]["exact"] is False, "段首是引言，字面对不上"


def test_survey_分论点只看段首前两句():
    """段末的回扣句（「唯有实干方能成事。」）即使字面像，也不算「段首亮了论点」——
       学的人对着提纲在段首找不到，提纲就是废的。"""
    got = {(x["kind"], x["i"]): x for x in A.survey(_TXT, _OL)}
    assert "唯有实干" not in got[("sub", 1)]["quote"], "把段末回扣句当成了段首论点句"


def test_align_同义表述只展示不改正文(monkeypatch):
    """正文换了说法但讲的是同一条分论点 —— 正文一字不动，标 same、并排显示正文那句，
       而且这条路径压根不该调 AI（没有缺失分论点要补写）。"""
    _no_ai(monkeypatch)
    content, outline, rep = A.align(_TXT, _OL)
    assert content == _TXT, "同义表述不该改动正文"
    assert outline == _OL, "提纲不该被回改"
    assert rep["changed"] is False
    sub2 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 1][0]
    assert sub2["state"] == "same", "换了说法的分论点应标 same（另一种写作思路）"
    assert sub2["quote"], "same 要给出正文里对应那句，好并排显示"
    # 段首原样命中的仍是 exact
    sub1 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 0][0]
    assert sub1["state"] == "exact"


def test_align_缺失分论点参考提纲补写(monkeypatch):
    """某条分论点正文里完全没有对应段落 → 参考提纲补写一段，插在结尾段之前，标 added。
       这是唯一会动正文的分支。"""
    # 提纲第 3 条分论点在正文里没段落，AI 返回它的补写段（编号按提纲里的第 3 条 → i=3）
    _stub(monkeypatch, [{"i": 3, "para": "开放是繁荣发展的必由之路。某自贸区吸引外资连年增长，"
                                         "区域合作释放共赢红利。"}])
    content, outline, rep = A.align(_TXT_MISS, _OL_MISS, wmax=2000)
    ps = A.paras(content)
    assert len(ps) == 5, "补写段没插进去（原 4 段应变 5 段）"
    assert "开放是繁荣发展的必由之路" in content
    assert ps[-1] == "让我们以创新实干书写新篇。", "补写段应插在结尾段之前，别顶掉结尾"
    sub3 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 2][0]
    assert sub3["state"] == "added"
    assert rep["changed"] is True and rep["log"]
    # 已有的两段一字未动
    assert "创新是引领发展的第一动力。某地靠制度创新突破了瓶颈，成效显著。" in content
    assert "实干是成就事业的基石。廖俊波扎根基层三年" in content


def test_align_补写会超字数就只报不写(monkeypatch):
    """补一段就顶破字数上限的，这条只报出来（nopara），绝不为补一段把全文写超。"""
    _stub(monkeypatch, [{"i": 3, "para": "开放是繁荣发展的必由之路。某自贸区吸引外资连年增长。"}])
    content, _outline, rep = A.align(_TXT_MISS, _OL_MISS, wmax=10)   # 上限卡得极低，怎么都塞不下
    assert content == _TXT_MISS, "超字数就不该补，正文要原样"
    sub3 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 2][0]
    assert sub3["state"] == "nopara"
    assert rep["changed"] is False


def test_align_补写的AI调用失败时不动正文(monkeypatch):
    monkeypatch.setattr(A, "_ai_call_or_error", lambda *_a, **_k: (None, ("boom", 502)))
    content, _outline, rep = A.align(_TXT_MISS, _OL_MISS)
    assert content == _TXT_MISS and rep["changed"] is False
    sub3 = [x for x in rep["items"] if x["kind"] == "sub" and x["i"] == 2][0]
    assert sub3["state"] == "nopara"


def test_align_没缺失分论点时不调AI也不动正文(monkeypatch):
    _no_ai(monkeypatch)
    content, outline, rep = A.align(_TXT, _OL)
    assert content == _TXT and outline == _OL and rep["changed"] is False


def test_quick_report_不调AI也给得出对照位置():
    # 人工编辑完正文用这个刷新：段首命中算 exact，换了说法算 same，都是字面算得出的
    got = A.quick_report(_TXT, _OL)
    sub1 = [x for x in got if x["kind"] == "sub" and x["i"] == 0][0]
    assert sub1["state"] == "exact" and sub1["para"] == 1
    assert [x for x in got if x["kind"] == "sub" and x["i"] == 1][0]["state"] == "same"


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


def test_align_正文不足三段不动它():
    content, outline, rep = A.align("就一段话，还没写完。", _OL)
    assert rep["changed"] is False and content == "就一段话，还没写完。"
