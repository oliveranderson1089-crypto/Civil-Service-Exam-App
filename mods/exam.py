"""全国考情：各地招考公告的汇总列表（读 + 手动刷新）。

抓取和归类都在 crawl_exam.py（systemd timer 每天两次），这里只管读。
和「每日时政」是同一套分工：爬虫是独立进程，Web 端不在请求里做网络抓取——
一个源卡住 30 秒，整个页面就跟着卡 30 秒。

**关注地区**：考情最怕的是「刷不到自己要考的那个省」。所以有一份用户级的关注列表，
默认落在四川（这个 App 的主用户在四川），进页面先看自己的省，再按需切「全国」。
"""
import json
import os
import sqlite3
import subprocess
import threading

from flask import Blueprint, jsonify, request

from core import BASE, DB, bg_new, bg_set, get_db, uid

bp = Blueprint("exam", __name__)

# 和 crawl_exam.KINDS 保持一致。这里再写一份是为了让 Web 端不 import 爬虫脚本
# （那个脚本 import 时会读 config.json、连 AI 配置，Web 进程不该背这些）。
KINDS = ["国考", "省考", "事考", "选调", "教师", "医疗", "警法", "其他"]
REGIONS = ["全国", "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
           "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东",
           "河南", "湖北", "湖南", "广东", "广西", "海南",
           "重庆", "四川", "贵州", "云南", "西藏",
           "陕西", "甘肃", "青海", "宁夏", "新疆"]
DEFAULT_FOLLOW = ["四川"]


def _get_follow(db):
    """关注地区存在 users.exam_follow（JSON 数组），跟 home_order / ui_orders 一个路子。

    没设过 → 给默认值；设成空数组 → **就是空的**，不能再兜回默认，
    否则「我不想只看四川」这个操作永远生效不了。
    """
    r = db.execute("SELECT exam_follow FROM users WHERE id=?", (uid(),)).fetchone()
    if not r or r[0] is None:
        return list(DEFAULT_FOLLOW)
    try:
        v = json.loads(r[0])
    except Exception:
        return list(DEFAULT_FOLLOW)
    return [x for x in v if x in REGIONS] if isinstance(v, list) else list(DEFAULT_FOLLOW)


@bp.get("/api/exam/notices")
def exam_notices():
    """公告列表。筛选：kind（考试类型）/ region（地区）/ q（标题关键词）。

    region 传 'follow' = 只看关注的省 + 全国性的那些；不传 = 不限地区。
    """
    db = get_db()
    kind = (request.args.get("kind") or "").strip()
    region = (request.args.get("region") or "").strip()
    q = (request.args.get("q") or "").strip()
    try:
        limit = min(300, max(1, int(request.args.get("limit") or 120)))
    except ValueError:
        limit = 120

    where, args = [], []
    if kind in KINDS:
        where.append("kind=?")
        args.append(kind)
    if region == "follow":
        f = _get_follow(db)
        # 全国性公告（国考、部委直属事业单位）对谁都算数，永远带上，
        # 否则「只看四川」会把国考公告也一起藏掉。
        picks = f + ["全国"]
        where.append("region IN (%s)" % ",".join("?" * len(picks)))
        args += picks
    elif region in REGIONS:
        where.append("region=?")
        args.append(region)
    if q:
        where.append("title LIKE ?")
        args.append("%" + q + "%")

    sql = "SELECT * FROM exam_notices"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # 没日期的排最后：pub_date 是空串时 ORDER BY DESC 会把它顶到最前面，
    # 一条不知道什么时候发的公告占着列表第一行，比排在末尾误导得多。
    sql += " ORDER BY (pub_date='') ASC, pub_date DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in db.execute(sql, args)]

    counts = {r[0]: r[1] for r in db.execute(
        "SELECT kind, COUNT(*) FROM exam_notices GROUP BY kind")}
    by_region = {r[0]: r[1] for r in db.execute(
        "SELECT region, COUNT(*) FROM exam_notices GROUP BY region")}
    last = db.execute("SELECT MAX(created_at) FROM exam_notices").fetchone()[0] or ""
    return jsonify({"items": rows, "kinds": KINDS, "regions": REGIONS,
                    "counts": counts, "by_region": by_region,
                    "follow": _get_follow(db), "updated_at": last,
                    "total": db.execute("SELECT COUNT(*) FROM exam_notices").fetchone()[0]})


@bp.put("/api/exam/follow")
def exam_follow():
    """设置关注的地区（多选）。存 settings 表，按用户分键。"""
    data = request.get_json(silent=True) or {}
    picks = [x for x in (data.get("regions") or []) if x in REGIONS and x != "全国"]
    db = get_db()
    db.execute("UPDATE users SET exam_follow=? WHERE id=?",
               (json.dumps(picks, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"regions": picks})


@bp.post("/api/exam/refresh")
def exam_refresh():
    """手动抓一轮（平时靠定时器）。30 多个源 + AI 归类要跑几分钟，扔后台。

    可带 regions=[...] 只跑指定地区——只想看看自己那个省有没有新公告时，
    不必为它等全国跑完。
    """
    data = request.get_json(silent=True) or {}
    picks = [x for x in (data.get("regions") or []) if x in REGIONS]
    tid = bg_new(get_db(), "exam", "刷新全国考情", 1)

    def run():
        con = sqlite3.connect(DB, timeout=60)
        try:
            bg_set(con, tid, status="running",
                   message="正在抓取招考公告…（%s）" % ("、".join(picks) if picks else "全国"))
            r = subprocess.run(
                [os.path.join(BASE, ".venv/bin/python3"),
                 os.path.join(BASE, "crawl_exam.py")] + picks,
                cwd=BASE, capture_output=True, text=True, timeout=1800)
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            bg_set(con, tid, status="done", progress=1,
                   message=(tail[-1] if tail else "完成"))
        except Exception as ex:
            bg_set(con, tid, status="error", message=str(ex)[:150])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid}), 202
