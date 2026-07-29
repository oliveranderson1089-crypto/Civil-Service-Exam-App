"""遗忘曲线复习：艾宾浩斯间隔。


"""
import json
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from core import get_db, log, uid
from mods.annots import _ann_sentence, _ann_where

bp = Blueprint("review", __name__)


REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60]  # 达到第 n 阶后，下次间隔天数


def _review_due(db, u, today):
    states = {(r["kind"], r["item_id"]): r for r in
              db.execute("SELECT * FROM review_state WHERE user_id=?", (u,)).fetchall()}
    due = []

    def check(kind, rid, created, payload):
        st = states.get((kind, rid))
        if st:
            if (st["next_due"] or "") <= today:
                due.append(dict(payload, kind=kind, id=rid, stage=st["stage"]))
        elif (created or "")[:10] < today:  # 收录次日进入第一轮复习
            due.append(dict(payload, kind=kind, id=rid, stage=0))

    for r in db.execute("SELECT * FROM entries WHERE user_id=?", (u,)):
        back = "\n".join(x for x in [
            (r["explanation"] or "").strip(),
            ("出处：" + r["derivation"]) if r["derivation"] else "",
            ("例句：" + r["example"]) if r["example"] else "",
            ("📝 " + r["note"]) if r["note"] else ""] if x)
        check("entry", r["id"], r["created_at"], {
            "title": r["word"], "sub": r["category"] or "词语", "body": (r["explanation"] or "")[:90],
            "front": r["word"], "front_sub": (r["pinyin"] or "") + " · " + (r["category"] or "词语"),
            "back": back or "（无释义）"})
    # 常考里的高频成语 / 实词搭配：按真题考频排的，比自己零散收录的更该背。
    # 两件事必须分开办，不然「高频成语」这块等于没进复习 —— 都是实测出来的：
    #   · 成语和实词**各算各的配额**。两边的 freq 根本不是一个量纲：实词是 902~1000
    #     （词表权重），成语是 4~47（真题考频）。混在一起 ORDER BY freq 排，99 条实词
    #     全霸在前面，894 条成语只挤得进 21 条。
    #   · 新词要**滚动**补。老写法固定取考频前 N 条，这批一背熟就再没有新的了
    #     （873 条成语永远轮不到，「不再规划新成语」就是这么来的）。改成
    #     「已进复习轮的照常按到期出 ＋ 没背过的按考频补足配额」，背熟一批自动往后推一批。
    _lw = _rv_limits(db, u)["word"]
    ck_seen = {k[1] for k in states if k[0] == "changkao"}   # 已在复习轮里的，不占新词配额
    # 一次放多少「没背过的」进来。0（不限）就是**真的**不限：别在这儿写词库现有条数当上限，
    # 词库一涨就又变成隐形天花板 —— 上一版写死 894 就是这么把新成语挡在外面的。
    inf = float("inf")
    ck_quota = {"成语": inf if _lw == 0 else max(40, _lw),
                "实词": inf if _lw == 0 else max(15, _lw // 2)}
    # ORDER BY board 在前，保证同板块的行连在一起，配额才扣得准
    for r in db.execute(
            "SELECT id, board, title, content, note, example, example_src, meaning "
            "FROM changkao_items WHERE board IN ('成语','实词') "
            "ORDER BY board, COALESCE(freq,0) DESC, id"):
        if r["id"] not in ck_seen:
            if ck_quota.get(r["board"], 0) <= 0:
                continue
            ck_quota[r["board"]] -= 1
        body = (r["content"] or "").strip()
        # 实词的 content 是「常用搭配」，词义单独放在 meaning —— 背面先给词义、再给搭配，才记得住
        mean = (r["meaning"] or "").strip()
        parts = []
        if mean:
            parts.append(("释义：" if r["board"] == "实词" else "") + mean)
        if body:
            parts.append(("搭配：" + body) if r["board"] == "实词" and mean else body)
        back = "\n".join(parts)
        if r["note"]:
            back += "\n\n📌 " + r["note"]
        if r["example"]:                       # 光有释义记不住怎么用，背面给个例句
            back += "\n\n✍️ 例句：" + r["example"] + (
                ("\n　　—— " + r["example_src"]) if r["example_src"] else "")
        check("changkao", r["id"], "2000-01-01", {          # 全局内容，不按收录时间等一天
            "title": r["title"] or "", "sub": r["board"] or "常考",
            "body": (mean or body)[:90],
            "front": r["title"] or "", "front_sub": "常考 · " + (r["board"] or ""),
            "back": back or "（无释义）"})

    # 古诗（全局内容，人人都背）：只收「常识常考的话题类型 ＋ 篇中有能当申论素材的句子」的诗。
    # 两个条件都在 gen_gushi.py 入库时卡死（话题白名单 ＋ 名句必须是原文子串），这儿只管出卡 ——
    # 判定放在出卡时就成了「每天现算一遍」，而且核不上原文的坏卡照样会漏到脸上。
    # 配额跟常考同一套办法：已进复习轮的照常按到期出，没背过的按考频滚动补足，背熟一批自动往后推。
    _lg = _rv_limits(db, u)["gushi"]
    g_seen = {k[1] for k in states if k[0] == "gushi"}
    g_quota = float("inf") if _lg == 0 else max(10, _lg)
    for r in db.execute(
            "SELECT g.id, g.line, g.topic, g.theme, g.common, g.apply, "
            "c.title, c.author, c.dynasty, c.content, c.translation "
            "FROM gushi_cards g JOIN classics c ON c.id=g.classic_id "
            "ORDER BY COALESCE(g.freq,0) DESC, g.id"):
        if r["id"] not in g_seen:
            if g_quota <= 0:
                continue
            g_quota -= 1
        # 正面只给篇名和话题，名句要靠自己背出来 —— 名句写在正面就等于没考
        back = "「" + (r["line"] or "") + "」"
        if r["common"]:
            back += "\n\n📖 常识考点：" + r["common"]
        if r["apply"]:
            back += "\n\n✍️ 申论怎么用：" + r["apply"]
        body = (r["content"] or "").strip()
        if body:
            back += "\n\n【全文】" + body[:200]
        if r["translation"]:
            back += "\n\n【译文】" + r["translation"][:160]
        who = ((r["dynasty"] or "") + " · " + (r["author"] or "")).strip(" ·")
        check("gushi", r["id"], "2000-01-01", {          # 全局内容，不按收录时间等一天
            "title": r["title"] or "", "sub": r["topic"] or "古诗",
            "body": (r["line"] or "")[:90],
            "front": "《" + (r["title"] or "") + "》",
            "front_sub": (who + " · " + (r["topic"] or "")).strip(" ·"),
            "back": back})

    for r in db.execute("SELECT * FROM wrong_questions WHERE user_id=?", (u,)):
        back = "\n".join(x for x in [
            ("【知识点】" + r["points"]) if r["points"] else "",
            ("【方法】" + r["method"]) if r["method"] else "",
            ("【技巧】" + r["skill"]) if r["skill"] else "",
            ("【步骤】" + r["steps"]) if r["steps"] else "",
            ("【答案】" + r["answer"]) if r["answer"] else ""] if x)
        check("wrongq", r["id"], r["created_at"], {
            "title": (r["question"] or "（图片错题）")[:36], "sub": r["qtype"] or r["board"] or "错题",
            "body": (r["points"] or "")[:90],
            "front": (r["question"] or "（图片错题）"), "front_sub": r["qtype"] or r["board"] or "错题",
            "back": back or "（无解析，可回错题本重新分析）"})
    for r in db.execute("SELECT s.classic_id cid, s.created_at ca, c.title t, c.author a, c.dynasty dy, "
                        "c.content ct, c.translation tr FROM classic_stars s "
                        "JOIN classics c ON c.id=s.classic_id WHERE s.user_id=?", (u,)):
        back = (r["ct"] or "")
        if r["tr"]:
            back += "\n\n【译文】" + r["tr"][:300]
        check("classic", r["cid"], r["ca"], {
            "title": r["t"], "sub": r["a"] or "古诗文", "body": (r["ct"] or "").split("\n")[0][:44],
            "front": r["t"], "front_sub": ((r["dy"] or "") + " · " + (r["a"] or "")).strip(" ·"),
            "back": back or "（无内容）"})
    # 议论文素材（全局每日更新，人人都要背）：最近 60 天的进入复习轮
    for r in db.execute("SELECT * FROM sucai_items WHERE date >= date('now','localtime','-60 day') "
                        "ORDER BY id DESC LIMIT 300"):
        body = (r["content"] or "").strip()
        back = body + (("\n\n【例句】" + r["example"]) if r["example"] else "")
        # 正面给「人名/地名 + 首句」当回忆线索（素材开头就是主体），光给「为民·担当」这种主题回忆不起来
        cue = re.split(r"[，,。；;、]", body, maxsplit=1)[0][:22]
        front = cue or (r["topic"] or "").strip() or (r["kind"] or "素材")
        front_sub = (r["kind"] or "素材") + ((" · " + r["topic"]) if r["topic"] else "")
        if r["kind"] == "衔接表达":          # 句式类：正面给用途，背面给句式本身
            front, front_sub = "衔接表达 · 回忆句式", (r["kind"] or "素材")
            back = body + (("\n\n【例句】" + r["example"]) if r["example"] else "")
        check("sucai", r["id"], r["created_at"], {
            "title": (r["topic"] or r["kind"] or "素材")[:36], "sub": r["kind"] or "素材",
            "body": body[:90], "front": front, "front_sub": front_sub,
            "back": back or "（无内容）"})
    # 手写批注：你圈过的地方按遗忘曲线回来找你 —— 圈重点本来就是「这里要紧」的意思，
    # 圈完再也不见面就白圈了。这是张「回看卡」：正面是你圈的那句话，翻开是它的上下文。
    #   · 只有带原文的才进（pixel 锚是一坨没内容的像素，进了也没得看）；PDF 的原文取自 textLayer。
    #   · 同一句话上划了好几笔只提醒一次，按**最早**那一笔的 id 记进度 —— 用升序取，
    #     这样以后在同一句上再补几笔也不会让复习进度重来。
    seen_ann = set()
    # 没 quote 的（pixel 锚）在 SQL 里就滤掉：存量老批注全是 pixel 锚，光一个用户就有好几百条，
    # 不滤的话 LIMIT 会被它们占满，带原文的新批注一条也取不到。
    for r in db.execute("SELECT id, target, anchor, created_at FROM annotations "
                        "WHERE user_id=? AND anchor LIKE '%\"quote\"%' ORDER BY id LIMIT 500", (u,)):
        try:
            a = json.loads(r["anchor"] or "{}")
        except Exception:
            continue
        quote = (a.get("quote") or "").strip()
        if not quote:
            continue
        sent = _ann_sentence(a) or quote        # 按句子去重＋卡片给整句（见 _ann_sentence）
        key = (r["target"], sent)
        if key in seen_ann:
            continue
        seen_ann.add(key)
        where, _mat = _ann_where(db, u, r["target"])
        if a.get("page"):
            where += " · 第 %d 页" % a["page"]
        ctx = ((a.get("prefix") or "") + quote + (a.get("suffix") or "")).strip()
        check("annot", r["id"], r["created_at"], {
            "title": sent[:36], "sub": where, "body": sent[:90],
            "front": sent, "front_sub": where,
            "back": ctx or sent})
    return due


# 复习分组：词语句子 / 每日积累 / 错题，分开背，不混在一副牌里。
# 加新来源时**只改这里**：/api/review/done 的白名单直接取自它（见那儿的注释）。
RV_GROUP = {"entry": "word", "classic": "word", "changkao": "word", "sucai": "daily",
            "gushi": "gushi", "annot": "annot", "wrongq": "wrongq"}
RV_NAMES = {"word": "词语句子", "daily": "每日积累", "gushi": "古诗",
            "annot": "批注", "wrongq": "错题"}
# 每日复习量默认值（0 = 不限）。批注单独一组：跟「每日积累」挤一个额度的话，素材排在前面，
# 20 条一占满，圈过的重点一条也出不来（实测过 —— 7 条批注全被截掉）。
# 古诗同理单开一组：并进「词语句子」的话，前面 40 条成语一占满就永远轮不到诗。
# 5 首是**一天背得完**的量：整首诗＋考点＋申论用法，比背一个成语重得多。
RV_LIMIT_DEF = {"word": 40, "daily": 20, "gushi": 5, "annot": 10, "wrongq": 10}
RV_GROUPS = list(RV_LIMIT_DEF)                             # 分组名单只此一份，别再手抄


def _rv_limits(db, u):
    r = db.execute("SELECT rv_limits FROM users WHERE id=?", (u,)).fetchone()
    try:
        got = json.loads((r["rv_limits"] if r else "") or "{}")
    except Exception:
        got = {}
    out = {}
    for k, v in RV_LIMIT_DEF.items():
        n = got.get(k)
        out[k] = v if n is None else max(0, min(500, int(n)))
    return out


@bp.get("/api/review/limits")
def review_limits_get():
    db = get_db()
    lim = _rv_limits(db, uid())
    due = _review_due(db, uid(), datetime.now().strftime("%Y-%m-%d"))
    pool = dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        pool[RV_GROUP.get(it["kind"], "wrongq")] += 1
    return jsonify({"limits": lim, "default": RV_LIMIT_DEF, "names": RV_NAMES, "due": pool})


@bp.post("/api/review/limits")
def review_limits_set():
    d = request.get_json(silent=True) or {}
    cur = _rv_limits(get_db(), uid())
    for k in RV_LIMIT_DEF:
        if k in d:
            try:
                cur[k] = max(0, min(500, int(d[k])))
            except Exception:
                log.debug("复习上限收到非法值，已忽略", exc_info=True)
    db = get_db()
    db.execute("UPDATE users SET rv_limits=? WHERE id=?",
               (json.dumps(cur, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"limits": cur})


@bp.get("/api/review/today")
def review_today():
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    due = _review_due(db, uid(), today)
    # 组内先后。changkao 以前没写在这儿，靠默认值排到 9（最末），跟别的组混着看不出问题；
    # 现在显式排在 word 组末位 —— 自己收录的词先背，常考的填满剩下的额度。
    order = {"entry": 0, "classic": 1, "changkao": 2, "sucai": 3, "gushi": 4,
             "annot": 5, "wrongq": 6}
    # 组内排序：**已经在复习轮里的排前面**（stage>0 说明背过一遍了，别让它一直往后堆），
    # 然后才是新词。被上限截掉的不动 next_due —— 只是今天不出现，明天照样在。
    due.sort(key=lambda x: (order.get(x["kind"], 9), -int(x.get("stage") or 0), x["id"]))
    lim = _rv_limits(db, uid())
    pool = dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        it["group"] = RV_GROUP.get(it["kind"], "wrongq")
        pool[it["group"]] += 1
    # 今天已经复习过、且成功推到以后的（认识/模糊 → next_due>today）算已完成，要**从每日额度里扣掉**。
    # 不然「每日复习量 40」只截断每次显示多少 —— 做完 40 条一刷新，池子里剩下的又冒出 40 条，
    # 感觉像「进度被重置」。忘记的（next_due=today）不算完成，它本来就该今天再出现。
    done_today = dict.fromkeys(RV_GROUPS, 0)
    for r in db.execute(
            "SELECT kind, COUNT(*) c FROM review_state "
            "WHERE user_id=? AND last_done=? AND next_due>? GROUP BY kind",
            (uid(), today, today)):
        done_today[RV_GROUP.get(r["kind"], "wrongq")] += r["c"]
    kept, used = [], dict.fromkeys(RV_GROUPS, 0)
    for it in due:
        g = it["group"]
        if lim[g] and (used[g] + done_today[g]) >= lim[g]:   # 上限 0 = 不限；今天做过的占额度
            continue
        used[g] += 1
        kept.append(it)
    resp = {"today": today, "count": len(kept),
            "groups": used, "pool": pool, "limits": lim, "done_today": done_today}
    # 首页角标只要 count（原先连整份 items 一起回，80KB 只为显示一个数字）。
    # 带 ?count=1 就省掉那份大列表；复习页不带参，照常拿全量。
    if not request.args.get("count"):
        resp["items"] = kept
    return jsonify(resp)


@bp.post("/api/review/done")
def review_done():
    data = request.get_json(silent=True) or {}
    kind, rid = (data.get("kind") or "").strip(), int(data.get("id") or 0)
    result = (data.get("result") or "know").strip()  # know认识 / fuzzy模糊 / forget忘记
    # 白名单直接取自 RV_GROUP，别手抄第二份 —— 上次加「常考」这一路复习来源时，
    # 取词那边（_review_due）加了、提交这边忘了加，结果卡片点「认识」直接「参数错误」。
    if kind not in RV_GROUP or not rid:
        return jsonify({"error": "参数错误"}), 400
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    st = db.execute("SELECT stage FROM review_state WHERE user_id=? AND kind=? AND item_id=?",
                    (uid(), kind, rid)).fetchone()
    cur = st["stage"] if st else 0
    if result == "forget":       # 忘记：重置，今日稍后重现
        stage, iv, nd = 0, 0, today
    elif result == "fuzzy":      # 模糊：不升轮，明天再看
        stage, iv = max(cur, 1), 1
        nd = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:                        # 认识：进入下一轮（1/2/4/7/15/30/60）
        stage = cur + 1
        iv = REVIEW_INTERVALS[min(stage, len(REVIEW_INTERVALS) - 1)]
        nd = (datetime.now() + timedelta(days=iv)).strftime("%Y-%m-%d")
    db.execute("INSERT OR REPLACE INTO review_state(user_id,kind,item_id,stage,next_due,last_done) "
               "VALUES(?,?,?,?,?,?)", (uid(), kind, rid, stage, nd, today))
    db.commit()
    return jsonify({"stage": stage, "next_due": nd, "interval": iv, "result": result})
