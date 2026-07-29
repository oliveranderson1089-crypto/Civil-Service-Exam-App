"""古诗复习卡的两道入库闸门（gen_gushi.py）。

「今日复习 · 古诗」只收同时满足两条的诗：
  1. 话题是常识判断真考的类型 —— topic 必须落在 gushi_meta.json 的 topics 白名单里；
  2. 篇中有能直接当申论素材的句子 —— line 必须是**这一首**的原文子串。
第 2 条是校验不是修辞：AI 报的「名句」很容易串篇（张冠李戴、两首拼一句），
而《清明》《登鹳雀楼》这类同名诗库里就有好几首，只按标题认篇必认错。
这两条一旦松掉，背下来的就是错卡——所以拿测试焊死。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import gen_gushi as gg  # noqa: E402


POEMS = [
    {"id": 1, "title": "清明", "author": "杜牧", "content": "清明时节雨纷纷，路上行人欲断魂。"},
    {"id": 2, "title": "清明", "author": "王禹偁", "content": "无花无酒过清明，兴味萧然似野僧。"},
    {"id": 3, "title": "石灰吟", "author": "于谦",
     "content": "千锤万凿出深山，烈火焚烧若等闲。\n(万凿 一作：万击)粉骨碎身浑不怕，要留清白在人间。"},
]
for _p in POEMS:
    _p["n"] = gg.norm(_p["content"])


def test_名句核不上原文的一律不收():
    p, err = gg.find_poem(POEMS, "落霞与孤鹜齐飞", title="清明", author="杜牧")
    assert p is None and "没有这句" in err, "凭空的名句被收进来了——背下来就是错的"


def test_同名诗按名句定篇不按标题():
    """光《清明》库里就有三首，只认标题必然认错人。"""
    p, err = gg.find_poem(POEMS, "无花无酒过清明", title="清明")
    assert p and p["id"] == 2, f"同名诗认错了篇：{p and p['id']}"


def test_标点与括注不影响比对():
    """原文里夹着「(万凿 一作：万击)」这类异文注，比对只留汉字才对得上。"""
    p, err = gg.find_poem(POEMS, "粉骨碎身浑不怕，要留清白在人间", title="石灰吟", author="于谦")
    assert p and p["id"] == 3, err


def test_话题不在常识常考白名单就不收():
    p, err = gg.check_one(POEMS, {"title": "清明", "line": "清明时节雨纷纷",
                                  "topic": "风花雪月", "theme": "家国情怀"})
    assert p is None and "常识常考白名单" in err


def test_申论主题不在白名单就不收():
    p, err = gg.check_one(POEMS, {"title": "清明", "line": "清明时节雨纷纷",
                                  "topic": "节气节令", "theme": "随便写写"})
    assert p is None and "白名单" in err


def test_两条都满足才放行():
    p, err = gg.check_one(POEMS, {"title": "清明", "author": "杜牧", "line": "清明时节雨纷纷",
                                  "topic": "节气节令", "theme": "文化传承"})
    assert p and p["id"] == 1, err


@pytest.mark.parametrize("it", gg.META["seed"], ids=lambda it: it["title"])
def test_种子池每条都带齐四样东西(it):
    """话题、申论主题、名句、常识考点——少一样这张卡就没法背。"""
    assert it["topic"] in gg.TOPICS, "话题不在常识常考白名单里"
    assert it["theme"] in gg.THEMES, "申论主题不在白名单里"
    assert len(gg.norm(it["line"])) >= 4, "名句太短，当不了申论素材"
    assert it["common"] and it["apply"], "常识考点和申论用法都得写"


def test_建表语句自己带着能跑(tmp_path):
    """脚本先于主应用建表（跟 crawl_news 那类一样），语法崩了会在半夜的定时任务里才发现。"""
    con = sqlite3.connect(tmp_path / "t.db")
    gg.ensure_table(con)
    gg.ensure_table(con)                     # 幂等：重跑不炸
    cols = {r[1] for r in con.execute("PRAGMA table_info(gushi_cards)")}
    assert {"classic_id", "line", "topic", "theme", "common", "apply", "freq"} <= cols
    assert gg.save_card(con, 1, "同一句", "节气节令", "文化传承", "考点", "用法", 100, "seed") == 1
    assert gg.save_card(con, 1, "同一句", "节气节令", "文化传承", "考点", "用法", 100, "seed") == 0, \
        "重跑脚本会插重复卡"
    con.close()
