"""每日 AI 学习问答归纳（summarize_ai.py）的冒烟测试。

这是踩坑踩出来的：summarize_ai.py 是 systemd 定时器直接拉起的**独立脚本**，
没人 import 它，所以 AI 工具重构（c3fa17c）把 DB / _ai_call_or_error / _user_dir
从 app.py 挪进 core / mods.ai / mods.files 后，它还在用 app.DB 老路径——
定时任务连崩两晚（7-17、7-18），资料库里一份归纳都没进，全程没有任何测试拦得住。

关键教训：光「能 import」防不住。原来的 `A.DB` 是藏在 main() 里的运行时属性访问，
import 阶段根本不执行。所以这里真跑一遍归纳流程（桩掉 AI 调用、走测试库），
既拦 import 断链，也拦这种「函数体里才炸」的断链。
"""
import sqlite3

import summarize_ai
from conftest import DB

TEST_DAY = "2099-01-02"          # 用远期日期，绝不撞真实数据 / 别的用例
FAKE_NOTE = "## 今天问了什么\n\n言语理解的语境分析。\n\n## 知识要点\n\n- 对策优先。\n"


def _seed_convo(user_id):
    """给某用户造一段当天、够长（>MIN_CHARS）的问答。"""
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO ai_chats(user_id,title,updated_at) VALUES(?,?,?)",
               (user_id, "冒烟会话", TEST_DAY + " 12:00:00"))
    cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)",
               (cid, "user", "语境分析题怎么做？" * 10))
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)",
               (cid, "assistant", "先定位横线所在句，再找呼应的提示信息。" * 10))
    db.commit()
    db.close()
    return cid


def _uid(username):
    db = sqlite3.connect(DB)
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    return row[0]


def _cleanup(user_id, chat_id):
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM ai_msgs WHERE chat_id=?", (chat_id,))
    db.execute("DELETE FROM ai_chats WHERE id=?", (chat_id,))
    db.execute("DELETE FROM materials WHERE user_id=? AND board=? AND title=?",
               (user_id, summarize_ai.CATEGORY, "AI 学习问答 · " + TEST_DAY))
    db.commit()
    db.close()


def test_跨模块依赖没断链():
    """DB / _ai_call_or_error / _user_dir 搬家后，脚本 import 得到的必须是真东西。

    这三个符号任一被重命名 / 再挪位置，import summarize_ai 就会在这里失败——
    正是 7-17 那次没人拦住的断链。
    """
    assert isinstance(summarize_ai.DB, str) and summarize_ai.DB.endswith(".db")
    assert callable(summarize_ai._ai_call_or_error)
    assert callable(summarize_ai._user_dir)


def test_当天问答能归纳进资料库(auth_client, account, monkeypatch):
    """端到端跑一遍 main()：造对话 → 桩 AI → 落一份 .md 进 materials。

    走 main() 而不是直接调子函数，是因为原 bug（A.DB）恰恰在 main() 里，
    只有真跑到那一行才暴露。
    """
    # 借 auth_client 保证库里有用户；取其 id 作归纳对象
    user_id = _uid(account["username"])
    chat_id = _seed_convo(user_id)
    # 桩掉真实 AI 调用，别打外网 / 花额度
    monkeypatch.setattr(summarize_ai, "_ai_call_or_error",
                        lambda *a, **k: (FAKE_NOTE, None))
    monkeypatch.setattr("sys.argv", ["summarize_ai.py", "--date", TEST_DAY])
    try:
        summarize_ai.main()

        db = sqlite3.connect(DB)
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM materials WHERE user_id=? AND board=? AND title=?",
            (user_id, summarize_ai.CATEGORY, "AI 学习问答 · " + TEST_DAY)).fetchone()
        db.close()
        assert row is not None, "归纳没写进 materials——归纳流程炸在半路"
        assert row["ext"] == ".md" and row["size"] > 0
        # 文件真落盘了、内容含笔记正文
        import os
        p = os.path.join(summarize_ai._user_dir(user_id), row["stored_name"])
        assert os.path.exists(p)
        assert "知识要点" in open(p, encoding="utf-8").read()
    finally:
        _cleanup(user_id, chat_id)


def test_对话太少不生成空笔记(auth_client, account, monkeypatch):
    """当天没什么学习内容就别造空笔记——MIN_CHARS 闸门要生效。"""
    user_id = _uid(account["username"])
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO ai_chats(user_id,title,updated_at) VALUES(?,?,?)",
               (user_id, "太短", TEST_DAY + " 12:00:00"))
    cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO ai_msgs(chat_id,role,content) VALUES(?,?,?)",
               (cid, "user", "在？"))          # 远不足 MIN_CHARS
    db.commit()
    db.close()
    called = []
    monkeypatch.setattr(summarize_ai, "_ai_call_or_error",
                        lambda *a, **k: called.append(1) or (FAKE_NOTE, None))
    monkeypatch.setattr("sys.argv", ["summarize_ai.py", "--date", TEST_DAY])
    try:
        summarize_ai.main()
        assert not called, "对话不足 MIN_CHARS 却仍调了 AI"
    finally:
        _cleanup(user_id, cid)
