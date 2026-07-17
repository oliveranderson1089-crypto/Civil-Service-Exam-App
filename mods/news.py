"""每日时政：新闻 + 新闻视频（全局共享，爬虫 + AI 提炼）。

app.py 里这块有两个连着写的区段标题（「每日时政」+「每日新闻视频」），
前一个成了空段、新闻路由全归到后一个名下——实际是一块，按实际拆。

抓取由 crawl_news.py / crawl_video.py 跑（systemd timer），这里只管读和刷新。
"""
import json
import os
import re
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from core import BASE, DB, bg_new, bg_set, get_db, log, uid
from mods.ai import _ai_call_or_error

bp = Blueprint("news", __name__)


VIDEO_BOARDS = ["国内", "国际", "四川", "备考"]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


@bp.get("/api/videos")
def videos_list():
    """每日新闻视频：只给**筛过的**（AI 按公考价值挑的），并附「为什么值得看」。
       信源全是白名单里的官方媒体 —— 没法自动确认「某个博主是不是真的」，
       所以不接受任意来源，那等于把把关的活儿丢给你自己。"""
    db = get_db()
    board = (request.args.get("board") or "").strip()
    star = request.args.get("star") in ("1", "true")
    where, args = [], []
    if board in VIDEO_BOARDS:
        where.append("v.board=?")
        args.append(board)
    if star:
        where.append("s.user_id IS NOT NULL")
    sql = ("SELECT v.*, (s.user_id IS NOT NULL) starred FROM video_items v "
           "LEFT JOIN video_stars s ON s.video_id=v.id AND s.user_id=? ")
    args = [uid()] + args
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY v.pick_date DESC, v.score DESC, v.id DESC LIMIT 120"
    rows = db.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        d["starred"] = bool(d.get("starred"))
        out.append(d)
    cnt = {r[0]: r[1] for r in db.execute(
        "SELECT board, COUNT(*) FROM video_items GROUP BY board")}
    last = db.execute("SELECT MAX(pick_date) FROM video_items").fetchone()[0] or ""
    return jsonify({"items": out, "counts": cnt, "boards": VIDEO_BOARDS, "last": last,
                    "n_star": db.execute("SELECT COUNT(*) FROM video_stars WHERE user_id=?",
                                         (uid(),)).fetchone()[0]})


@bp.post("/api/videos/<int:vid>/star")
def video_star(vid):
    db = get_db()
    have = db.execute("SELECT 1 FROM video_stars WHERE user_id=? AND video_id=?",
                      (uid(), vid)).fetchone()
    if have:
        db.execute("DELETE FROM video_stars WHERE user_id=? AND video_id=?", (uid(), vid))
        db.commit()
        return jsonify({"starred": False})
    db.execute("INSERT OR IGNORE INTO video_stars(user_id, video_id) VALUES(?,?)", (uid(), vid))
    db.commit()
    return jsonify({"starred": True})


# 画质档：chapters=418kbps、chapters2=818kbps、chapters3=1.2M、chapters4=2M。
# 优先 chapters2 —— 清晰度够看字幕，又不至于卡。
CCTV_TIERS = ("chapters2", "chapters3", "chapters", "chapters4")


def cctv_play(guid):
    """问央视网要这条片子的可播地址。

    优先拿 **mp4 分段**：那是普通渐进式 mp4，`<video>` 原生就能放 —— 不用 hls.js、
    不依赖 MSE，桌面壳那个 WebKit 也吃得下。代价是一集切成好几段，得自己接成一条时间轴。

    但**不是每条都有 mp4**：像《今日关注》，四个画质档的 url 全是空串（没转码），
    只有 HLS。所以拿不到 mp4 时退回 m3u8，前端用 hls.js 放。
    两种流实测都没有防盗链、CORS 全开，能直接放进我们自己的页面。
    """
    r = urllib.request.Request(
        "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=" + str(guid),
        headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=12) as x:
        d = json.loads(x.read().decode("utf-8", "ignore"))
    vid = d.get("video") or {}
    title = (d.get("title") or "").strip()

    for tier in CCTV_TIERS:
        chs = [{"url": c["url"], "dur": float(c.get("duration") or 0)}
               for c in (vid.get(tier) or []) if c.get("url")]
        if chs:
            return {"mode": "mp4", "chapters": chs,
                    "total": sum(c["dur"] for c in chs), "title": title}

    if d.get("hls_url"):
        return {"mode": "hls", "src": d["hls_url"],
                "total": float(vid.get("totalLength") or 0), "title": title}
    raise RuntimeError("央视网这条既没有 mp4 也没有 HLS")


@bp.get("/api/videos/<int:vid>/play")
def video_play(vid):
    """给前端播放器：这条视频怎么播。

    三种播法（`kind` 决定）：
      cctv → 自己放：央视网给的 mp4 分段，我们的播放器把它们接成一条连续的时间轴
      bili → 嵌 B 站官方播放器（人家的 iframe 没有任何嵌入限制，实测可用）
      sc   → 川观：抓取时如果拿到了直链就自己放；没拿到就只能跳出去（老实说明）
    """
    db = get_db()
    r = db.execute("SELECT * FROM video_items WHERE id=?", (vid,)).fetchone()
    if not r:
        return jsonify({"error": "视频不存在"}), 404
    row = dict(r)
    kind = row.get("kind") or "sc"
    base = {"id": vid, "kind": kind, "title": row.get("title") or "",
            "url": row.get("url") or "", "source": row.get("source") or ""}

    if kind == "bili":
        bv = row.get("guid") or ""
        return jsonify(dict(base, mode="iframe", embed=(
            "https://player.bilibili.com/player.html?bvid=%s&autoplay=0&danmaku=0&high_quality=1"
            % bv)))

    # 抓取时算好的播放地址，直接用（不用每次点播放都去请求人家的接口）
    try:
        cached = json.loads(row.get("play") or "null")
    except Exception:
        cached = None
    if cached and (cached.get("chapters") or cached.get("src")):
        return jsonify(dict(base, **cached))

    if kind == "cctv":
        try:
            info = cctv_play(row.get("guid") or "")
        except Exception as e:
            log.warning("央视取流失败 vid=%s: %s", vid, e)
            return jsonify(dict(base, mode="external",
                                note="央视网这会儿没给出播放地址，先在浏览器里看")), 200
        db.execute("UPDATE video_items SET play=? WHERE id=?",
                   (json.dumps(info, ensure_ascii=False), vid))
        db.commit()
        return jsonify(dict(base, **info))

    # 川观：抓取时没拿到直链就没辙了（它的直链藏在 JS 里，得渲染页面才拿得到）
    return jsonify(dict(base, mode="external", note="这条只能在浏览器里看"))


@bp.post("/api/videos/refresh")
def videos_refresh():
    """手动刷一次（平时是定时器每天跑）。抓取要开无头浏览器，放后台。"""
    tid = bg_new(get_db(), "video", "刷新每日新闻视频", 1)

    def run():
        con = sqlite3.connect(DB, timeout=60)
        try:
            bg_set(con, tid, status="running", message="正在抓取央视网 / B站官方号 / 川观新闻…")
            r = subprocess.run(
                [os.path.join(BASE, ".venv/bin/python3"), os.path.join(BASE, "crawl_video.py")],
                cwd=BASE, capture_output=True, text=True, timeout=600)
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            bg_set(con, tid, status="done", progress=1,
                    message=(tail[-1] if tail else "完成"))
        except Exception as ex:
            bg_set(con, tid, status="error", message=str(ex)[:150])
        finally:
            con.close()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"task": tid}), 202


@bp.get("/api/news")
def news_list():
    board = (request.args.get("board") or "").strip()
    date = (request.args.get("date") or "").strip()
    star_only = request.args.get("star") == "1"
    db = get_db()
    if star_only:
        # 收藏夹：跨板块跨日期，按收藏时间倒序
        rows = db.execute(
            "SELECT n.id,n.title,n.source,n.pub_date,n.ai_summary,COALESCE(n.board,'国内') board,"
            "length(n.content) chars, 1 starred FROM news_items n "
            "JOIN news_stars s ON s.news_id=n.id AND s.user_id=? "
            "ORDER BY s.created_at DESC LIMIT 200", (uid(),)).fetchall()
        counts = {r[0]: r[1] for r in
                  db.execute("SELECT COALESCE(board,'国内'), COUNT(*) FROM news_items GROUP BY COALESCE(board,'国内')")}
        return jsonify({"items": [dict(r) for r in rows], "dates": [], "date": "", "star_total": len(rows),
                        "counts": {b: counts.get(b, 0) for b in ("党内", "国内", "四川", "国际")}})
    where, args = [], []
    if board in ("党内", "国内", "四川", "国际"):
        where.append("board=?"); args.append(board)
    # 该板块下有哪些日期（号数导航用）
    dsql = "SELECT pub_date, COUNT(*) c FROM news_items %s GROUP BY pub_date ORDER BY pub_date DESC LIMIT 30" % (
        ("WHERE " + " AND ".join(where)) if where else "")
    dates = [{"date": r["pub_date"], "count": r["c"]} for r in db.execute(dsql, args).fetchall()]
    if not date and dates:
        date = dates[0]["date"]  # 默认最新一天
    if date:
        where.append("pub_date=?"); args.append(date)
    sql = ("SELECT n.id,n.title,n.source,n.pub_date,n.ai_summary,COALESCE(n.board,'国内') board,"
           "length(n.content) chars,(s.news_id IS NOT NULL) starred "
           "FROM news_items n LEFT JOIN news_stars s ON s.news_id=n.id AND s.user_id=%d %s "
           "ORDER BY n.id DESC LIMIT 60") % (uid(), ("WHERE " + " AND ".join("n." + w for w in where)) if where else "")
    rows = db.execute(sql, args).fetchall()
    counts = {r[0]: r[1] for r in
              db.execute("SELECT COALESCE(board,'国内'), COUNT(*) FROM news_items GROUP BY COALESCE(board,'国内')")}
    star_total = db.execute("SELECT COUNT(*) FROM news_stars WHERE user_id=?", (uid(),)).fetchone()[0]
    return jsonify({"items": [dict(r) for r in rows], "dates": dates, "date": date, "star_total": star_total,
                    "counts": {b: counts.get(b, 0) for b in ("党内", "国内", "四川", "国际")}})


@bp.post("/api/news/<int:nid>/star")
def news_star(nid):
    on = bool((request.get_json(silent=True) or {}).get("starred"))
    db = get_db()
    if on:
        db.execute("INSERT OR IGNORE INTO news_stars(user_id,news_id) VALUES(?,?)", (uid(), nid))
    else:
        db.execute("DELETE FROM news_stars WHERE user_id=? AND news_id=?", (uid(), nid))
    db.commit()
    return jsonify({"starred": on})


@bp.get("/api/news/<int:nid>")
def news_detail(nid):
    r = get_db().execute("SELECT * FROM news_items WHERE id=?", (nid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    try:
        marks = json.loads(r["marks"] or "[]") if "marks" in r.keys() else []
    except Exception:
        marks = []
    return jsonify({"id": r["id"], "title": r["title"], "url": r["url"], "source": r["source"],
                    "pub_date": r["pub_date"], "content": r["content"] or "",
                    "ai_summary": r["ai_summary"] or "", "marks": marks})


# 时政重点标注的四类考点（颜色/含义在前端一一对应）
NEWS_MARK_KINDS = ["提法", "数据", "政策", "金句"]


@bp.post("/api/news/<int:nid>/marks")
def news_marks(nid):
    """在原文里划重点：让 AI **逐字挑出**原文中的要害句，并说明是什么考点。
       关键是「逐字」——挑出来的句子必须能在原文里原样找到，否则前端根本标不上去。
       服务端会逐条核对，对不上的直接丢掉（宁可少标，不能标错位置）。"""
    db = get_db()
    r = db.execute("SELECT * FROM news_items WHERE id=?", (nid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    content = (r["content"] or "").strip()
    if len(content) < 40:
        return jsonify({"marks": []})
    try:
        old = json.loads(r["marks"] or "[]")
    except Exception:
        old = []
    if old and not request.args.get("force"):
        return jsonify({"marks": old, "cached": True})

    prompt = (
        "下面是一篇时政原文。考生没时间通读，请在原文里**划重点**：挑出 4~8 处最该记的地方，"
        "每处**必须从原文里逐字复制**（一字不差，含标点），否则没法在原文上标出来。\n\n"
        "每处给：\n"
        "· quote：从原文逐字复制的句子或短语（10~60 字，别整段抄）\n"
        "· kind：属于哪类考点，只能填 提法 / 数据 / 政策 / 金句 之一\n"
        "  （提法=新表述新概念，常识判断爱考；数据=具体数字时间，容易出选项；"
        "政策=文件名/举措/目标；金句=可直接用进申论的表述）\n"
        "· why：为什么要记它（一句话，讲清考点在哪，别复述原文）\n\n"
        '只输出 JSON：{"marks":[{"quote":"","kind":"","why":""}]}\n\n【原文】\n' + content[:4000])
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考时政老师，只从原文里逐字摘句，绝不改写、不编造。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.3, max_tokens=2000, timeout=180, json_mode=True)
    if err:
        return err
    try:
        got = json.loads(rep).get("marks") or []
    except Exception:
        return jsonify({"error": "AI 返回格式异常，请重试"}), 502

    marks, seen = [], set()
    for m in got:
        q = (m.get("quote") or "").strip()
        if not q or q in seen:
            continue
        if q not in content:                 # 对不上原文就丢掉——标错位置比不标更糟
            q2 = re.sub(r"\s+", "", q)
            hit = next((x for x in [q2] if q2 and q2 in re.sub(r"\s+", "", content)), None)
            if not hit:
                continue
            q = q2                            # 只是空白差异，用去空白版再试
            if q not in content:
                continue
        seen.add(q)
        kind = m.get("kind") if m.get("kind") in NEWS_MARK_KINDS else "提法"
        marks.append({"quote": q, "kind": kind, "why": (m.get("why") or "").strip()[:120]})
    if not marks:
        return jsonify({"error": "AI 挑出的句子和原文对不上，请重试"}), 502
    db.execute("UPDATE news_items SET marks=? WHERE id=?", (json.dumps(marks, ensure_ascii=False), nid))
    db.commit()
    return jsonify({"marks": marks})
