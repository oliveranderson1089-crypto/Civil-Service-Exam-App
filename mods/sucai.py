"""每日写作素材（与微信 08:00 推送共用一份生成结果）。

_sucai_import 扫缓存目录把素材入库（幂等），应用文那边也要用——
从这儿 import 过去，链路单向：app.py → mods/gongwen → mods/sucai → core。
"""
import os
import re
import sqlite3
import threading

from flask import Blueprint, jsonify, request

from core import DB, get_db, log
from mods.ai import ai_chat, ai_configured

bp = Blueprint("sucai", __name__)


KAOGONG_CACHE = os.environ.get("KAOGONG_CACHE", os.path.expanduser("~/.openclaw/kaogong-cache"))
_SUCAI_KIND_MAP = {"人物事例": "人物事例", "事实论据": "人物事例", "具体事例": "具体事例",
                   "理论论据": "理论论据", "衔接表达": "衔接表达"}


def _sucai_parse(text):
    """解析 kaogong-cache 每日素材文本 → [(kind, topic, content)]；兼容早期无小节头的格式。"""
    items, kind = [], "人物事例"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^【(人物事例|事实论据|具体事例|理论论据|衔接表达)】$", line)
        if m:
            kind = _SUCAI_KIND_MAP[m.group(1)]
            continue
        m = re.match(r"^(?:\d+[.、．]\s*|[·•]\s*)(.+)$", line)
        if not m:
            continue
        body = m.group(1).strip()
        topic = ""
        tm = re.match(r"^【(.+?)】\s*(.*)$", body)
        if tm and tm.group(2).strip():
            topic, body = tm.group(1), tm.group(2).strip()
        if body:
            items.append((kind, topic, body))
    return items


def _sucai_import(db):
    """扫描缓存目录，把还没入库的日期解析进 sucai_items（幂等）。"""
    try:
        files = [f for f in os.listdir(KAOGONG_CACHE) if re.match(r"^\d{4}-\d{2}-\d{2}\.txt$", f)]
    except Exception:
        return
    have = {r[0] for r in db.execute("SELECT DISTINCT date FROM sucai_items")}
    changed = False
    for f in sorted(files):
        d = f[:10]
        if d in have:
            continue
        try:
            text = open(os.path.join(KAOGONG_CACHE, f), encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for kind, topic, content in _sucai_parse(text):
            db.execute("INSERT OR IGNORE INTO sucai_items(date,kind,topic,content) VALUES(?,?,?,?)",
                       (d, kind, topic, content))
        changed = True
    if changed:
        db.commit()
        _spawn_fill_examples()   # 新导入的衔接表达后台补例句，用户不用挨个点


_FILL_RUNNING = False


def _spawn_fill_examples():
    """后台线程给缺例句的「衔接表达」补 AI 例句（每天素材更新后自动跑一次）。"""
    global _FILL_RUNNING
    if _FILL_RUNNING or not ai_configured():
        return
    _FILL_RUNNING = True

    def run():
        global _FILL_RUNNING
        try:
            con = sqlite3.connect(DB, timeout=30)
            rows = con.execute("SELECT id, content FROM sucai_items WHERE kind='衔接表达' "
                               "AND (example IS NULL OR example='') ORDER BY id DESC LIMIT 20").fetchall()
            for sid, content in rows:
                prompt = ("下面是一句申论写作的衔接表达/万能句式：\n%s\n\n请用它写一个申论语境下的规范例句"
                          "（书面化、紧扣治理/民生/发展类主题，30~60字），只输出例句本身。" % content)
                try:
                    rep = ai_chat([{"role": "system", "content": "你是申论写作辅导老师，例句规范、书面化。"},
                                   {"role": "user", "content": prompt}], temperature=0.6, max_tokens=200)
                    con.execute("UPDATE sucai_items SET example=? WHERE id=?", (rep.strip(), sid))
                    con.commit()
                except Exception:
                    continue
            con.close()
        except Exception:
            log.exception("后台补例句任务异常退出")
        finally:
            _FILL_RUNNING = False

    threading.Thread(target=run, daemon=True).start()


@bp.get("/api/sucai")
def sucai_list():
    kind = (request.args.get("kind") or "").strip()
    db = get_db()
    _sucai_import(db)
    counts = {r[0]: r[1] for r in db.execute("SELECT kind, COUNT(*) FROM sucai_items GROUP BY kind")}
    where, args = "", []
    if kind and kind != "全部":
        where = "WHERE kind=?"; args = [kind]
    # 分页取，理由同 partydict：原先一次 400 条 = 226 KB，进页面就得等它整份下完。
    # 多取一条判断「还有没有」。
    limit = max(1, min(int(request.args.get("limit") or 120), 400))
    offset = max(0, int(request.args.get("offset") or 0))
    rows = db.execute("SELECT * FROM sucai_items %s ORDER BY date DESC, id LIMIT ? OFFSET ?" % where,
                      args + [limit + 1, offset]).fetchall()
    return jsonify({"items": [dict(r) for r in rows[:limit]], "more": len(rows) > limit,
                    "counts": counts})
