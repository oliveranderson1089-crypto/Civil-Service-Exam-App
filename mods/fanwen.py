"""人民时评·申论范文：范文库 + AI 拆解 + 逐段批注。

零反向依赖：app.py 没有任何地方回头用这里的东西，
所以是拆模块时最干净的一块。
"""
import json
import os
import subprocess

from flask import Blueprint, jsonify, request

from core import BASE, get_db, log, uid
from mods.ai import _ai_call_or_error

bp = Blueprint("fanwen", __name__)


@bp.get("/api/fanwen")
def fanwen_list():
    """人民时评范文列表。带日期条（像每日时政），点某天看那天那篇。
       只回列表元信息 + 收藏态，正文走详情接口（列表页不用一次拉一堆全文）。"""
    db = get_db()
    star = request.args.get("star") in ("1", "true")
    sql = ("SELECT m.id, m.pub_date, m.column_name, m.title, m.author, m.pullquote, "
           "length(m.content) chars, "
           "(m.analysis IS NOT NULL AND m.analysis<>'') has_ai, "
           "(s.user_id IS NOT NULL) starred "
           "FROM essay_models m LEFT JOIN essay_model_stars s "
           "ON s.model_id=m.id AND s.user_id=? ")
    if star:
        sql += "WHERE s.user_id IS NOT NULL "
    sql += "ORDER BY m.pub_date DESC, m.id DESC LIMIT 120"
    rows = [dict(r) for r in db.execute(sql, (uid(),)).fetchall()]
    for r in rows:
        r["starred"] = bool(r["starred"])
    n_star = db.execute("SELECT COUNT(*) FROM essay_model_stars WHERE user_id=?",
                        (uid(),)).fetchone()[0]
    return jsonify({"items": rows, "n_star": n_star})


@bp.get("/api/fanwen/<int:mid>")
def fanwen_detail(mid):
    r = get_db().execute("SELECT * FROM essay_models WHERE id=?", (mid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    try:
        ann = json.loads(r["annotations"]) if r["annotations"] else {}
    except Exception:
        ann = {}
    return jsonify({"id": r["id"], "pub_date": r["pub_date"], "column_name": r["column_name"],
                    "title": r["title"], "author": r["author"], "source_url": r["source_url"],
                    "pullquote": r["pullquote"] or "", "content": r["content"] or "",
                    "analysis": r["analysis"] or "", "annotations": ann})


@bp.post("/api/fanwen/<int:mid>/star")
def fanwen_star(mid):
    db = get_db()
    have = db.execute("SELECT 1 FROM essay_model_stars WHERE user_id=? AND model_id=?",
                      (uid(), mid)).fetchone()
    if have:
        db.execute("DELETE FROM essay_model_stars WHERE user_id=? AND model_id=?", (uid(), mid))
        db.commit()
        return jsonify({"starred": False})
    db.execute("INSERT OR IGNORE INTO essay_model_stars(user_id, model_id) VALUES(?,?)",
               (uid(), mid))
    db.commit()
    return jsonify({"starred": True})


@bp.post("/api/fanwen/<int:mid>/ai")
def fanwen_ai(mid):
    """AI 把这篇范文拆开讲：怎么起题、怎么分论、亮点在哪、哪些句子能直接仿写。
       生成一次就缓存进 analysis（全局共享，不重复花钱）。"""
    r = get_db().execute("SELECT * FROM essay_models WHERE id=?", (mid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["analysis"] and not force:
        return jsonify({"content": r["analysis"], "cached": True})
    body = (r["content"] or "")[:8000]
    prompt = (
        "下面是《人民日报》「人民时评」栏目的一篇评论《%s》。它是标准的申论大作文范本。\n"
        "请面向四川省考申论考生，用简体中文、Markdown 输出「范文拆解」，分这几节：\n"
        "## 一、中心论点\n（一句话点明作者要论证什么）\n"
        "## 二、结构脉络（怎么提出问题→分析问题→解决问题）\n"
        "（逐段梳理：每一部分在做什么，分论点是什么，用了什么论证方法）\n"
        "## 三、亮点与可借鉴之处\n（选材、论证、说理的高明处，考生能学什么）\n"
        "## 四、可直接仿写的过渡句与金句\n（摘录原文里的过渡句/结论句/金句，并说明什么场景能套用）\n"
        "## 五、这篇能用在哪些申论主题\n（点出适配的话题方向）\n"
        "要求：紧扣原文，具体到句，别空泛。写完整不要截断。\n\n正文：\n%s"
    ) % (r["title"], body)
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是资深申论辅导老师，拆解范文准确、具体、实用，用简体中文 Markdown，务必完整不截断。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=5000)
    if err:
        return err
    db = get_db()
    db.execute("UPDATE essay_models SET analysis=? WHERE id=?", (reply, mid))
    db.commit()
    return jsonify({"content": reply, "cached": False})


@bp.post("/api/fanwen/<int:mid>/annotate")
def fanwen_annotate(mid):
    """对照精读：给关键段落逐段批注，渲染时批注就跟在那段后面 —— 解决「解析和正文两头看、
       对不上」的割裂感。返回 {段号: 批注}，生成一次缓存进 annotations。"""
    r = get_db().execute("SELECT * FROM essay_models WHERE id=?", (mid,)).fetchone()
    if not r:
        return jsonify({"error": "未找到"}), 404
    force = (request.get_json(silent=True) or {}).get("force")
    if r["annotations"] and not force:
        try:
            return jsonify({"notes": json.loads(r["annotations"]), "cached": True})
        except Exception:
            log.debug("annotations 缓存不是合法 JSON，重新生成", exc_info=True)
    paras = [p for p in (r["content"] or "").split("\n") if p.strip()]
    numbered = "\n".join("[%d] %s" % (i, p) for i, p in enumerate(paras))
    prompt = (
        "下面是《人民日报》「人民时评」范文《%s》，每段前面标了段号 [n]。\n"
        "请给**关键段落**逐段批注（不必每段都批，挑真正有讲头的：论证手法、过渡、亮点句、可仿写处）。\n"
        "每条批注一句话、具体、能直接学（如「用数据+案例支撑分论点一」「这句过渡承上启下，可套用」）。\n\n"
        "%s\n\n"
        '只输出 JSON：{"notes":[{"i":段号,"note":"批注"}]}' % (r["title"], numbered))
    reply, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论老师，给范文逐段批注，具体到句、能直接学。严格输出 JSON。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=3000, json_mode=True)
    if err:
        return err
    notes = {}
    try:
        for x in json.loads(reply).get("notes") or []:
            i = int(x.get("i"))
            note = (x.get("note") or "").strip()
            if 0 <= i < len(paras) and note:
                notes[str(i)] = note
    except Exception:
        log.warning("AI 返回的批注 JSON 解析失败，这次批注为空", exc_info=True)
    db = get_db()
    db.execute("UPDATE essay_models SET annotations=? WHERE id=?",
               (json.dumps(notes, ensure_ascii=False), mid))
    db.commit()
    return jsonify({"notes": notes, "cached": False})


@bp.post("/api/fanwen/refresh")
def fanwen_refresh():
    """手动抓一次今天的人民时评（平时定时器 07:10 跑）。抓取很轻量（纯 HTTP），同步跑就行。"""
    before = get_db().execute("SELECT COUNT(*) FROM essay_models").fetchone()[0]
    try:
        r = subprocess.run(
            [os.path.join(BASE, ".venv/bin/python3"), os.path.join(BASE, "crawl_rmsp.py")],
            cwd=BASE, capture_output=True, text=True, timeout=90)
    except Exception as ex:
        return jsonify({"error": "抓取失败：" + str(ex)[:120]}), 500
    after = get_db().execute("SELECT COUNT(*) FROM essay_models").fetchone()[0]
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    return jsonify({"added": after - before, "msg": tail[-1] if tail else "完成"})
