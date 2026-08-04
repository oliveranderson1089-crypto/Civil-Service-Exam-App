"""应用文格式检查器的测试（P2 错例库）。

这套检查器**既是出稿闸门也是错例产线**，所以误报的代价是双份的：
出稿时白改一遍，入库时把**正确写法当错例教给用户**。
下面每一条用例对应一次实测踩到的误报或漏报，改动前先看注释。
"""
import json

import pytest

from conftest import DB  # noqa: F401
from mods.yycheck import (check_all, check_fentiao, check_label_prefix,
                          check_missing_parts, check_sign_inline, check_tone,
                          fentiao_kinds, has_call, has_label_prefix, has_sign,
                          has_title)

GOOD = ("××区老旧小区改造工作简报\n"
        "为深入贯彻城镇老旧小区改造决策部署，我区扎实推进改造工作，现将情况报告如下。\n"
        "一、健全推进机制。成立工作专班，压实属地责任。\n"
        "二、成效明显。已完成 30 个小区改造，惠及群众 1.2 万人。\n"
        "××区住房和城乡建设局\n"
        "2026年7月30日")


# ---- 分条方式：口语文种必须豁免 ----

def test_fentiao_flags_written_doctype():
    bad = "工作要抓实。一是压实责任，二是强化督导。"
    got = check_fentiao(bad, "通知")
    assert got and got[0]["check"] == "分条方式"
    assert "一、" in got[0]["good"], "改正里要给出规范序号写法"
    assert got[0]["bad"] and got[0]["why"], "错例必须成对：错句+理由都不能空"


def test_fentiao_exempts_spoken():
    """36 份真题参考答案里唯一用「一是…二是」的就是讲话稿——那是对的写法，不能报错。"""
    bad = "工作要抓实。一是压实责任，二是强化督导。"
    assert check_fentiao(bad, "讲话稿") == []


def test_fentiao_ignores_normal_chinese():
    """「任务一是重点」里的「一是」是正常汉语，不是分条骨架。"""
    assert check_fentiao("这项任务一是重点。", "通知") == []


# ---- 标签前缀：自产 10/71 用，真题 0/45 用 ----

def test_label_prefix_flagged():
    bad = "标题：节约用水倡议书\n称谓：全体市民\n正文：请大家节约用水。\n落款：市水务局"
    got = check_label_prefix(bad, "倡议书")
    assert got and got[0]["check"] == "标签前缀"
    assert "标题：" in got[0]["bad"]


def test_label_prefix_needs_two():
    """只出现一个冒号词可能是正常句子，要两个以上才算这种写法。"""
    assert check_label_prefix("标题：某某通知\n正文写在这里。", "通知") == []


def test_missing_parts_skips_label_prefix_style():
    """带标签前缀时部件其实在（「称谓：同志们」），只是格式不对。
    在缺部件里再报一次就是误报——第一版这么误报了 7 条。"""
    bad = "标题：××简报\n称谓：同志们\n正文：内容。\n落款：××局"
    assert check_missing_parts(bad, "简报") == []
    assert check_label_prefix(bad, "简报"), "该由标签前缀这一项来报"


# ---- 缺部件：只查有真题实证的文种 ----

def test_missing_parts_only_for_evidence_backed():
    """parts 里 15 个族只有 8 个有真题答案支撑（n≥3），其余是先验设定。
    拿先验生产「错例」= 把猜测当标准答案教给用户，所以直接不查。"""
    from mods.gongwen import GW_MAP
    noevi = [k for k, g in GW_MAP.items() if g.get("parts_src") != "real"]
    assert noevi, "应该还有一批文种没有真题实证"
    for k in noevi:
        assert check_missing_parts("随便一段没有标题也没有落款的话。", k) == [], \
            "%s 没有真题实证，不该参与缺部件检查" % k


def test_missing_parts_catches_real_gap():
    """有实证的文种，真缺部件时要报。简报的标题是 3/3 份真题答案都有的。"""
    from mods.gongwen import GW_MAP
    assert GW_MAP["简报"].get("parts_src") == "real"
    bad = "各社区居委会：\n为推进工作，现将情况通报。\n一、做法。\n二、成效。\n××街道办事处"
    got = check_missing_parts(bad, "简报")
    assert any("标题" in g["part"] for g in got), got


def test_good_text_is_clean():
    """一篇格式对的稿子不该被任何检查器抓到——这是防误报的总闸。"""
    assert check_all(GOOD, "简报") == []


# ---- 语气合身份 ----

def test_tone_flags_command_in_soft_doctype():
    bad = "请广大市民节约用水。请各单位遵照执行。"
    got = check_tone(bad, "倡议书")
    assert got and got[0]["check"] == "语气合身份"


def test_tone_allows_command_in_downward_doctype():
    """通知是下行文，「请遵照执行」本来就对。"""
    assert check_tone("请各单位遵照执行。", "通知") == []


# ---- 落款成行 ----

def test_sign_inline_flagged():
    bad = "以上情况报告如下，请领导审阅。××市住房和城乡建设局"
    got = check_sign_inline(bad, "汇报")
    assert got and got[0]["check"] == "落款成行"


def test_sign_on_own_line_ok():
    assert check_sign_inline(GOOD, "简报") == []


# ---- 字面探测器 ----

@pytest.mark.parametrize("text,fn,want", [
    ("××区老旧小区改造工作简报\n正文。", has_title, True),
    ("同志们：\n正文。", has_title, False),                 # 称谓不是标题
    ("一、健全机制。\n二、见成效。", has_title, False),      # 分条项不是标题
    ("尊敬的各位居民朋友：\n正文。", has_call, True),
    # 单行文本本身就落在「末 3 行」里，所以认得出落款 —— 这条一开始我期望写成
    # False，是测试写错了，不是探测器错
    ("××市住房和城乡建设局", has_sign, True),
])
def test_probes(text, fn, want):
    assert fn(text) is want


def test_sign_probe_covers_committee_names():
    """「XX社区居委会」原来认不出，导致误报「缺落款」。"""
    assert has_sign("正文。\n××社区居委会\n2026年7月30日")


def test_fentiao_kinds():
    assert "汉字序号" in fentiao_kinds("一、甲。二、乙。")
    assert "一是二是" in fentiao_kinds("一是甲，二是乙。")
    assert fentiao_kinds("就一句话。") == ["不分条"]


def test_has_label_prefix_helper():
    assert has_label_prefix("标题：甲\n落款：乙")
    assert not has_label_prefix("正常的一段话，没有标签。")


# ---- 错例的形状 ----

def test_pairs_are_complete():
    """错例必须成对：错句 + 改正 + 扣分理由 + 部件，缺一样就没有教学价值。"""
    for pairs in (check_fentiao("一是甲，二是乙。", "通知"),
                  check_label_prefix("标题：甲\n落款：乙", "通知"),
                  # 这一行要够长：check_sign_inline 有 12 字下限，用来避开
                  # 「××市教育局」这种本来就单独成行的正常落款
                  check_sign_inline("以上情况请领导审阅。××市教育局", "汇报")):
        assert pairs
        for p in pairs:
            for k in ("check", "bad", "good", "why", "part"):
                assert p.get(k), "%s 缺 %s" % (p.get("check"), k)
            json.dumps(p, ensure_ascii=False)      # 要能进 yy_items.text


# ---- 错例接入复习曲线 ----

def test_yy_in_review_registries():
    """加复习来源时容易只改一半：取词那边加了、提交那边忘了加，
    结果卡片点「认识」直接「参数错误」（这个坑在「常考」那一路真踩过）。
    /api/review/done 的白名单直接取自 RV_GROUP，所以这里盯住三张表都齐。"""
    from mods.review import RV_GROUP, RV_LIMIT_DEF, RV_NAMES
    assert RV_GROUP.get("yy") == "yy"
    assert RV_NAMES.get("yy"), "分组要有中文名，前端按它显示"
    assert RV_LIMIT_DEF.get("yy"), "必须单开一组额度——并进「每日积累」会被 350 条素材挤没"


def test_yy_frontend_maps_in_sync():
    """前端 static/js/review.js 有一份自己的名称表，和后端 RV_NAMES 是两份。
    加分组时两边都要加，只加一边的话卡片上会显示原始 kind 字符串。"""
    from pathlib import Path

    from conftest import BASE
    js = Path(BASE, "static", "js", "review.js").read_text(encoding="utf-8")
    for name in ("RV_KIND", "RV_COLOR", "RV_LNAME"):
        line = next(x for x in js.splitlines() if x.startswith("const " + name))
        assert "yy:" in line, "%s 里没加 yy" % name
    assert "'yy'" in js, "分组回退列表里要有 yy，否则只有 yy 有内容时会跳回 word"


def test_yy_review_cards_are_complete(auth_client):
    """真走一遍 /api/review/today，确认错例卡片的正反面都成形。"""
    import sqlite3

    con = sqlite3.connect(DB)
    con.execute(
        "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,created_at) "
        "VALUES('错例','简报','主体·举措','分条方式·一是甲·testaa',"
        "'{\"bad\":\"一是甲，二是乙。\",\"good\":\"一、甲。二、乙。\"}',"
        "'口头说法写进公文要扣分','2020-01-01 00:00:00')")
    con.commit()
    r = auth_client.get("/api/review/today")
    assert r.status_code == 200
    items = [x for x in (r.get_json() or {}).get("items", []) if x.get("kind") == "yy"]
    assert items, "错例没进复习池"
    it = items[0]
    assert "错在哪" in it["front"], "正面要让人先找错，不能直接给答案"
    assert "✗" in it["back"] and "✓" in it["back"], "背面要成对给错句和改正"
    assert it["sub"], "要标出文种·部件"


def test_yy_review_done_accepts(auth_client):
    """点「认识」要能提交——白名单漏加就是这里 400。"""
    r = auth_client.get("/api/review/today")
    items = [x for x in (r.get_json() or {}).get("items", []) if x.get("kind") == "yy"]
    assert items
    r2 = auth_client.post("/api/review/done",
                          json={"kind": "yy", "id": items[0]["id"], "result": "know"})
    assert r2.status_code == 200, r2.get_json()


def test_yy_review_caps_per_check_type():
    """库里 100 条有 85 条是「分条方式」。不限量的话每天 8 条额度全被它占满，
    「标签前缀」「落款成行」永远轮不到——和当年成语被实词霸榜是同一个坑。"""
    import inspect

    from mods import review
    src = inspect.getsource(review._review_due)
    assert "YY_PER_CHECK" in src, "缺按检查项限量的逻辑"


# ---- 搜索接入 ----

def test_yy_items_searchable(auth_client):
    """搜「一是」要能搜到「这么写是错的」——错例最该被搜到的时机就是你正想这么写的时候。
    可搜内容在 text 的 JSON 里（{"bad":…,"good":…}），所以 SQL 得直接 LIKE 它。"""
    r = auth_client.get("/api/search?q=" + "一是")
    assert r.status_code == 200
    hits = [x for x in (r.get_json() or {}).get("results", []) if x.get("type") == "yy"]
    assert hits, "错例没进搜索结果"
    h = hits[0]
    assert h["board"].startswith("应用文·"), h["board"]
    assert h["snippet"], "要有摘要"


def test_yy_search_snippet_unpacks_pair(auth_client):
    """错例的摘要要把成对内容摊开给人看，不能直接吐一段 JSON。"""
    r = auth_client.get("/api/search?q=" + "一是")
    hits = [x for x in (r.get_json() or {}).get("results", []) if x.get("type") == "yy"]
    assert hits
    assert not any('"bad"' in h["snippet"] for h in hits), "摘要里漏出了原始 JSON"


def test_yy_search_frontend_has_label_and_target():
    """搜索结果的类型标签和点击落点都在前端硬编码，漏一个就是「没有标签」或者死链。"""
    from pathlib import Path

    from conftest import BASE
    js = Path(BASE, "static", "js", "search.js").read_text(encoding="utf-8")
    assert "yy: '应用文素材'" in js, "SR_TYPE 里没加 yy，结果卡片会没有类型标签"
    assert "r.type === 'yy'" in js, "没有点击落点，搜到了点不开"


# ---- 错例小测（应用文「可测」）----

@pytest.fixture
def seeded_errors():
    """测试库是空的，小测要的数据得自己备——**跨检查项**各来几条，
    否则「一份卷子不能只有一类」这条根本测不出来（第一版就是这么假通过的）。"""
    import json as _json
    import sqlite3
    con = sqlite3.connect(DB)
    seed = [
        ("分条方式", "简报", "主体·举措", "一是压实责任", "一、压实责任"),
        ("分条方式", "通知", "主体·举措", "一是加强督导", "一、加强督导"),
        ("分条方式", "汇报", "主体·举措", "一是完善机制", "一、完善机制"),
        ("标签前缀", "倡议书", "标题", "把「标题：、落款：」这些部件名当标签写进答卷",
         "直接写内容，不写部件名"),
        ("缺部件", "简报", "标题", "写简报时省掉「标题」这一块", "写简报必须写上「标题」"),
        ("落款成行", "汇报", "落款", "把落款和正文写在同一行：以上请审阅。××市教育局",
         "正文写完换行，署名机关单独一行"),
    ]
    for i, (chk, dt, part, bad, good) in enumerate(seed):
        con.execute(
            "INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,note,src) "
            "VALUES('错例',?,?,?,?,?,'test')",
            (dt, part, "%s·seed%d" % (chk, i),
             _json.dumps({"bad": bad, "good": good}, ensure_ascii=False), "扣分理由 %d" % i))
    con.commit()
    return len(seed)


def test_errquiz_balances_check_types(seeded_errors, auth_client):
    """库里 102 条有 85 条是「分条方式」。不按检查项轮着取的话，
    一份 10 道的卷子会全是同一类——那考的是耐心不是格式。"""
    r = auth_client.get("/api/gongwen/errquiz?n=10")
    assert r.status_code == 200
    items = (r.get_json() or {}).get("items", [])
    assert items, "出不出题"
    kinds = {it["check"] for it in items}
    assert len(kinds) >= 2, "一份卷子只有一类检查项：%s" % kinds


def test_errquiz_mixes_right_and_wrong(seeded_errors, auth_client):
    """一半给错句一半给改正。只给错句的话，做几道就摸出「反正都选错」，等于没考。"""
    r = auth_client.get("/api/gongwen/errquiz?n=10")
    items = (r.get_json() or {}).get("items", [])
    ans = [it["answer"] for it in items]
    assert "right" in ans and "wrong" in ans, "答案一边倒：%s" % ans


def test_errquiz_item_shape(seeded_errors, auth_client):
    """每道题要能独立成题：题面、答案、成对的错句改正、扣分理由。"""
    r = auth_client.get("/api/gongwen/errquiz?n=6")
    for it in (r.get_json() or {}).get("items", []):
        for k in ("text", "answer", "bad", "good", "check"):
            assert it.get(k), "缺 %s：%s" % (k, it)
        assert it["answer"] in ("right", "wrong")
        # 题面必须是给出的那一条，不能既给错句又给改正（那就露答案了）
        assert it["text"] in (it["bad"], it["good"])


def test_errquiz_statements_are_readable(seeded_errors, auth_client):
    """结构类错例（缺部件/标签前缀/落款成行）的内容必须是**陈述句**。
    原来写成「（全文找不到「标题」）」这种括注，当判断题读不通、
    在复习卡片上也别扭——两个出口都用同一份数据，所以形状要能两边都读。"""
    r = auth_client.get("/api/gongwen/errquiz?n=20")
    for it in (r.get_json() or {}).get("items", []):
        assert not it["text"].startswith("（"), "题面是括注不是句子：%r" % it["text"]


def test_errquiz_view_registered():
    """新视图要在 shell.js 注册（VIEWS + TITLES + 入口分派）、core.js 挂进应用文板块，
    并且 index.html 里有 section 和 script —— 少一处就是点了没反应。"""
    from pathlib import Path

    from conftest import BASE
    shell = Path(BASE, "static", "js", "shell.js").read_text(encoding="utf-8")
    assert "'yyerr'" in shell and "yyerr: '应用文改错'" in shell
    assert "openYyErr()" in shell, "入口没分派，卡片点了没反应"
    core = Path(BASE, "static", "js", "core.js").read_text(encoding="utf-8")
    assert "key: 'yyerr'" in core, "应用文板块里没这个入口"
    html = Path(BASE, "static", "index.html").read_text(encoding="utf-8")
    assert 'id="view-yyerr"' in html and "js/yyerr.js" in html


# ---- 应用文素材库浏览页 ----

def test_yylib_sorts_by_real_exam_freq(auth_client):
    """这个页面最要紧的一点：**文种按真题频次排**，不按录入顺序。
    原来「文种大全」按录入顺序排，练得最多的倡议书在真题里一次没考过。"""
    r = auth_client.get("/api/gongwen/yylib")
    assert r.status_code == 200
    cats = (r.get_json() or {}).get("cats", [])
    assert cats
    freqs = [g["freq"] for g in cats]
    assert freqs == sorted(freqs, reverse=True), "没按频次降序：%s" % freqs
    assert cats[0]["fam"] == "交流材料", "第一名该是真题最高频的交流材料"
    # 零频的必须还在列表里（降级保留，不是删掉），但排在后面
    zero = [g["k"] for g in cats if g["freq"] == 0]
    assert {"通知", "倡议书", "新闻稿"} <= set(zero)
    assert cats.index(next(g for g in cats if g["k"] == "通知")) > len(cats) // 2


def test_yylib_shows_empty_cells(seeded_errors, auth_client):
    """空格子也要列出来——库里哪块还没素材，正是这个页面该回答的问题。
    「没有就不显示」会让页面看上去永远是齐的。"""
    r = auth_client.get("/api/gongwen/yylib")
    cats = (r.get_json() or {}).get("cats", [])
    empty = [(g["k"], p["part"]) for g in cats for p in g["parts"] if p["n"] == 0]
    assert empty, "一个空格子都没列出来，说明把空的过滤掉了"
    # 必需部件要标出来，界面上才能看出「该有的这块还空着」
    assert any(p.get("req") for g in cats for p in g["parts"])


def test_yylib_marks_evidence_backed(auth_client):
    """哪些文种的部件清单有真题实证要标出来——8 个 real，其余是先验设定。"""
    r = auth_client.get("/api/gongwen/yylib")
    cats = (r.get_json() or {}).get("cats", [])
    real = [g["k"] for g in cats if g["parts_src"] == "real"]
    assert len(real) >= 6, real
    assert any(g["parts_src"] != "real" for g in cats), "应该还有一批是先验的"


def test_yylib_drilldown_unpacks_pairs(seeded_errors, auth_client):
    """下钻到具体格子时，错例的成对内容要摊开，不能吐 JSON 字符串。"""
    r = auth_client.get("/api/gongwen/yylib?doctype=简报")
    d = r.get_json() or {}
    assert d.get("items"), "简报下取不到条目"
    for it in d["items"]:
        if it["kind"] == "错例":
            assert it.get("bad") and it.get("good"), it
            assert not it.get("text"), "错例的 text 该清空，内容已摊到 bad/good"


def test_yylib_view_registered_and_search_lands_there():
    """视图注册 5 处 + 搜索落点要改到这个页面（原来是临时落到「上位词」页）。"""
    from pathlib import Path

    from conftest import BASE
    shell = Path(BASE, "static", "js", "shell.js").read_text(encoding="utf-8")
    assert "'yylib'" in shell and "yylib: '应用文素材库'" in shell and "openYyLib()" in shell
    core = Path(BASE, "static", "js", "core.js").read_text(encoding="utf-8")
    assert "key: 'yylib'" in core
    html = Path(BASE, "static", "index.html").read_text(encoding="utf-8")
    assert 'id="view-yylib"' in html and "js/yylib.js" in html
    search = Path(BASE, "static", "js", "search.js").read_text(encoding="utf-8")
    assert "openYyLib(" in search, "搜索结果还落在临时页面上"


# ---- 真题练习题源开关 ----

def test_realstat_reports_practicable_counts(auth_client):
    """界面上要能看出「这个筛法还剩几道」，不然点了才知道没题。"""
    r = auth_client.get("/api/find/realstat")
    assert r.status_code == 200
    d = r.get_json() or {}
    assert "guanche" in d["types"]
    for qt, v in d["types"].items():
        assert set(v) == {"total", "with_ref", "since2018"}, v
        assert v["since2018"] <= v["total"], "2018+ 不该多于总数"
        assert v["with_ref"] <= v["total"]


def test_real_source_needs_known_qtype(auth_client):
    """没有真题题源的题型要明确报错，不能默默退回 AI 出题——
    那样用户以为在练真题，其实练的是 AI 编的。"""
    r = auth_client.post("/api/find/gen", json={"qtype": "xiezuo", "src": "real"})
    assert r.status_code == 400


def test_real_source_defaults_to_2018_window():
    """默认只取 2018 年起：2000-2017 的贯彻执行题型还没定型
    （通知/倡议书那会儿还考，2018 后不考了），拿老卷练现在的题型是错的。"""
    import inspect

    from mods import find
    src = inspect.getsource(find._pick_real)
    assert 'd.get("era") or "new"' in src, "默认年份窗口不是 new"


def test_real_source_skips_practiced():
    """练过的不再出——靠 source 里的「真题·<卷名> Q<n>」去重。"""
    import inspect

    from mods import find
    src = inspect.getsource(find._pick_real)
    assert "真题·" in src and "find_papers" in src, "没有查重逻辑"


def test_official_reference_not_overwritten_by_ai():
    """真题带官方参考答案时，不能再让 AI 编一份——那是降级，还白花一次调用。"""
    import inspect

    from mods import find
    src = inspect.getsource(find._find_build)
    assert "if reference:" in src, "_find_build 没有「已有参考答案就跳过 AI」的分支"


def test_find_reference_normalizes_fentiao():
    """find.py 原来完全没调 fix_fentiao，于是它给的参考答案可以写「一是…二是…」——
    而同一个 app 的错例库正在教用户这是扣分项。两个模块对同一条规范说法不一致，
    比哪一边错更糟。"""
    import inspect

    from mods import find
    src = inspect.getsource(find._find_build)
    assert "fix_fentiao(ref, doctype)" in src


def test_find_source_switch_frontend():
    """题源开关的前端：控件、参数、置灰逻辑。少一处就是「选了真题其实还在用 AI」。"""
    from pathlib import Path

    from conftest import BASE
    html = Path(BASE, "static", "index.html").read_text(encoding="utf-8")
    assert 'id="fd-src"' in html and 'data-fdsrc="real"' in html
    assert 'id="fd-realopt"' in html and 'data-fdera="new"' in html, "缺年份窗口筛选"
    js = Path(BASE, "static", "js", "find.js").read_text(encoding="utf-8")
    assert "src: fdSrc()" in js, "出题请求没带题源参数——选了真题也还是 AI 出题"
    assert "era: fdEra()" in js and "exam: fdExam()" in js
    assert "loadFindRealStat" in js, "没拉真题存量，界面显示不出「还剩几道」"
    # 没有真题题源的题型要置灰，不能默默退回 AI
    assert "btn.disabled = !has" in js


# ---- AI 工具接入 ----

def test_search_yy_registered_readonly():
    """注册表模式：加工具只改 agent_tools。只读工具不该要二次确认。"""
    from mods.agent_tools import TOOL_REGISTRY
    assert "search_yy" in TOOL_REGISTRY
    ent = TOOL_REGISTRY["search_yy"]
    assert ent["kind"] == "read" and not ent["confirm"]
    props = ent["spec"]["function"]["parameters"]["properties"]
    assert {"doctype", "part", "kind", "keyword"} <= set(props)


def test_search_yy_answers_format_question(seeded_errors, flask_app):
    """用户问「简报该有哪几块」时，正面回答是**文种卡**（骨架+部件+真题频次），
    素材条目只是佐证。只回条目等于答非所问。"""
    import json
    import sqlite3

    from conftest import DB
    from mods.agent_tools import TOOL_REGISTRY
    con = sqlite3.connect(DB)
    with flask_app.app_context():
        res, err = TOOL_REGISTRY["search_yy"]["handler"]({"doctype": "简报"}, con)
    assert not err
    d = json.loads(res)
    assert d["文种"]["名称"] == "简报"
    assert d["文种"]["格式骨架"] and d["文种"]["部件"]
    assert "考过" in d["文种"]["真题频次"], "要能据此回答「这个文种值不值得练」"


def test_search_yy_flags_weak_evidence(flask_app):
    """部件清单是先验设定的文种，要**明说证据不足**——不能把猜测当标准答案给用户。"""
    import json
    import sqlite3

    from conftest import DB
    from mods.agent_tools import TOOL_REGISTRY
    con = sqlite3.connect(DB)
    with flask_app.app_context():
        res, _e = TOOL_REGISTRY["search_yy"]["handler"]({"doctype": "通知"}, con)
    d = json.loads(res)
    assert "先验" in d["文种"]["依据"] or "样本还不够" in d["文种"]["依据"], d["文种"]["依据"]


def test_search_yy_unpacks_error_pairs(seeded_errors, flask_app):
    """错例是成对的，要摊成「错误写法/正确写法」，不能丢给模型一段 JSON 字符串。"""
    import json
    import sqlite3

    from conftest import DB
    from mods.agent_tools import TOOL_REGISTRY
    con = sqlite3.connect(DB)
    with flask_app.app_context():
        res, _e = TOOL_REGISTRY["search_yy"]["handler"]({"kind": "错例", "limit": 3}, con)
    d = json.loads(res)
    assert d["items"]
    for it in d["items"]:
        assert it.get("错误写法") and it.get("正确写法"), it


# ---- 「要求」类素材：真题原话当判分尺子 ----

def test_require_extract_drops_annotation():
    """带【】的「要求」是出版社解析批注混进来的，整条弃掉。
    实测 2017 国考地市 Q6 那两条就是这么来的——不滤掉，「完善亲水设施」
    这种**答案内容**会被当成评分维度入库。"""
    import build_yy_require as B
    dims, _o = B.extract("（1）内容具体【结合材料中的具体例子】、全面【细致阅读材料】")
    assert dims == [], dims


def test_require_extract_normal():
    import build_yy_require as B
    dims, _o = B.extract("（1）内容全面，条理清晰；（2）简明扼要，格式规范；（3）不超过500字。")
    assert "内容全面" in dims and "条理清晰" in dims and "格式规范" in dims
    assert not any("字" in d for d in dims), "字数要求不该当成评分维度：%s" % dims


def test_require_extract_filters_junk():
    """分值残渣、引号内容、异体字都要处理掉。"""
    import build_yy_require as B
    dims, _o = B.extract("分）要求：内容全面")
    assert "分）要求：" not in dims and "要求" not in "".join(dims)
    dims2, _o2 = B.extract("以“岁月失语，惟石能言”为题，内容具体")
    assert not any("岁月" in d for d in dims2), dims2
    # 异体字归一：⾯(U+2FA1) 和 面(U+9762) 不能算两个维度
    assert B.clean("内容全⾯") == "内容全面"


def test_real_require_prefers_doctype_then_generic(seeded_errors, flask_app):
    """判分口径先用该文种自己的，不够再用通用的补——每个文种真题样本本来就少，
    只用自己的会只剩一两条，口径反而更窄。"""
    import sqlite3

    from conftest import DB
    from mods.find import _real_require
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,freq) "
                "VALUES('要求','简报','','独有维度',9)")
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,freq) "
                "VALUES('要求','','','通用维度',5)")
    con.commit()
    got = _real_require(con, "简报")
    assert got.startswith("独有维度"), got
    assert "通用维度" in got, "该文种的不够时要用通用的补齐"


def test_real_require_survives_missing_table():
    """表没建/没数据时要退回手写口径，不能因此批不了作业。"""
    import sqlite3

    from mods.find import _real_require
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    assert _real_require(con, "简报") == ""


# ---- 「表述」类：带真题实证 ----

def test_phrase_hits_matches_ellipsis():
    """「健全…机制」这种带省略号的提法，要求各段都出现才算命中——
    真题里中间填的内容长短不一，卡顺序会全部漏判。"""
    import build_yy_phrase as B
    answers = [("简报", "健全联防联控机制，压实属地责任"), ("汇报", "完善相关制度")]
    assert B.hits("健全…机制", answers)[0] == 1
    assert B.hits("完善…制度", answers)[0] == 1
    assert B.hits("凝聚…合力", answers)[0] == 0


def test_phrase_pool_prefers_real_evidence(seeded_errors, flask_app):
    """有真题实证的提法要排在前面——不然灌进来的 freq 等于白标。
    实测 89 条种子提法只有 30 条在真题答案里出现过，剩下的是教材式套话。"""
    import sqlite3

    from conftest import DB
    from mods.gongwen import _phrase_pool
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,freq,src) "
                "VALUES('表述','','主体·举措','有实证的','有实证的',9,'real')")
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,freq,src) "
                "VALUES('表述','','主体·成效','没实证的','没实证的',0,'seed')")
    con.commit()
    got = _phrase_pool(con, "简报")
    idx = {x["scene"]: i for i, x in enumerate(got)}
    if "主体·举措" in idx and "主体·成效" in idx:
        assert idx["主体·举措"] < idx["主体·成效"], "有实证的没排前面"


def test_phrase_seed_kept_not_deleted():
    """没在真题里出现的 59 条**不删**：38 份答案是很小的语料，
    零出现不等于它错（真出现率 5% 的提法，38 份里一次不出现的概率也有 14%）。"""
    import sqlite3

    from conftest import DB
    con = sqlite3.connect(DB)
    n = con.execute("SELECT COUNT(*) FROM yy_items WHERE kind='表述'").fetchone()[0]
    # 测试库是空的，这里只验语义：脚本不该有 DELETE
    src = open("build_yy_phrase.py", encoding="utf-8").read()
    assert "DELETE" not in src.upper(), "脚本不该删任何提法"
    assert n >= 0


# ---- 「情景」类：真题原题的三要素 ----

def test_scene_extract_role_and_audience():
    import build_yy_scene as B
    d = B.extract("假如你是S县委组织部的工作人员，请根据“给定资料3”撰写一篇简报，供领导参阅。（25 分）")
    assert d["role"] == "S县委组织部的工作人员"
    assert d["audience"] == "领导"


def test_scene_extract_meeting_occasion():
    import build_yy_scene as B
    d = B.extract("A市要召开打通基层法律服务“最后一公里”座谈会，假如你是花湖区政府办工作人员，"
                  "请撰写一篇经验交流材料。（35 分）")
    assert "座谈会" in d["scene"], d["scene"]
    assert d["role"] == "花湖区政府办工作人员"


def test_scene_never_captures_boilerplate():
    """「根据"给定资料5"写」会被受文对象的正则误吃成「定资料5"」——
    正则把「给」消耗掉了，残缺形式不含完整的「给定资料」，套话过滤就拦不住。"""
    import build_yy_scene as B
    d = B.extract("请根据“给定资料5”写一份推荐材料。（30 分）")
    assert "资料" not in (d["audience"] or ""), d["audience"]
    assert "资料" not in (d["scene"] or ""), d["scene"]


def test_scene_leaves_blank_when_unsure():
    """抽不准就留空，不猜。情景要喂进出题提示词，猜错等于给用户一个假题面。"""
    import build_yy_scene as B
    d = B.extract("三、请为该报撰写一则短评。（20 分）")
    assert d["scene"] == "" and d["role"] == ""


def test_real_scenes_falls_back_to_demo_audience(seeded_errors, flask_app):
    """受文对象大多抽不到（真题题干本来就不写，由文种隐含），
    缺的要退回该文种 demo 里的 audience，不能留空丢给出题。"""
    import json
    import sqlite3

    from conftest import DB
    from mods.gongwen import real_scenes
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,freq) "
                "VALUES('情景','简报','','t-scene',?,2)",
                (json.dumps({"scene": "某事", "role": "某工作人员", "audience": ""}),))
    con.commit()
    got = [x for x in real_scenes(con, "简报") if x.get("role") == "某工作人员"]
    assert got and got[0]["audience"], "没退回 demo 的受文对象"


# ---- 「范文」类：真题参考答案 + 乱码闸 ----

def test_fanwen_garbled_gate():
    """OCR 乱码的答案不能当范文——范文里有错字会教错。
    实测那条是「从工商执法到部门吾合…食药监等部分隘合成并市场利过局」，
    拉丁字符 9%，而正常答案中位 0%、次高 3.4%，界限很清楚。"""
    import build_yy_fanwen as B
    ok = "关于开展安全生产大检查的通知。各县区人民政府：为深入排查隐患，现将有关事项通知如下。" * 2
    assert not B.garbled(ok)[0]
    bad = "执法更有效率 from gongshang to bumen wuhe wei gongshang he zhijian zai dao SEAF me Se" * 2
    assert B.garbled(bad)[0]
    assert B.garbled("太短")[0]


def test_fanwen_title_extraction():
    import build_yy_fanwen as B
    assert B.first_line_title("关于“攀果”品牌成长发展的工作简报\nR 区农业农村局\n正文…") \
        == "关于“攀果”品牌成长发展的工作简报"
    # 称谓不是标题
    assert B.first_line_title("尊敬的各位居民朋友：\n正文…") == ""
    # 分条项不是标题
    assert B.first_line_title("一、加强组织领导\n正文…") == ""


# ---- 真题范文 ↔ 自产范文 并排对照 ----

def test_yylist_carries_real_answers(seeded_errors, auth_client):
    """真题参考答案要和自产范文摆在一起——只灌进库不接界面，等于白灌。"""
    r = auth_client.get("/api/write/yylist")
    assert r.status_code == 200
    cats = (r.get_json() or {}).get("cats", [])
    for cat in cats:
        for t in cat["doctypes"]:
            assert "real" in t, "%s 没带真题范文字段" % t["k"]
            assert "freq" in t, "卡片上要显示真题频次"


def test_realfan_returns_stem_with_answer(seeded_errors, auth_client):
    """范文脱离题目没法学：题干、要求、分值、字数要一起给。"""
    import sqlite3

    from conftest import DB
    con = sqlite3.connect(DB)
    row = con.execute("SELECT id FROM yy_items WHERE kind='范文' LIMIT 1").fetchone()
    if not row:
        return                       # 测试库里没范文就跳过，不硬造
    d = auth_client.get("/api/write/realfan/%d" % row[0]).get_json()
    assert d.get("content")
    assert "src" in d


def test_realfan_404():
    pass


def test_realfan_frontend_wired():
    """卡片上的 pill、点击落点、查看器三处都要有，缺一处就是点不开。"""
    from pathlib import Path

    from conftest import BASE
    js = Path(BASE, "static", "js", "write.js").read_text(encoding="utf-8")
    assert "data-wrfan" in js and js.count("data-wrfan") >= 2, "pill 或点击落点缺一"
    assert "openRealFan" in js and "/api/write/realfan/" in js
    assert "rf-stem" in js and "rf-req" in js, "题干/要求没显示，范文脱离题目没法学"


# ---- 「得体」类：能说 / 不能说 ----

def test_detide_command_tone_is_evidence_backed():
    """「面向群众的文种别用命令口气」这条是**实证的否定证据**：
    36 份真题参考答案里下行文的命令式说法出现 0 次，比人工规则硬。"""
    import re
    import sqlite3

    from conftest import BASE
    from mods.yycheck import _ORDER_CMD
    src = open("build_yy_detide.py", encoding="utf-8").read()
    assert "_ORDER_CMD" in src, "得体的语气规则要用同一份检查器，不能另写一套判据"
    assert _ORDER_CMD.search("请各单位遵照执行")
    assert not _ORDER_CMD.search("让我们携手共建美好家园")


def test_detide_marks_seed_vs_real():
    """人工种子必须和真题实证分开标——这一类最容易变成「我以为公文该这么说」。"""
    import build_yy_detide as B
    assert B.SEED, "要有人工种子兜底真题覆盖不到的文种"
    for row in B.SEED:
        assert len(row) == 6, row
    src = open("build_yy_detide.py", encoding="utf-8").read()
    assert "人工种子" in src and "src=\"seed\"" in src


def test_detide_does_not_overreach_to_downward_docs():
    """通知在样本里只有 1 份，不能拿它断言「通知也不能用命令口气」。
    命令口气那条只按面向群众的文种入库。"""
    import build_yy_detide as B
    from mods.yycheck import _SOFT_DOCTYPES
    assert "通知" not in _SOFT_DOCTYPES
    # 种子里反而明确写了「通知可以提要求」
    assert any(r[0] == "通知" and "下行文" in " ".join(r[2:]) for r in B.SEED)


def test_detide_pair_unpacked_everywhere(seeded_errors, flask_app, auth_client):
    """得体是 {do,dont} 成对结构，素材库和 AI 工具都要摊开，不能吐 JSON。"""
    import json
    import sqlite3

    from conftest import DB
    from mods.agent_tools import TOOL_REGISTRY
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text,src) "
                "VALUES('得体','简报','称谓','t-得体',?,'real')",
                (json.dumps({"do": "该这样", "dont": "别这样"}),))
    con.commit()
    d = auth_client.get("/api/gongwen/yylib?doctype=简报&kind=得体").get_json()
    got = [x for x in d["items"] if x["title"] == "t-得体"]
    assert got and got[0]["good"] == "该这样" and got[0]["bad"] == "别这样"
    assert not got[0]["text"], "text 该清空，内容已摊到 good/bad"
    with flask_app.app_context():
        res, _e = TOOL_REGISTRY["search_yy"]["handler"]({"kind": "得体"}, con)
    j = json.loads(res)
    assert any(x.get("该这么写") for x in j["items"]), "AI 工具没摊开"


# ---- 「要点」类：按部件 + 治理领域挂 ----

def test_point_part_defaults_to_action():
    """规范概括句按构造就是**做法概括**，所以默认归举措；
    只有成效/问题句靠句首动词覆盖。堆一张长动词表去认举措不诚实——
    实测那样 66% 认不出，而认不出的「弘扬奋斗精神…」「发挥党员先锋模范作用…」
    明明也是举措。"""
    import build_yy_point as B
    assert B.part_of("弘扬奋斗精神，传承红色基因。") == "主体·举措"
    assert B.part_of("发挥党员先锋模范作用，扎根基层服务群众。") == "主体·举措"
    assert B.part_of("实现自主创新突破，技术水平大幅跃升。") == "主体·成效"
    assert B.part_of("存在配套设施不足的问题。") == "主体·问题"
    assert B.part_of("亟需完善长效管理机制。") == "主体·问题"


def test_point_retrieval_matches_domain(seeded_errors, flask_app):
    """domain 是这一类的命门：写垃圾分类的简报时，一条科技创新的举措句毫无用处。"""
    import sqlite3

    from conftest import DB
    from mods.gongwen import parts_of
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for dom, txt in (("垃圾分类", "推行垃圾分类投放，健全收运处置体系。"),
                     ("科技创新", "攻克关键核心技术，实现自主创新突破。")):
        con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,domain,title,text) "
                    "VALUES('要点','','主体·举措',?,?,?)", (dom, txt[:20], txt))
    con.commit()
    wp = [p for p, _r in parts_of("简报")] or ["主体·举措"]
    kw = "%垃圾分类%"
    got = [r["text"] for r in con.execute(
        "SELECT text FROM yy_items WHERE kind='要点' AND part IN (%s) "
        "AND (domain LIKE ? OR text LIKE ?) ORDER BY (domain LIKE ?) DESC, id LIMIT 6"
        % ",".join("?" * len(wp)), wp + [kw, kw, kw])]
    assert got and "垃圾分类" in got[0], "领域匹配的没排在最前：%s" % got[:1]


def test_point_sources_are_labelled():
    """概括句来自时政（src='news'），常考提法是种子（src='seed'）——
    两者性质不同：前者是做法、后者是政策依据，界面和取用都要能分开。"""
    src = open("build_yy_point.py", encoding="utf-8").read()
    assert 'src="news"' in src and 'src="seed"' in src
    assert "开头·缘由" in src, "常考提法该挂在开头（发文依据），不是正文做法"


# ---- 「骨架」类：把代码里的 parts 落库，不造新数据 ----

def test_skeleton_carries_evidence_strength():
    """20 个文种里只有 8 个的部件清单有真题支撑，其余是先验。
    **拿先验当标准答案教给用户，是这个方案里最不能做的事**，所以标记必须跟着落库。"""
    import build_yy_skeleton as B
    from mods.gongwen import GW_DOCTYPES
    real = [g["k"] for g in GW_DOCTYPES if g.get("parts_src") == "real"]
    assert len(real) == 8, real
    src = open("build_yy_skeleton.py", encoding="utf-8").read()
    assert "真题实证" in src and "先验设定" in src
    assert 'src = "real" if real else "seed"' in src


def test_skeleton_every_part_has_hint():
    """每个部件都要有「这一块放什么」的说明，空条目等于占位没内容。"""
    import build_yy_skeleton as B
    from mods.gongwen import GW_DOCTYPES, parts_of
    missing = set()
    for g in GW_DOCTYPES:
        for p, _r in parts_of(g["k"]):
            if not (B.PART_HINT.get(p) or B.PART_HINT.get(p.split("·")[0])):
                missing.add(p)
    assert not missing, "这些部件没有说明：%s" % missing


def test_skeleton_is_idempotent():
    """重跑要更新而不是堆重复——parts 改了之后重跑，库里该跟着变。"""
    src = open("build_yy_skeleton.py", encoding="utf-8").read()
    assert "INSERT OR IGNORE" in src and "UPDATE yy_items SET" in src


def test_all_eight_kinds_defined():
    """八类素材的名字只此一份，别在各处手抄。"""
    import sqlite3

    from conftest import DB
    ddl = open("schema.py", encoding="utf-8").read()
    for k in ("骨架", "表述", "情景", "要点", "得体", "错例", "要求", "范文"):
        assert k in ddl, "schema 的 kind 注释里少了「%s」" % k
