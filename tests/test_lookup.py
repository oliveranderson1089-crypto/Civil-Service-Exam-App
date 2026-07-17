"""词典查询：全新库上也不能崩。

ref_idiom / ref_ci 的数据由 build_db.py（手工跑的构建脚本）从 chinese-xinhua
灌进来，可 core.lookup() 是无条件查它们的——表要是不存在，一查成语就
no such table 直接 500。这和 changkao_items.freq、news_items.board 是同一个
病根：app.py 依赖的 schema 却指望别的脚本去建。

这里盯的是「没跑过 build_db.py 的新库上，查词典要优雅降级而不是崩」。
"""
import sqlite3

import core
from conftest import DB, appmod


class TestRefTables:
    def test_空库也建得出两张词典表(self):
        got = {r[0] for r in sqlite3.connect(DB).execute(
            "select name from sqlite_master where type='table'")}
        for t in ("ref_idiom", "ref_ci"):
            assert t in got, f"{t} 没建——没跑过 build_db.py 的新库上 lookup() 会崩"

    def test_没有词典数据时lookup不崩只是查不到(self, flask_app):
        """测试库里这两张表是空的（数据要 build_db.py 才有），正好是新部署的样子。"""
        with flask_app.app_context():
            r = core.lookup("高瞻远瞩")
        assert r["found"] is False
        assert r["word"] == "高瞻远瞩"
        assert r["pinyin"], "查不到释义也该给出拼音"

    def test_lookup对空输入不崩(self, flask_app):
        with flask_app.app_context():
            assert core.lookup("")["found"] is False
            assert core.lookup(None)["found"] is False

    def test_有数据时查得到(self, flask_app):
        """灌一条进去，确认 lookup 真的会读这张表（不是永远返回 found=False）。"""
        con = sqlite3.connect(DB)
        con.execute("INSERT OR REPLACE INTO ref_idiom(word,pinyin,explanation,derivation,example) "
                    "VALUES('测试成语','cè shì','测试释义','出处','例句')")
        con.commit()
        con.close()
        try:
            with flask_app.app_context():
                r = core.lookup("测试成语")
            assert r["found"] is True
            assert r["explanation"] == "测试释义"
            assert r["category"] == "成语"
        finally:
            con = sqlite3.connect(DB)
            con.execute("DELETE FROM ref_idiom WHERE word='测试成语'")
            con.commit()
            con.close()

    def test_四字以上查不到的按词组归类(self, flask_app):
        with flask_app.app_context():
            assert core.lookup("生理功能测试")["category"] == "词组"
