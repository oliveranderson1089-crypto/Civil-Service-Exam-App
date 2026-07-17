"""上位词积累：逻辑填空的概括词提示。


"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from core import get_db
from mods.ai import _ai_call_or_error

bp = Blueprint("hyper", __name__)


@bp.get("/api/hyper")
def hyper_list():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    if q:
        rows = db.execute("SELECT * FROM hyper_items WHERE hyper LIKE ? OR subs LIKE ? "
                          "ORDER BY id DESC LIMIT 200", ("%" + q + "%", "%" + q + "%")).fetchall()
    else:
        rows = db.execute("SELECT * FROM hyper_items ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify({"items": [dict(r) for r in rows],
                    "total": db.execute("SELECT COUNT(*) FROM hyper_items").fetchone()[0]})


@bp.get("/api/hyper/daily")
def hyper_daily():
    """每日推荐 3 组：按日期确定性轮换，全站一致。"""
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM hyper_items ORDER BY id")]
    if not ids:
        return jsonify({"items": []})
    start = (datetime.now().toordinal() * 3) % len(ids)
    pick = [ids[(start + i) % len(ids)] for i in range(min(3, len(ids)))]
    rows = db.execute("SELECT * FROM hyper_items WHERE id IN (%s)" %
                      ",".join("?" * len(pick)), pick).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@bp.post("/api/hyper/ai")
def hyper_ai():
    """输入一个词/一组词 → AI 给出上位词、同类下位词、辨析与例句，并收录。"""
    word = ((request.get_json(silent=True) or {}).get("word") or "").strip()
    if not word:
        return jsonify({"error": "请输入词语"}), 400
    db = get_db()
    hit = db.execute("SELECT * FROM hyper_items WHERE hyper=?", (word,)).fetchone()
    if hit:
        return jsonify(dict(hit, cached=True))
    prompt = ("公考「逻辑填空」中，题干出现一个类别名词（上位词），空格要填该类别下的具体成员（下位词）。\n"
              "示范：戏曲 → 京剧、越剧、黄梅戏、豫剧、昆曲；文房四宝 → 笔、墨、纸、砚。\n"
              "注意 hyper 必须是可数的类别名词，subs 必须是具体事物名称，不能是形容词。\n\n"
              "给定词语：%s\n请输出 JSON：\n"
              '{"hyper":"它所属的类别名词（若它本身就是类别名词，则原样输出）",'
              '"subs":"该类别下常见的具体成员，用顿号分隔，6~10个",'
              '"note":"一句话说明题干出现这个类别词时答案该选什么（40字内）",'
              '"example":"一个含空格的逻辑填空式例句，用____表示空（30~50字）"}\n只输出 JSON。' % word)
    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是公考言语理解老师，熟悉逻辑填空的上下文提示逻辑。"},
         {"role": "user", "content": prompt}], temperature=0.4, max_tokens=400, json_mode=True)
    if err:
        return err
    try:
        d = json.loads(rep)
    except Exception:
        return jsonify({"error": "AI 返回格式异常"}), 502
    hyper = (d.get("hyper") or word).strip()
    db.execute("INSERT OR REPLACE INTO hyper_items(hyper,subs,note,example,source) VALUES(?,?,?,?,?)",
               (hyper, (d.get("subs") or "").strip(), (d.get("note") or "").strip(),
                (d.get("example") or "").strip(), "ai"))
    db.commit()
    r = db.execute("SELECT * FROM hyper_items WHERE hyper=?", (hyper,)).fetchone()
    return jsonify(dict(r, cached=False))


@bp.delete("/api/hyper/<int:hid>")
def hyper_del(hid):
    db = get_db()
    db.execute("DELETE FROM hyper_items WHERE id=?", (hid,))
    db.commit()
    return jsonify({"ok": True})
