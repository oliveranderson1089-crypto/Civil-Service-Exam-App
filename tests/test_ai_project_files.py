"""项目资料是**项目级**的：挂上去以后，这个项目下的每一个对话都读得到。

起因是这条抱怨：从项目设置里挂的资料，表现得像「传进了某一次对话」——
用户要的是「挂在项目上，项目下的对话随时调得动」。所以这里盯死三件事：
  · 同一个项目的**另一个**对话，也拿得到（不是只有当时那个对话）；
  · 别的项目 / 没项目的对话，拿不到（共享不等于泄漏到全局）；
  · 大资料注不进上下文时，**清单和读法必须还在**——不然模型会一口咬定
    「你这个项目里只挂了评分标准」，而剩下那几份就在库里躺着。
"""
import io
import os
import sqlite3

import pytest

import mods.agent  # noqa: F401  写工具在这里注册
from conftest import DB
from core import AI_PROJ_DIR
from mods import aisession
from mods.agent_tools import exec_tool


@pytest.fixture
def fake_ai(monkeypatch):
    """把模型换成一个只把 messages 留下来的桩：这些测试问的是「给模型看了什么」。"""
    seen = {}
    monkeypatch.setattr(aisession, "_ai_agentic_or_error",
                        lambda messages, db, **kw: (seen.update(msgs=messages),
                                                    ("好的。", [], [], None))[1])
    return seen


@pytest.fixture
def proj(auth_client):
    pid = auth_client.post("/api/aichat/projects",
                           json={"name": "社区工作者考试", "instructions": "应付笔试"}).get_json()["id"]
    return auth_client, pid


def blob_dir():
    """原件落在 <AI_PROJ_DIR>/<user_id>/ 下。用户 id 从库里查 —— 写死 1 的话，
    哪天 conftest 换个建号顺序，这几条断言会变成永远为真。"""
    con = sqlite3.connect(DB, timeout=10)
    u = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.close()
    return os.path.join(AI_PROJ_DIR, str(u))


def ls_blobs():
    """盘上现有的原件。测试之间共用同一个用户目录（同一个库跑一整轮），
    所以断言一律用**前后之差**，别断言「目录是空的」。"""
    d = blob_dir()
    return set(os.listdir(d)) if os.path.isdir(d) else set()


def upload(c, pid, name, body, filename="讲义.txt"):
    return c.post("/api/aichat/projects/%d/files/upload" % pid,
                  data={"name": name, "file": (io.BytesIO(body.encode("utf-8")), filename)},
                  content_type="multipart/form-data")


def sys_prompt_of(c, pid, fake_ai, content="讲讲"):
    cid = c.post("/api/aichat/chats", json={"project_id": pid}).get_json()["id"]
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": content})
    return fake_ai["msgs"][0]["content"]


# ---------------- 上传 ----------------

def test_传文件就挂上了并且抽出了正文(proj):
    c, pid = proj
    d = upload(c, pid, "评分标准", "第一档 18-20 分：观点明确、论证充分。").get_json()
    assert d["ok"] and d["chars"] > 0
    files = c.get("/api/aichat/projects/%d/files" % pid).get_json()["files"]
    assert [f["name"] for f in files] == ["评分标准"]
    assert files[0]["orig_name"] == "讲义.txt"


def test_不给名字就用文件名(proj):
    c, pid = proj
    upload(c, pid, "", "正文", filename="社区工作者真题.txt")
    assert c.get("/api/aichat/projects/%d/files" % pid).get_json()["files"][0]["name"] == "社区工作者真题"


def test_一个字都抽不出来的文件不留在盘上(proj):
    c, pid = proj
    before = ls_blobs()
    r = upload(c, pid, "空的", "", filename="空.txt")
    assert r.status_code == 400
    assert not c.get("/api/aichat/projects/%d/files" % pid).get_json()["files"]
    assert ls_blobs() == before, "抽不出字的原件既没用也删不掉，不该留着"


def test_没登录挂不上(proj, flask_app):
    c, pid = proj
    other = flask_app.test_client()                     # 没登录
    assert upload(other, pid, "偷挂", "内容").status_code in (401, 302, 404)


# ---------------- 共享：这就是用户要的那一条 ----------------

def test_同一项目的每个对话都拿得到(proj, fake_ai):
    c, pid = proj
    upload(c, pid, "评分标准", "第一档 18-20 分：观点明确。")
    for _ in range(2):                       # 两个**不同**的对话，各问一次
        sp = sys_prompt_of(c, pid, fake_ai)
        assert "第一档 18-20 分" in sp, "换个对话就读不到了，那还是「传进了某一次对话」"


def test_传完之前就建好的老对话也拿得到(proj, fake_ai):
    """资料是挂在项目上的，不是挂在某次上传的那一刻 —— 先建的对话也要能用。"""
    c, pid = proj
    cid = c.post("/api/aichat/chats", json={"project_id": pid}).get_json()["id"]
    upload(c, pid, "评分标准", "第一档 18-20 分：观点明确。")
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "批一下"})
    assert "第一档 18-20 分" in fake_ai["msgs"][0]["content"]


def test_不属于这个项目的对话读不到(proj, fake_ai):
    c, pid = proj
    upload(c, pid, "评分标准", "第一档 18-20 分：观点明确。")
    cid = c.post("/api/aichat/chats", json={}).get_json()["id"]      # 没挂项目
    c.post("/api/aichat/chats/%d/send" % cid, json={"content": "随便聊"})
    assert "第一档 18-20 分" not in fake_ai["msgs"][0]["content"]

    pid2 = c.post("/api/aichat/projects", json={"name": "行测"}).get_json()["id"]
    assert "第一档 18-20 分" not in sys_prompt_of(c, pid2, fake_ai)


def test_注不下的资料也要留下清单和读法(proj, fake_ai):
    """预算给不下时，以前是直接截掉后面几份 —— 模型于是当它们不存在。"""
    c, pid = proj
    upload(c, pid, "大讲义", "社区工作者常识。" * 3000)     # 远超 PROJ_INJECT
    upload(c, pid, "评分标准", "第一档 18-20 分。")
    sp = sys_prompt_of(c, pid, fake_ai)
    assert "大讲义" in sp and "评分标准" in sp, "清单必须列全，哪怕正文没给"
    assert "read_project_file" in sp, "没告诉模型怎么读，剩下的内容等于不存在"
    assert "只是前" in sp, "截断不留痕，模型就会拿半份当整份下结论"


# ---------------- 工具：随时调得动 ----------------

@pytest.fixture
def ctx(auth_client):
    """带登录态的请求上下文 + db，直接调工具用。"""
    import app as appmod
    from core import get_db
    con = sqlite3.connect(DB, timeout=10)
    uid = con.execute("SELECT id FROM users WHERE username='tester'").fetchone()[0]
    con.close()
    with appmod.app.test_request_context():
        from flask import session
        session["user_id"] = uid
        yield get_db()


@pytest.fixture
def hung(proj, ctx):
    c, pid = proj
    upload(c, pid, "大讲义", "开头。" + "社区治理的基本方法。" * 2000 + "末尾密码是芝麻开门。")
    fid = ctx.execute("SELECT id FROM ai_project_files WHERE project_id=?", (pid,)).fetchone()[0]
    return c, pid, fid, ctx


def test_按段读并且告诉模型还有几段(hung):
    _, _, fid, db = hung
    msg, _ = exec_tool("read_project_file", {"id": fid}, db)
    assert "开头。" in msg and "第 1/" in msg and "part=2" in msg


def test_关键词能直接定位到后面去(hung):
    """整段读要翻很多次；「按标准第几档」这种问题得能一步找到。"""
    _, _, fid, db = hung
    msg, _ = exec_tool("read_project_file", {"id": fid, "keyword": "芝麻开门"}, db)
    assert "芝麻开门" in msg


def test_搜不到就说全文都没有别留活口(hung):
    _, _, fid, db = hung
    msg, _ = exec_tool("read_project_file", {"id": fid, "keyword": "量子纠缠"}, db)
    assert "没有出现" in msg and "全文" in msg


def test_列表工具只列当前项目(hung):
    from flask import g
    c, pid, _, db = hung
    pid2 = c.post("/api/aichat/projects", json={"name": "行测"}).get_json()["id"]
    upload(c, pid2, "行测笔记", "图形推理规律。")
    g.ai_project_id = pid
    msg, _ = exec_tool("list_project_files", {}, db)
    assert "大讲义" in msg and "行测笔记" not in msg


def test_读不到别的项目的资料(hung):
    from flask import g
    c, pid, fid, db = hung
    pid2 = c.post("/api/aichat/projects", json={"name": "行测"}).get_json()["id"]
    g.ai_project_id = pid2
    msg, _ = exec_tool("read_project_file", {"id": fid}, db)
    assert "没有" in msg, "A 项目的对话读到了 B 项目的资料，回答会驴唇不对马嘴"


def test_读别人的资料读不到(hung):
    """跨账号那条线，不能只靠「同一个项目」挡（项目上下文不在时更要靠它）。"""
    import app as appmod
    from core import get_db
    _, _, fid, _ = hung
    con = sqlite3.connect(DB, timeout=10)
    con.execute("INSERT INTO users(username,password_hash,role) VALUES('路人','x','user')")
    oid = con.execute("SELECT id FROM users WHERE username='路人'").fetchone()[0]
    con.commit()
    con.close()
    with appmod.app.test_request_context():
        from flask import session
        session["user_id"] = oid
        msg, _ = exec_tool("read_project_file", {"id": fid}, get_db())
    assert "没有" in msg


# ---------------- 删除 ----------------

def test_删资料连原件一起删(proj):
    c, pid = proj
    before = ls_blobs()
    fid = upload(c, pid, "评分标准", "第一档。").get_json()["id"]
    assert ls_blobs() - before, "上传都没落原件，按页续读就无从谈起"
    c.delete("/api/aichat/projects/%d/files/%d" % (pid, fid))
    assert not c.get("/api/aichat/projects/%d/files" % pid).get_json()["files"]
    assert ls_blobs() == before, "库里删了、盘上还在，就是慢性漏盘"


def test_删项目连资料一起删(proj):
    c, pid = proj
    upload(c, pid, "评分标准", "第一档。")
    c.delete("/api/aichat/projects/%d" % pid)
    con = sqlite3.connect(DB, timeout=10)
    left = con.execute("SELECT COUNT(*) FROM ai_project_files WHERE project_id=?", (pid,)).fetchone()[0]
    con.close()
    assert left == 0, "项目没了，这些资料再没有任何入口能看到，留着就是孤儿"


def test_按页识别只对PDF原件有意义(hung):
    """粘进来的文本、txt 没有"页"这回事 —— 别让模型在这上面反复试。"""
    _, _, fid, db = hung
    msg, _ = exec_tool("read_project_file", {"id": fid, "page": 3}, db)
    assert "不是 PDF" in msg and "part" in msg


def test_没有第几页就直说(hung):
    _, _, fid, db = hung
    db.execute("UPDATE ai_project_files SET ext='.pdf', pages=10, stored_name='x.pdf' WHERE id=?",
               (fid,))
    db.commit()
    msg, _ = exec_tool("read_project_file", {"id": fid, "page": 99}, db)
    assert "一共 10 页" in msg


def test_原件丢了也别装死(hung):
    """原件被清掉时要说清「只能读已入库的正文」，而不是一句读不出来。"""
    _, _, fid, db = hung
    db.execute("UPDATE ai_project_files SET ext='.pdf', stored_name='没了.pdf' WHERE id=?", (fid,))
    db.commit()
    msg, _ = exec_tool("read_project_file", {"id": fid, "page": 2}, db)
    assert "不在磁盘上" in msg and "part" in msg
