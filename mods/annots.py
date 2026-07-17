"""批注：手写笔迹 / 高亮 / 笔记。

存服务器而不是 localStorage：批注是长期资产，不该躺在一个浏览器的 5MiB 配额里
（2026-07-16 就是被这个配额撑爆、setItem 静默失败，笔迹全丢）。

_ann_sentence / _ann_where 是给外面用的：app.py 的搜索和复习都要把批注
接进去（见 4c8d2f6），所以它们不是私有实现，改签名要留意那两处。
"""
import json
import re

from flask import Blueprint, jsonify, request

from core import get_db, uid

bp = Blueprint("annots", __name__)


_ANN_KINDS = ("ink", "hl", "note")
_ANN_ANCHORS = ("text", "pdf", "pixel")
_ANN_MAX = 200_000        # 单条标注 data 上限；一坨手写笔迹撑死几十 KB，200K 足够且挡住异常写入
_ANN_TOTAL_MAX = 4_000_000   # 整页合计上限（压缩后一整页重度批注也就几百 KB）
_ANN_LIST_MAX = 3000      # 读回上限：POST 是逐条加的，没有条数上限，别让单页长到把 load 拖垮


_ANN_MAT_RE = re.compile(r"/api/materials/(\d+)/")
_ANN_SENT_END = "。！？；!?;\n"


def _ann_sentence(a):
    """锚句是从落笔点截的 16 个字，本身是半截话（"什么（一句话概括几个主题）尝试使"）——
    定位够用，但拿给人看不行。用前后文补成一句完整的。
    它同时也是**去重的依据**：同一段上画了好几笔，每笔落点不同、quote 各不相同（滑动窗口），
    按 quote 去重等于没去 —— 会冒出七八张几乎一样的卡片。按句子去重才是一处一条。"""
    quote = (a.get("quote") or "").strip()
    if not quote:
        return ""
    ctx = (a.get("prefix") or "") + quote + (a.get("suffix") or "")
    i = ctx.find(quote)
    if i < 0:
        return quote
    start = 0
    for p in _ANN_SENT_END:                      # 往前找上一个句末
        j = ctx.rfind(p, 0, i)
        if j >= 0 and j + 1 > start:
            start = j + 1
    end = len(ctx)
    for p in _ANN_SENT_END:                      # 往后找下一个句末
        j = ctx.find(p, i + len(quote))
        if j >= 0 and j + 1 < end:
            end = j + 1
    return ctx[start:end].strip() or quote


def _ann_where(db, u, target):
    """把批注的 target 翻成人看得懂的位置，顺带把资料信息带出来（前端点结果要用，省一次请求）。
    target 里带着资料的 URL（mat:/api/materials/48/view、view:viewer:/api/materials/99/text），
    从中抠出 id 查名字。返回 (显示用的位置, {id,name,ext} 或 None)。"""
    m = _ANN_MAT_RE.search(target or "")
    if m:
        r = db.execute("SELECT id, title, orig_name, ext FROM materials WHERE id=? AND user_id=?",
                       (int(m.group(1)), u)).fetchone()
        if r:
            name = r["title"] or r["orig_name"] or "资料"
            return "批注 · " + name, {"id": r["id"], "name": name, "ext": r["ext"] or ""}
    return "批注", None


def _ann_row(r):
    return {
        "id": r["id"], "target": r["target"], "anchor_type": r["anchor_type"],
        "anchor": json.loads(r["anchor"] or "{}"), "kind": r["kind"],
        "data": json.loads(r["data"] or "null"), "updated_at": r["updated_at"],
    }


@bp.get("/api/annots")
def ann_list():
    target = (request.args.get("target") or "").strip()
    if not target:
        return jsonify({"error": "缺少 target"}), 400
    rows = get_db().execute(
        "SELECT * FROM annotations WHERE user_id=? AND target=? ORDER BY id LIMIT ?",
        (uid(), target, _ANN_LIST_MAX)).fetchall()
    return jsonify({"items": [_ann_row(r) for r in rows]})


def _ann_parse(data):
    """校验一条标注的入参，返回 (字段dict, 错误)。"""
    target = (data.get("target") or "").strip()
    kind = (data.get("kind") or "").strip()
    at = (data.get("anchor_type") or "").strip()
    if not target or len(target) > 200:
        return None, "target 不合法"
    if kind not in _ANN_KINDS:
        return None, "kind 不合法"
    if at not in _ANN_ANCHORS:
        return None, "anchor_type 不合法"
    anchor = json.dumps(data.get("anchor") or {}, ensure_ascii=False)
    body = json.dumps(data.get("data"), ensure_ascii=False)
    if len(body) > _ANN_MAX:
        return None, "这条标注太大了"
    return {"target": target, "kind": kind, "anchor_type": at, "anchor": anchor, "data": body}, None


@bp.post("/api/annots")
def ann_create():
    f, err = _ann_parse(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO annotations(user_id,target,anchor_type,anchor,kind,data) VALUES(?,?,?,?,?,?)",
        (uid(), f["target"], f["anchor_type"], f["anchor"], f["kind"], f["data"]))
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@bp.put("/api/annots/<int:aid>")
def ann_update(aid):
    f, err = _ann_parse(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    cur = db.execute(
        "UPDATE annotations SET anchor_type=?,anchor=?,kind=?,data=?,"
        "updated_at=datetime('now','localtime') WHERE id=? AND user_id=?",
        (f["anchor_type"], f["anchor"], f["kind"], f["data"], aid, uid()))
    db.commit()
    if not cur.rowcount:
        return jsonify({"error": "没找到这条标注"}), 404
    return jsonify({"ok": True})


@bp.delete("/api/annots/<int:aid>")
def ann_delete(aid):
    db = get_db()
    cur = db.execute("DELETE FROM annotations WHERE id=? AND user_id=?", (aid, uid()))
    db.commit()
    if not cur.rowcount:
        return jsonify({"error": "没找到这条标注"}), 404
    return jsonify({"ok": True})


@bp.post("/api/annots/replace")
def ann_replace():
    """整页替换：前端画布是「一页笔迹」的整体，逐条 diff 不值当。
    一次事务里换掉这个 target 的全部标注，避免中途失败留下半页。"""
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip()
    items = data.get("items")
    if not target or len(target) > 200:
        return jsonify({"error": "target 不合法"}), 400
    if not isinstance(items, list) or len(items) > 2000:
        return jsonify({"error": "items 不合法"}), 400
    rows = []
    total = 0
    for it in items:
        f, err = _ann_parse(dict(it or {}, target=target))
        if err:
            return jsonify({"error": err}), 400
        # 光有单条上限不够：2000 条 × 200K = 400MB 也是「合法」的，
        # 而 Flask 没设 MAX_CONTENT_LENGTH，整包会先读进内存
        total += len(f["data"]) + len(f["anchor"])
        if total > _ANN_TOTAL_MAX:
            return jsonify({"error": "这一页批注太大了"}), 400
        rows.append((uid(), target, f["anchor_type"], f["anchor"], f["kind"], f["data"]))
    db = get_db()
    db.execute("DELETE FROM annotations WHERE user_id=? AND target=?", (uid(), target))
    db.executemany(
        "INSERT INTO annotations(user_id,target,anchor_type,anchor,kind,data) VALUES(?,?,?,?,?,?)", rows)
    db.commit()
    return jsonify({"ok": True, "n": len(rows)})
