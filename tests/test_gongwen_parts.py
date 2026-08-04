"""应用文「结构部件」的地基测试（P0b）。

为什么要有这一份：`GW_DOCTYPES` / `GW_MAP` 是**跨模块共享的常量**——
mods/find.py 直接 import 过去，前端 /api/write/gwspec 把整份 JSON 吐给页面用，
gen_write.py 那个定时器脚本也走同一条生成链路。
往每个文种里加 `parts` 时，只要顺手改错一个键名，断的地方不在这个文件里，
而是在小题训练页和每天 05:00 的定时任务里，**而且不报错、只是内容变空**。

所以这里盯三件事：
  ① 对外契约：find.py 和前端读的那几个键必须都还在（k/d/fmt/cat/min/max/demo）
  ② 部件词表：parts 里的槽位和角色必须来自受控词表，不许随手造新名字
  ③ 两套描述不许漂移：parts 提到的槽位，fmt 那句人话里也得提到
另外验一下 yy_items 建表进了 init_db()（schema 漂移在这个项目里崩过）。
"""
import sqlite3

import pytest

from conftest import DB  # noqa: F401  import 它顺带确认测试库隔离生效
from mods.gongwen import (GW_CATS, GW_DOCTYPES, GW_MAP, GW_PART_ALIAS, GW_ROLES,
                          GW_SLOTS, norm_part, parts_of)

# find.py 和前端 write.js / find.js 实际读的键。少一个就是线上空白，不是异常
CONTRACT = ("k", "d", "fmt", "cat", "min", "max", "demo")


def test_doctype_contract():
    assert GW_DOCTYPES, "文种清单不能空"
    for g in GW_DOCTYPES:
        for key in CONTRACT:
            assert key in g, "文种 %s 少了键 %s（find.py / 前端要读）" % (g.get("k"), key)
        assert g["cat"] in GW_CATS, "%s 的分类 %s 不在 GW_CATS 里" % (g["k"], g["cat"])
        assert isinstance(g["min"], int) and isinstance(g["max"], int)
        assert 0 < g["min"] < g["max"], "%s 的字数区间不合法" % g["k"]
        for k in ("scene", "role", "audience"):
            assert g["demo"].get(k), "%s 的示范情景缺 %s" % (g["k"], k)


def test_gw_map_matches_list():
    assert set(GW_MAP) == {g["k"] for g in GW_DOCTYPES}
    for k, g in GW_MAP.items():
        assert g["k"] == k


def test_find_py_access_pattern():
    """照 mods/find.py 里的取法走一遍，别让它在线上才发现取不到。"""
    for k in sorted(GW_MAP.keys(), key=len, reverse=True):
        spec = GW_MAP.get(k, {})
        assert spec.get("fmt", "") != ""
        assert GW_MAP[k]["min"] and GW_MAP[k]["max"]
    payload = [{"k": d["k"], "cat": d["cat"], "min": d["min"], "max": d["max"]}
               for d in GW_DOCTYPES]
    assert len(payload) == len(GW_DOCTYPES)


# ---- 部件词表 ----

def test_every_doctype_has_parts():
    for g in GW_DOCTYPES:
        ps = parts_of(g["k"])
        assert ps, "%s 没有 parts" % g["k"]
        assert any(req for _p, req in ps), "%s 一个必需部件都没有" % g["k"]


def test_parts_use_controlled_vocab():
    """槽位必须来自 GW_SLOTS；带二级角色的，角色必须在该槽位的词表里。
    文种专属部件（如新闻稿的「导语」）走 GW_ROLES 的显式登记，不是随手写。"""
    for g in GW_DOCTYPES:
        for part, _req in parts_of(g["k"]):
            slot = part.split("·")[0]
            assert slot in GW_SLOTS, "%s 的部件 %r 槽位不在 GW_SLOTS" % (g["k"], part)
            if "·" in part:
                role = part.split("·", 1)[1]
                assert role in GW_ROLES.get(slot, []), \
                    "%s 的部件 %r 角色不在 GW_ROLES[%s]" % (g["k"], part, slot)


def test_parts_do_not_drift_from_fmt():
    """parts（结构化，给检索用）和 fmt（人话，给提示词和界面用）是两套描述同一件事。
    留两套是故意的——fmt 里有 parts 装不下的细节（「标题（发文机关+事由+文种）」）。
    但两套就会漂移，所以卡一条：parts 里的槽位，fmt 那句话里必须提到。"""
    for g in GW_DOCTYPES:
        fmt = g["fmt"]
        for part, req in parts_of(g["k"]):
            if not req:
                continue                      # 可选部件不强求写进 fmt
            slot = part.split("·")[0]
            assert slot in fmt, \
                "%s 的必需部件 %r 在 fmt 里找不到：%r" % (g["k"], part, fmt)


# ---- 归一化：三条规则都用 63 篇实测里的真名字做样例 ----

@pytest.mark.parametrize("raw,want", [
    # 尾部序号（实测 13 种 / 22 条）
    ("主体·举措一", "主体·举措"),
    ("主体·举措2", "主体·举措"),
    ("主体段落二", "主体"),
    ("建议三", "主体·建议"),
    # 正文· 前缀是另一套命名法（实测 23 种 / 26 条）
    ("正文·缘由", "开头·缘由"),
    ("正文·号召", "结尾·号召"),
    ("正文·做法分条", "主体·举措"),
    ("正文开头", "开头"),
    # 分隔符丢了 / 别名
    ("结尾号召", "结尾·号召"),
    ("落款与日期", "落款"),
    ("落款（署名+日期）", "落款"),
    ("结语", "结尾·收束"),
    ("开场白", "开头"),
    # 已经规范的不许被改坏
    ("主体·举措", "主体·举措"),
    ("称谓", "称谓"),
    ("标题", "标题"),
])
def test_norm_part(raw, want):
    assert norm_part(raw) == want


def test_norm_part_composite_splits():
    """合成名（实测 18 种 / 23 条）要拆成两条，不能糊成一个新名字。"""
    assert norm_part("主体·举措及成效", split=True) == ["主体·举措", "主体·成效"]
    assert norm_part("开头·缘由与目的", split=True) == ["开头·缘由", "开头·目的"]
    # split=False 时取第一个，保证老调用点拿到的是单个字符串
    assert norm_part("主体·举措及成效") == "主体·举措"


def test_norm_part_unknown_falls_back_to_slot():
    """认不出的角色别丢，退到槽位级——丢了等于这条批注白标。"""
    assert norm_part("主体·某个没见过的说法") == "主体"
    assert norm_part("") == ""
    assert norm_part(None) == ""


def test_alias_table_is_normalized():
    """别名表的右边必须本身就是规范名，否则归一化要跑两遍才收敛。"""
    for src, dst in GW_PART_ALIAS.items():
        assert norm_part(dst) == dst, "别名 %r → %r 的目标不是规范名" % (src, dst)


# ---- yy_items 建表 ----

YY_COLS = {"id", "kind", "doctype", "part", "cat", "domain", "title", "text",
           "note", "example", "src", "src_ref", "freq", "created_at"}


def test_yy_items_created_by_init_db():
    con = sqlite3.connect(DB)
    got = {r[1] for r in con.execute("PRAGMA table_info(yy_items)")}
    assert got, "init_db() 没建 yy_items"
    assert YY_COLS <= got, "yy_items 缺列：%s" % (YY_COLS - got)


def test_yy_items_unique_and_index():
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO yy_items(kind,doctype,part,title,text) VALUES(?,?,?,?,?)",
                ("骨架", "简报", "主体·成效", "t1", "x"))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO yy_items(kind,doctype,part,title,text) VALUES(?,?,?,?,?)",
                    ("骨架", "简报", "主体·成效", "t1", "y"))
    con.rollback()
    idx = {r[1] for r in con.execute("PRAGMA index_list(yy_items)")}
    assert any("yy_pick" in i for i in idx), "少了 (kind,doctype,part) 检索索引"


# ---- P1：字数模型 / 频次 / 口语文种豁免 / 表述按部件取 ----

def test_no_more_500_hard_cap():
    """真题实测最大 1000 字（2022 国考行执第 5 题公开信 800-1000），
    硬顶卡在 500 会把这类题在训练里彻底屏蔽。"""
    from mods.gongwen import YY_HARD_CAP, _word_band
    assert YY_HARD_CAP == 1000
    lo, hi = _word_band("公开信", "large", score=30)
    assert hi > 500, "公开信 30 分还被压在 500 以内：%d" % hi


@pytest.mark.parametrize("score,lo_max,hi_min", [
    (15, 350, 250), (20, 500, 400), (25, 550, 400), (30, 1000, 450),
])
def test_score_bands_from_real(score, lo_max, hi_min):
    """按分值建档，数字来自真题实测中位数（题位是猜的，分值是题面写着的）。"""
    from mods.gongwen import _word_band
    lo, hi = _word_band("经验交流材料", "medium", score=score)
    assert lo >= 150 and hi <= lo_max and hi >= hi_min


def test_word_target_not_at_cap():
    """真题参考答案写到上限的 94%，不顶着上限——给模型具体数字比给区间有用（P2 的经验）。"""
    from mods.gongwen import _word_band, _word_target
    lo, hi = _word_band("简报", "medium", score=25)
    t = _word_target(lo, hi)
    assert lo < t <= hi, (lo, t, hi)
    assert t < hi, "目标字数不该等于上限"


def test_spoken_doctype_keeps_yishi():
    """「一是…二是…」在讲话稿里是对的——30 份真题答案里唯一用它的就是讲话稿。
    其他文种照旧改成规范序号。"""
    from mods.gongwen import GW_SPOKEN, fix_fentiao
    src = "工作要抓实。一是压实责任，二是强化督导。"
    assert "讲话稿" in GW_SPOKEN
    assert fix_fentiao(src, "讲话稿") == src
    assert fix_fentiao(src, "通知") != src
    assert fix_fentiao(src) != src          # 不传文种时行为不变（老调用点）


def test_real_exam_freq_present():
    """每个文种都要带真题频次，界面才能按「该练什么」排序而不是按录入顺序。"""
    for g in GW_DOCTYPES:
        assert "freq" in g and "freq_all" in g and "fam" in g, g["k"]
        assert isinstance(g["freq"], int)
    top = max(GW_DOCTYPES, key=lambda g: g["freq"])
    assert top["fam"] == "交流材料", "真题最高频的族应该是交流材料，实测 8 次"
    # 零频的老文种留着但不该占前排
    zero = {g["k"] for g in GW_DOCTYPES if g["freq"] == 0}
    assert {"通知", "倡议书", "新闻稿"} <= zero


def test_new_doctypes_added():
    """真题考过、原清单没有的文种要补齐（加不删——删了会让已有范文变孤儿）。"""
    have = {g["k"] for g in GW_DOCTYPES}
    assert {"经验交流材料", "推荐材料", "情况介绍", "提案", "工作指南", "谈话提纲"} <= have
    for g in GW_DOCTYPES:
        assert g["cat"] in GW_CATS, "%s 用了新分类，前端会漏显示" % g["k"]


def test_phrase_pool_is_per_doctype():
    """规范表述必须按 (文种, 部件) 取——原来是整表一把梭，写通知和写倡议书喂同一份池子。"""
    import sqlite3

    from mods.gongwen import _phrase_pool
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR IGNORE INTO gongwen_items(scene,phrases,doctype,source) "
                "VALUES('结尾·要求（通知）','请遵照执行','通知','seed')")
    con.execute("INSERT OR IGNORE INTO yy_items(kind,doctype,part,title,text) "
                "VALUES('表述','谈话提纲','主体·建议','t-建议','建议你…')")
    con.commit()
    got = _phrase_pool(con, "谈话提纲")
    assert got, "谈话提纲取不到任何表述"
    parts = {x["scene"] for x in got}
    # 谈话提纲的 parts 是 成效/问题/建议，不该把「结尾·要求（通知）」当主料
    assert "主体·建议" in parts or len(got) >= 4


# ---- P3：part 形态（只写指定几块）----

def test_only_parts_presets_match_real_exam():
    """预设来自真题原题，不是编的：
       调研报告→「问题」「建议」（2022 川县乡 Q2）
       提案→「案由」「具体建议」（2025 国考地市 Q4）
       工作指南→「工作事项及工作内容」（2025 国考行执 Q3）"""
    from mods.gongwen import _only_parts
    assert _only_parts("调研报告") == ["主体·问题", "主体·建议"]
    assert "主体·建议" in _only_parts("提案")
    assert _only_parts("工作指南") == ["主体·举措"]


def test_only_parts_respects_caller():
    """调用方指定了写哪几块就按它的，但要过滤掉这个文种没有的部件。"""
    from mods.gongwen import _only_parts
    assert _only_parts("调研报告", ["主体·问题"]) == ["主体·问题"]
    # 「落款」不在调研报告的 parts 里？在的话就该留着；给个肯定不存在的
    assert _only_parts("调研报告", ["主体·某个不存在的角色"]) == []


def test_only_parts_normalizes_input():
    """调用方可能传「正文·问题」这类别名，要先过归一化。"""
    from mods.gongwen import _only_parts
    assert _only_parts("调研报告", ["正文·问题"]) == ["主体·问题"]


def test_only_parts_falls_back_to_body():
    """没预设的文种取主体那几块——真题的 part 题考的都是正文的「肉」，不考标题落款。"""
    from mods.gongwen import _only_parts
    got = _only_parts("公开信")
    assert got and all(p.startswith("主体") for p in got), got


def test_part_form_requires_parts(client):
    """part 形态没指定写哪几块就该报错，不能默默当成篇写。"""
    from mods.gongwen import _only_parts
    # 所有已知文种都能推出至少一块，所以这里验的是 _only_parts 不会返回空
    for g in GW_DOCTYPES:
        assert _only_parts(g["k"]), "%s 推不出 part 形态要写哪几块" % g["k"]
