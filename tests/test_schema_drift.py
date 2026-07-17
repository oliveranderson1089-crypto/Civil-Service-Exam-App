"""守住 schema 漂移。

建表语句散在 app.py、crawl_news.py、gen_changshi.py、build_classics.py、
import_teacher.py 里，同一张表被定义两遍。漂移已经真崩过：
changkao_items.freq 只由 import_teacher.py 建、news_items.board 只由
crawl_news.py 建，而 app.py 照样查它们——没跑过那两个脚本的新库直接 500。

不去强行合并（脚本自包含、不依赖 Flask 是有价值的），改用这几条盯着：
辅助脚本一旦加了 app.py 不知道的列，这里就红，提醒你同步进 init_db()。
"""
import re
import shutil
import sqlite3
import sys

import pytest

from conftest import BASE, DB, appmod

sys.path.insert(0, str(BASE))


def _fresh(tmp_path):
    """拷一份 conftest 已建好的空库——它就是 app.py init_db() 的产物。"""
    p = tmp_path / "fresh.db"
    shutil.copy(DB, p)
    return sqlite3.connect(p)


def _cols(con, table):
    return {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}


def _ddl_cols(src_file, table):
    """从源码里抠出 CREATE TABLE 并真建一次——比读正则可靠。括号配对，不依赖分号。"""
    s = open(BASE / src_file, encoding="utf-8").read()
    m = re.search(r"CREATE TABLE IF NOT EXISTS %s\s*\(" % table, s)
    if not m:
        return None
    depth = 0
    for j in range(m.end() - 1, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                mem = sqlite3.connect(":memory:")
                mem.executescript(s[m.start():j + 1])
                return _cols(mem, table)
    return None


class TestCrawlNews:
    def test_不会加app不知道的列(self, tmp_path):
        """news_items.board 就是这么漏的：crawl_news 建了，app.py 查了，init_db 没建。"""
        import crawl_news
        con = _fresh(tmp_path)
        before = _cols(con, "news_items")
        crawl_news.ensure_schema(con)
        after = _cols(con, "news_items")
        assert after == before, (
            "crawl_news.ensure_schema 给 news_items 补了 app.py 不知道的列：%s\n"
            "请把它同步进 app.py 的 init_db()，否则没跑过爬虫的新库上 /api/news 会 500"
            % sorted(after - before))


@pytest.mark.parametrize("src,table", [
    ("crawl_news.py", "news_items"),
    ("crawl_news.py", "gaikuo_items"),
    ("crawl_news.py", "xiyu_items"),
    ("gen_changshi.py", "changshi_items"),
    ("build_classics.py", "classics"),
])
def test_脚本建表不超出app建表(src, table, tmp_path):
    """同一张表两处定义，app.py 那份必须是超集（少的列由 init_db 的 ALTER 补上）。"""
    script_cols = _ddl_cols(src, table)
    assert script_cols, f"{src} 里没找到 {table} 的建表语句"
    app_cols = _cols(_fresh(tmp_path), table)
    missing = script_cols - app_cols
    assert not missing, (
        f"{src} 建的 {table} 有 app.py 不知道的列：{sorted(missing)}\n"
        f"谁先跑决定表结构——请同步进 app.py 的 init_db()")
