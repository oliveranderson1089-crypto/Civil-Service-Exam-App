"""备考规划：两条线共用一套路线图代码，别再让「只有一条线有的字段」把接口打 500。

现场是社区那条线一点「让规划助手排今天的计划」就「请求失败」，服务端
`KeyError: 'shenlun'` —— _roadmap_prompt 直接取了 p["shenlun"]，而社区那份路线图
（这门考试不考申论）压根没有这个键。

这里钉住三件事：
  1. 社区线能把硬约束拼出来、接口不 500；
  2. 拼出来的是这门考试的东西 —— 不出现「行测定额」，link 候选给的是社区的去处；
  3. 公考那条线一个字都没被带跑偏。
"""
import json

import pytest

from mods import plan as planmod


@pytest.fixture
def stub_ai(monkeypatch):
    """把模型换成回声桩：真跑 /api/plan/generate，顺手把喂进去的 prompt 抓出来。"""
    seen = {}

    def fake(msgs, **kw):
        seen["prompt"] = msgs[-1]["content"]
        return json.dumps({"summary": "先清错题",
                           "items": [{"title": "社会工作单选 20 道", "module": "社会工作",
                                      "minutes": 30, "reason": "错题最多", "link": "sqdrill"}]},
                          ensure_ascii=False), None

    monkeypatch.setattr("mods.plan._ai_call_or_error", fake)
    return seen


def _open_roadmap(c, ln, days=None):
    assert c.post("/api/me/line", json={"line": ln}).status_code == 200
    r = c.post("/api/plan/profile", json={"exam": "社区专职工作者",
                                          "exam_date": "2026-09-12", "minutes": 300})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    body = {"start_date": "2026-08-19"}
    if days:
        body["days"] = days
    r = c.post("/api/plan/roadmap", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["roadmap"]


def test_shequ_roadmap_prompt_without_shenlun(auth_client):
    """社区线的阶段里没有 shenlun 字段 —— 硬约束照样要拼得出来。"""
    rm = _open_roadmap(auth_client, "shequ")
    assert rm["phase"], "起始日那天应当落在某个阶段里"
    assert "shenlun" not in rm["phase"], "前提变了：社区线现在有申论字段，这个测试要重写"
    txt = planmod._roadmap_prompt(rm)          # 以前这一行就是 KeyError 现场
    assert "· 申论：" not in txt, "社区这门考试不考申论"
    assert "行测定额" not in txt, "社区这门考试不考行测，定额别按行测叫"
    assert "sqdrill" in txt and "sqsub" in txt, "得告诉 AI 社区线的题该去哪儿做"


def test_gongkao_roadmap_prompt_unchanged(auth_client):
    """公考那条线的输出不该被这次改动带跑偏。"""
    rm = _open_roadmap(auth_client, "gongkao", days=40)
    txt = planmod._roadmap_prompt(rm)
    assert "· 申论：" in txt and "今日行测定额" in txt
    assert "sqdrill" not in txt


def test_shequ_plan_generate_ok(auth_client, stub_ai):
    """整条链路：社区线点「排今天的计划」→ 200，不是 500。"""
    _open_roadmap(auth_client, "shequ")
    r = auth_client.post("/api/plan/generate", json={})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json()["items"][0]["link"] == "sqdrill", \
        "sqdrill 不在 PLAN_LINKS 里的话 link 会被那道校验清空，任务就点不进去"
    pr = stub_ai["prompt"]
    assert "备考方向" in pr and "不考行测" in pr
    assert "图形推理" not in pr, "例子还是行测的，AI 会照着排考不到的东西"


def test_gongkao_plan_generate_ok(auth_client, stub_ai):
    _open_roadmap(auth_client, "gongkao", days=40)
    assert auth_client.post("/api/plan/generate", json={}).status_code == 200
    pr = stub_ai["prompt"]
    assert "行测定额" in pr and "sqdrill" not in pr


def test_roadmap_links_are_reachable():
    """路线图 fixed 里写的 link 都得在白名单里，否则 AI 抄了也会被清掉。"""
    for plan in (planmod.ROADMAP_SQ, planmod.ROADMAP_40):
        for x in plan["fixed"]:
            assert x["link"] in planmod.PLAN_LINKS, x
