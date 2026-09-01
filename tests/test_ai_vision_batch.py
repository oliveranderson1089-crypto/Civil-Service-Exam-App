"""带图问答：图多的时候要**全看完**，而不是悄悄只看前几张。

来由（2026-08-29）：用户往 AI 助手里传了 11 张题目截图，说「按顺序解释这些题」，
AI 只解释了前六张 —— 界面上没有任何地方说过后面几张被丢了。查下来是两道暗闸：
  · _req_atts 里写死 `raw[:6]`：第 7 张往后连请求都没进；
  · _vision_prompt 里写死 `paths[:3]`：真正进视觉模型的只有前 3 张，
    第 4~6 张靠后台 OCR 出来的文字碰运气。
现在附件放到 12 份，图片按 VISION_BATCH 分组、一组一组问完。
这组测试钉住的是「几张进去、几张出来」，不是提示词的措辞。
"""
import pytest

from mods import aisession


def _atts(n):
    return [{"name": "第%d张.jpg" % (i + 1), "text": "", "image": "img%d.jpg" % (i + 1)}
            for i in range(n)]


@pytest.fixture
def vision_on(monkeypatch):
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "ai_img_path", lambda name: ("/tmp/" + name) if name else "")


def test_十一张图一张都不能少(vision_on):
    jobs = aisession._vision_jobs(_atts(11), "按顺序解释这些题")
    assert [len(paths) for paths, _, _ in jobs] == [4, 4, 3]
    assert sum(len(paths) for paths, _, _ in jobs) == 11, "有图没进请求"
    assert [rng for _, _, rng in jobs] == [(1, 4), (5, 8), (9, 11)]


def test_分组时要告诉模型这是第几张(vision_on):
    jobs = aisession._vision_jobs(_atts(11), "按顺序解释这些题")
    # 不说清楚的话，三组答案接起来就是三份「第一张、第二张…」，对不上用户手里的图
    assert "第 5~8 张" in jobs[1][1]
    assert "11" in jobs[0][1], "该交代这一轮一共几张"


def test_图不多就别分组也别啰嗦(vision_on):
    jobs = aisession._vision_jobs(_atts(3), "这题怎么做")
    assert len(jobs) == 1 and len(jobs[0][0]) == 3
    assert "一共" not in jobs[0][1], "只有一组还讲「第几~几张」，是给模型添乱"


def test_每组只带自己那几张的转写(vision_on):
    atts = _atts(8)
    for i, a in enumerate(atts):
        a["text"] = "转写%d" % (i + 1)
    jobs = aisession._vision_jobs(atts, "看看")
    assert "转写1" in jobs[0][1] and "转写5" not in jobs[0][1]
    assert "转写5" in jobs[1][1] and "转写1" not in jobs[1][1]


def test_没配视觉或图没了就不走这条路(monkeypatch):
    monkeypatch.setattr(aisession, "vision_configured", lambda: True)
    monkeypatch.setattr(aisession, "ai_img_path", lambda name: "")
    assert aisession._vision_jobs(_atts(5), "看看") == []
    monkeypatch.setattr(aisession, "ai_img_path", lambda name: "/tmp/" + name)
    monkeypatch.setattr(aisession, "vision_configured", lambda: False)
    assert aisession._vision_jobs(_atts(5), "看看") == []


def test_附件条数上限是十二不是六():
    raw = [{"name": "f%d" % i, "text": "正文%d" % i} for i in range(20)]
    out = aisession._req_atts({"attachments": raw})
    assert len(out) == aisession.ATT_MAX == 12
    assert out[-1]["name"] == "f11", "取的该是前 12 份，顺序别乱"
