"""跨模块共用的地基：路径、日志、数据库连接、当前用户。

拆模块拆出来的。蓝图不能 import app（app 要 import 蓝图来注册，会绕成一个圈），
所以两边都要用的东西放这儿——依赖只朝一个方向走：app.py → mods/* → core.py。

这里只放真正共用的，别当杂物间：业务逻辑归各自的模块。
"""
import logging
import os
import sqlite3

from flask import g, session

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
STATIC = os.path.join(BASE, "static")
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

# ---------------------------------------------------------------- 日志
# 跑在 systemd 下，stderr 直接进 journald：journalctl --user -u gongkao -f
# GONGKAO_LOG=DEBUG 可打开「可安全忽略」那一档（临时文件没删掉、可选依赖缺失之类）。
logging.basicConfig(
    level=os.environ.get("GONGKAO_LOG", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%m-%d %H:%M:%S",
)
log = logging.getLogger("gongkao")


# ---------------------------------------------------------------- 数据库
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    return db


def close_db(exc):
    """请求结束关连接。没 commit 的事务会在 close 时回滚——批注整页替换的原子性就靠它。
    app.py 里用 app.teardown_appcontext(close_db) 挂上。"""
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------- 当前用户
def current_user():
    u = session.get("user_id")
    if not u:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (u,)).fetchone()


def uid():
    return session.get("user_id")


def uname(db, u):
    """查用户名。查不到说明是孤儿记录（用户已删而引用还在），给个带 id 的占位好排查。

    原先 app.py 里同名的 _uname 定义了三遍（组队/好友/聊天各一份，兜底文案分别是
    "?"、"用户N"、"好友"）——后定义的覆盖前面的，实际全都在用最后那份，另两份是死代码。
    """
    r = db.execute("SELECT username FROM users WHERE id=?", (u,)).fetchone()
    return (r["username"] if r else "") or ("用户%s" % u)
