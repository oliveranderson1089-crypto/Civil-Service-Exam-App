"""跨模块共用的地基：路径、日志、数据库连接、当前用户。

拆模块拆出来的。蓝图不能 import app（app 要 import 蓝图来注册，会绕成一个圈），
所以两边都要用的东西放这儿——依赖只朝一个方向走：app.py → mods/* → core.py。

这里只放真正共用的，别当杂物间：业务逻辑归各自的模块。
"""
import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import g, session
from pypinyin import Style
from pypinyin import pinyin as _pinyin

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
STATIC = os.path.join(BASE, "static")
UPLOADS = os.environ.get("GONGKAO_UPLOADS", os.path.join(BASE, "uploads"))
CONFIG = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))

# ---------------------------------------------------------------- 板块结构
SECTIONS = [
    {"key": "xingce", "name": "行测", "icon": "测", "desc": "行政职业能力测验",
     "boards": ["常识判断", "资料分析", "判断推理", "数量关系", "政治理论", "言语理解与表达"]},
    {"key": "shenlun", "name": "申论", "icon": "申", "desc": "申论写作",
     "boards": ["应用文", "议论文"]},
]
ALL_BOARDS = {b for s in SECTIONS for b in s["boards"]}
IDIOM_BOARD = "言语理解与表达"  # 带成语/词语工具的板块


# ---------------------------------------------------------------- 日志
# 跑在 systemd 下，stderr 直接进 journald：journalctl --user -u gongkao -f
# GONGKAO_LOG=DEBUG 可打开「可安全忽略」那一档（临时文件没删掉、可选依赖缺失之类）。
logging.basicConfig(
    level=os.environ.get("GONGKAO_LOG", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%m-%d %H:%M:%S",
)
log = logging.getLogger("gongkao")


# ---------------------------------------------------------------- 配置（密钥 + AI 设置）
def _write_cfg(cfg):
    """原子写：先落同目录临时文件并 fsync，再 rename 顶替。

    直接覆写的话，写到一半断电就留下半个 JSON——下次启动 secret_key 读不出来，
    全员登出、配置被重置。rename 在同一文件系统上是原子的：要么旧的，要么新的。
    """
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CONFIG)


def load_secret():
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            # 文件在却读不出来（损坏/权限），绝不能当成「还没有配置」往下走：那样会另生一把
            # secret_key 把所有人登出，随后 _save_cfg() 覆盖掉它，ai_key/邀请码一起没。
            raise SystemExit("配置 %s 读不出来：%s\n请先修好它、或备份后移走再启动——"
                             "服务不会拿空配置顶替。" % (CONFIG, e))
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        try:
            _write_cfg(cfg)
        except Exception as e:
            raise SystemExit("secret_key 写不进 %s：%s\n带临时密钥跑的话每次重启都会把所有人"
                             "登出，不如现在就停下来修。" % (CONFIG, e))
    return cfg


CFG = load_secret()


def _save_cfg():
    """存不下就往上抛，让接口报 500。

    别在这儿吞：调用方都是先改内存 CFG 再存盘、然后无条件回 ok:True——
    吞掉的话页面显示「已保存」，本进程也确实生效，重启才发现改动没了。
    """
    _write_cfg(CFG)


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


def bg_new(db, kind, title, total=0):
    """开一条后台任务记录，返回 id。前端靠 bg_tasks 轮询进度。

    原先叫 _bg_new、躺在「文档识题」区段里，可 23 处调用横跨新闻视频/应用文/
    成文/文档识题——它跟 get_db 一样是共用设施，不属于任何一个业务。
    """
    cur = db.execute("INSERT INTO bg_tasks(user_id,kind,title,total) VALUES(?,?,?,?)",
                     (uid(), kind, title, total))
    db.commit()
    return cur.lastrowid


def bg_set(con, tid, **kw):
    if not kw:
        return
    cols = ", ".join("%s=?" % k for k in kw)
    con.execute("UPDATE bg_tasks SET %s, updated_at=datetime('now','localtime') WHERE id=?" % cols,
                list(kw.values()) + [tid])
    con.commit()


def users_count():
    return get_db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def is_admin():
    return session.get("role") == "admin"


def _bump_sync():
    """组队/互监有变动时想让对端尽快刷新——版本指纹本身就含这些表（见 /api/sync），
    这里留空即可，作为语义标记。"""
    pass


def _mark_study(db, u, date):
    """记一个学习日（完成备考规划任务、或互监任务被确认）。一天一条，重复无副作用。"""
    if u and date:
        db.execute("INSERT OR IGNORE INTO study_days(user_id,date) VALUES(?,?)", (u, date))


def _study_stats(db, u):
    """连续学习天数（到今天或昨天为止未断）+ 累计学习天数。"""
    days = {r[0] for r in db.execute("SELECT date FROM study_days WHERE user_id=?", (u,))}
    total = len(days)
    if not total:
        return {"streak": 0, "total": 0}
    today = datetime.now().date()
    cur = today
    if today.isoformat() not in days:            # 今天还没学，连胜看到昨天为止
        cur = today - timedelta(days=1)
        if cur.isoformat() not in days:
            return {"streak": 0, "total": total}
    streak = 0
    while cur.isoformat() in days:
        streak += 1
        cur = cur - timedelta(days=1)
    return {"streak": streak, "total": total}


def _truthy(v, default=True):
    if v is None:
        return default
    return str(v).lower() not in ("0", "false", "no", "")


def uname(db, u):
    """查用户名。查不到说明是孤儿记录（用户已删而引用还在），给个带 id 的占位好排查。

    原先 app.py 里同名的 _uname 定义了三遍（组队/好友/聊天各一份，兜底文案分别是
    "?"、"用户N"、"好友"）——后定义的覆盖前面的，实际全都在用最后那份，另两份是死代码。
    """
    r = db.execute("SELECT username FROM users WHERE id=?", (u,)).fetchone()
    return (r["username"] if r else "") or ("用户%s" % u)

# ---------------------------------------------------------------- 成语/词语工具
# 查 ref_idiom / ref_ci 两张只读词典。零外部依赖、四个符号全被各模块用——
# 是不折不扣的地基，原先散在 app.py 中间。
CJK_RE = re.compile(r"^[一-鿿]+$")


def to_pinyin(word):
    try:
        parts = _pinyin(word, style=Style.TONE, heteronym=False, errors="default")
        return " ".join(p[0] for p in parts)
    except Exception:
        return ""


def lookup(word):
    word = (word or "").strip()
    db = get_db()
    info = {"word": word, "pinyin": "", "category": "词语", "explanation": "",
            "derivation": "", "example": "", "source": "manual", "found": False}
    if not word:
        return info
    row = db.execute("SELECT * FROM ref_idiom WHERE word=?", (word,)).fetchone()
    if row:
        info.update(pinyin=row["pinyin"] or to_pinyin(word), category="成语",
                    explanation=row["explanation"] or "", derivation=row["derivation"] or "",
                    example=row["example"] or "", source="idiom", found=True)
        return info
    row = db.execute("SELECT * FROM ref_ci WHERE word=?", (word,)).fetchone()
    if row:
        info.update(pinyin=to_pinyin(word), category="词语",
                    explanation=row["explanation"] or "", source="ci", found=True)
        return info
    row = db.execute("SELECT * FROM ci_ai WHERE word=?", (word,)).fetchone()
    if row:
        rk = row.keys()
        info.update(pinyin=row["pinyin"] or to_pinyin(word), category=row["category"] or info["category"],
                    explanation=row["explanation"] or "",
                    derivation=(row["derivation"] if "derivation" in rk else "") or "",
                    example=(row["example"] if "example" in rk else "") or "",
                    source="ai", found=True)
        return info
    info["pinyin"] = to_pinyin(word)
    # 词典都查不到时按长度猜类别：≥4 字多为「词组」（如 生理功能），2-3 字按词语
    if len(word) >= 4 and CJK_RE.match(word):
        info["category"] = "词组"
    return info


def row_to_dict(row):
    d = dict(row)
    if "starred" in d:
        d["starred"] = bool(d.get("starred"))
    return d
