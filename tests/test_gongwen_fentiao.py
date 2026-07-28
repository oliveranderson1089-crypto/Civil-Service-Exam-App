"""应用文分条：一律用「一、二、」，不许出现「一是…二是…」。

提示词里写死这条不够——这套说法在模型的公文语料里太扎实，实测还是往外冒。所以
出稿后过一道 fix_fentiao()。这个函数动的是**已经存下去的正文**，改坏了没法回滚，
所以两头都要拦：该改的改到，不该动的一个字不动。

还有一条隐蔽的：批注（segs）的 text 是从正文逐字复制的，正文改了批注没改，
「必须出现在正文里」那道闸会把整篇批注静默丢光——页面上就是「范文有、批注没了」。
"""
import json
import sqlite3

import pytest

import schema
from conftest import DB
from mods.gongwen import _gen_yingyong, fix_fentiao


@pytest.mark.parametrize("src, want", [
    # 成串的分条：序号换掉，项与项之间的逗号/分号升成句号
    ("现提出如下意见：一是加强组织领导，二是细化任务分工，三是强化督导考核。",
     "现提出如下意见：一、加强组织领导。二、细化任务分工。三、强化督导考核。"),
    ("一是加强领导，成立专班；二是细化分工，明确责任。",
     "一、加强领导，成立专班。二、细化分工，明确责任。"),
    # 换行分条：换行本身就是断句，不要再补句号
    ("主要做法：\n一是健全机制。\n二是压实责任。",
     "主要做法：\n一、健全机制。\n二、压实责任。"),
])
def test_改成规范序号(src, want):
    assert fix_fentiao(src) == want


@pytest.mark.parametrize("src", [
    # 只有一条，不是分条句式
    "存在问题的原因一是资金不足。",
    # 「任务一」+「是」——「一是」根本不在分条位置上，只改后半句会得到
    # 「任务一是重点。二、难点」这种不伦不类的东西
    "任务一是重点、二是难点",
    # 本来就是规范序号
    "一、加强组织领导。二、细化任务分工。",
    "",
])
def test_不该动的不动(src):
    assert fix_fentiao(src) == src


def test_正文改了批注跟着改_否则批注会被静默丢光(monkeypatch):
    """走一遍真的 _gen_yingyong：桩掉 AI，只看它怎么处理返回的正文和批注。"""
    reply = json.dumps({
        "title": "关于加强垃圾分类工作的通知",
        "content": "关于加强垃圾分类工作的通知\n\n各县（区）人民政府：\n"
                   "为深入贯彻绿色发展理念，现将有关事项通知如下："
                   "一是健全联防联控机制，压实属地管理责任；二是细化任务分工，明确时间节点。\n"
                   "××市××局\n2025年4月1日",
        "segs": [{"part": "主体·举措",
                  "text": "一是健全联防联控机制，压实属地管理责任；二是细化任务分工，明确时间节点。",
                  "why": "分条作答，每条先亮做法再讲落地"}],
        "note": "格式最容易丢分",
    }, ensure_ascii=False)
    monkeypatch.setattr("mods.gongwen._ai_call_or_error", lambda *a, **k: (reply, None))

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    eid, err = _gen_yingyong(db, {"doctype": "通知", "form": "full"})
    assert err is None, err
    row = db.execute("SELECT content, outline FROM daily_essays WHERE id=?", (eid,)).fetchone()
    db.close()

    assert "一是" not in row["content"] and "一、健全联防联控机制" in row["content"]
    segs = json.loads(row["outline"])
    assert segs, "批注被丢光了：正文改了、segs 没跟着改，就会撞上「必须出现在正文里」那道闸"
    assert "一是" not in segs[0]["text"]
    # 批注要能在正文里定位（前端靠这个跳转），逐字对得上才算数
    flat = row["content"].replace("\n", "")
    assert segs[0]["text"].replace("\n", "") in flat


def test_老库里那条分条领起要被改掉():
    """gongwen_items 整张表是喂给 AI 当零件用的。种子只在空库时写，老库得靠迁移。

    不迁的话，提示词里再怎么说「用一、二、」，例句「一是加强组织领导…」还会把它带回去。
    """
    con = sqlite3.connect(DB)
    con.execute("UPDATE gongwen_items SET phrases='一是…二是…三是…、其一…其二…', "
                "example='一是加强组织领导，二是细化任务分工。' "
                "WHERE scene='主体·分条领起' AND source='seed'")
    con.commit()
    con.close()

    schema.init_db()

    con = sqlite3.connect(DB)
    r = con.execute("SELECT phrases, example FROM gongwen_items "
                    "WHERE scene='主体·分条领起' AND source='seed'").fetchone()
    con.close()
    assert r, "种子里的「主体·分条领起」不见了"
    assert not r[0].startswith("一是") and "一是" not in r[1]
