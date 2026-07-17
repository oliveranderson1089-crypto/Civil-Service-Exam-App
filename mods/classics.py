"""古诗文：考频初始化 + 每日推荐。

_ensure_classic_freq 放这儿是因为它跨三处用（古诗文速查、每日推荐、常考），
而它本质属于古诗文。常考模块 import 它，链路仍单向：
app.py → mods/changkao → mods/classics → core。

考频是**一次性**算的（算过就跳过）：所以 classics 表虽是参考数据，却不是只读——
想把它拆成独立只读库的话，得先把这份计算挪到建库脚本里。
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify

from core import get_db, log
from mods.ai import _ai_call_or_error, ai_configured

bp = Blueprint("classics", __name__)


# 高频 & 适合申论的古诗文标题池（命中即抬高 freq，并作为每日推荐来源）
CLASSIC_HOT = [
    "登鹳雀楼", "望岳", "登高", "行路难", "将进酒", "茅屋为秋风所破歌", "石灰吟", "竹石",
    "己亥杂诗", "赤壁", "过零丁洋", "题西林壁", "游山西村", "观书有感", "水调歌头", "念奴娇",
    "满江红", "破阵子", "永遇乐", "定风波", "登飞来峰", "泊船瓜洲", "酬乐天扬州初逢席上见赠",
    "劝学", "爱莲说", "陋室铭", "岳阳楼记", "醉翁亭记", "出师表", "论语", "孟子", "荀子",
    "生于忧患死于安乐", "鱼我所欲也", "曹刿论战", "得道多助失道寡助", "赋得古原草送别",
    "无题", "春望", "闻官军收河南河北", "秋词", "浣溪沙", "卜算子", "青玉案", "沁园春",
]


def _ensure_classic_freq(db):
    if db.execute("SELECT COUNT(*) FROM classics WHERE freq>0").fetchone()[0]:
        return
    # 首次：命中高频标题的抬到高分；其余名家名篇给中分
    for t in CLASSIC_HOT:
        db.execute("UPDATE classics SET freq=100 WHERE title LIKE ?", ("%" + t + "%",))
    hot_authors = ["李白", "杜甫", "白居易", "苏轼", "辛弃疾", "李清照", "王安石", "陆游",
                   "王维", "孟浩然", "刘禹锡", "杜牧", "李商隐", "范仲淹", "毛泽东"]
    for a in hot_authors:
        db.execute("UPDATE classics SET freq=freq+30 WHERE author LIKE ?", ("%" + a + "%",))
    # 四书五经/蒙学等经典整体抬一档
    db.execute("UPDATE classics SET freq=freq+20 WHERE category IN ('论语','孟子','大学','中庸','诗经','增广贤文')")
    db.commit()


@bp.get("/api/classics/daily")
def classics_daily():
    db = get_db()
    _ensure_classic_freq(db)
    today = datetime.now().strftime("%Y-%m-%d")
    sel = ("SELECT d.classic_id, d.apply, d.common, c.title, c.author, c.dynasty, c.category, c.content "
           "FROM classic_daily d JOIN classics c ON c.id=d.classic_id WHERE d.date=?")
    row = db.execute(sel, (today,)).fetchone()
    if not row:
        # 从高频池里按日期确定性选一首（尽量适合申论）
        pool = db.execute("SELECT id FROM classics WHERE freq>=100 ORDER BY id").fetchall()
        if not pool:
            pool = db.execute("SELECT id FROM classics ORDER BY freq DESC, id LIMIT 300").fetchall()
        if not pool:
            return jsonify({"error": "暂无"}), 404
        idx = datetime.now().toordinal() % len(pool)
        cid = pool[idx]["id"]
        db.execute("INSERT OR REPLACE INTO classic_daily(date, classic_id) VALUES(?,?)", (today, cid))
        db.commit()
        row = db.execute(sel, (today,)).fetchone()
    apply_txt, common_txt = row["apply"] or "", row["common"] or ""
    if (not apply_txt or not common_txt) and ai_configured():
        prompt = ("这是《%s》（%s·%s）：\n%s\n\n请输出 JSON："
                  '{"apply":"一句话40字内，说明它适合申论/面试的哪类主题、怎么引用",'
                  '"common":"一句话60字内，本篇在行测常识判断里的常考点：作者朝代/文学地位/名句出处/'
                  '所属文体或流派/易混淆点，任选最可能考的写"}。只输出 JSON。' %
                  (row["title"], row["dynasty"], row["author"], (row["content"] or "")[:200]))
        rep, err = _ai_call_or_error(
            [{"role": "system", "content": "你是公考辅导老师，兼顾申论运用与常识判断考点，精炼实用。"},
             {"role": "user", "content": prompt}], temperature=0.5, max_tokens=260, json_mode=True)
        if not err:
            try:
                d = json.loads(rep)
                apply_txt = (d.get("apply") or apply_txt).strip()
                common_txt = (d.get("common") or common_txt).strip()
                db.execute("UPDATE classic_daily SET apply=?, common=? WHERE date=?",
                           (apply_txt, common_txt, today))
                db.commit()
            except Exception:
                log.exception("每日古诗文的 apply/common 落库失败")
    return jsonify({"id": row["classic_id"], "title": row["title"], "author": row["author"],
                    "dynasty": row["dynasty"], "category": row["category"],
                    "first_line": (row["content"] or "").split("\n")[0],
                    "apply": apply_txt, "common": common_txt})
