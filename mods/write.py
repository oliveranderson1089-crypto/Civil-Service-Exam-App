"""成文：素材 → 大作文（生成逻辑，无路由）。

素材背了不会用，等于没背。这里把散落在各库的素材真正拼成一篇能交卷的大作文。

这块没有自己的路由，是被 app.py 的写作接口调的生成逻辑（_write_gen / _e_row）。
拆出来是为了让 app.py 少 300 行，依赖仍单向：app.py → mods/write。
"""
import json
import re

from flask import jsonify

from core import log
from mods.ai import _ai_call_or_error
from mods.align import align


WRITE_MIN, WRITE_MAX = 1000, 1200      # 省考大作文常规字数

# 政治理论和常考提法**不是按天更新的**（都是一次性铺进去的），
# 所以它们不能按日期取——要按当天素材的话题去检索，这样每篇都用得上。
_STOP = set(["我们", "他们", "这个", "那个", "一个", "可以", "因为", "所以", "如果", "需要",
             "进行", "具有", "成为", "不断", "更加", "已经", "以及", "其中", "这样", "通过",
             "实现", "称号", "荣获", "表示", "指出", "以来", "以后", "同时", "但是", "而且"])


def _kw_of(sucai, news, n=8):
    """抠出检索用的关键词，拿去政治理论/常考提法里捞相关内容。

    首选素材自带的 topic 标签（「创新·实干」「奉献·为民」这种，是人工归好类的，干净）；
    不够再从正文里补高频词——但正文里抠出来的多半是「通过」「实现」这类虚词，捞不到东西，
    所以只当补充，且过一遍停用词。"""
    kws = []
    for x in sucai:
        for w in re.split(r"[·、,，/]", x.get("topic") or ""):
            w = w.strip()
            if 2 <= len(w) <= 6 and w not in kws:
                kws.append(w)
    if len(kws) >= 4:
        return kws[:n]
    cnt = {}
    for t in [x.get("content") or "" for x in sucai] + [x.get("title") or "" for x in news]:
        for w in re.findall(r"[一-龥]{2,4}", t):
            if w in _STOP:
                continue
            cnt[w] = cnt.get(w, 0) + 1
    for w, _ in sorted(cnt.items(), key=lambda x: -x[1]):
        if w not in kws:
            kws.append(w)
        if len(kws) >= n:
            break
    return kws


def _like_any(db, sql, kws, cols, limit):
    """按关键词 OR LIKE 去某张表捞素材；一个都没命中就退回默认取法。"""
    if not kws:
        return []
    where = " OR ".join("(%s)" % " OR ".join("%s LIKE ?" % c for c in cols) for _ in kws)
    args = []
    for k in kws:
        args += ["%" + k + "%"] * len(cols)
    return db.execute(sql % where + " LIMIT %d" % limit, args).fetchall()


def _write_pool(db, date):
    """凑齐一天的素材池。date=None 表示综合应用（不限日期，跨全库挑）。"""
    p = {"date": date, "sucai": [], "lianjie": [], "gaikuo": [], "xiyu": [],
         "theory": [], "tifa": [], "idiom": [], "news": []}
    if date:
        rows = db.execute("SELECT kind,topic,content FROM sucai_items WHERE date=? ORDER BY id",
                          (date,)).fetchall()
        for r in rows:
            (p["lianjie"] if r["kind"] == "衔接表达" else p["sucai"]).append(dict(r))
        p["gaikuo"] = [dict(r) for r in db.execute(
            "SELECT topic,sentence FROM gaikuo_items WHERE date=? LIMIT 6", (date,))]
        p["xiyu"] = [dict(r) for r in db.execute(
            "SELECT category,quote,note FROM xiyu_items WHERE date=? LIMIT 6", (date,))]
        p["news"] = [dict(r) for r in db.execute(
            "SELECT title,ai_summary FROM news_items WHERE date(created_at)=? LIMIT 8", (date,))]
    else:
        # 综合应用：素材不限日期，但优先近期（AI 自己选题，选材范围要够宽）
        p["sucai"] = [dict(r) for r in db.execute(
            "SELECT kind,topic,content FROM sucai_items WHERE kind!='衔接表达' "
            "ORDER BY date DESC LIMIT 40")]
        p["lianjie"] = [dict(r) for r in db.execute(
            "SELECT kind,topic,content FROM sucai_items WHERE kind='衔接表达' "
            "ORDER BY RANDOM() LIMIT 14")]
        p["xiyu"] = [dict(r) for r in db.execute(
            "SELECT category,quote,note FROM xiyu_items ORDER BY date DESC LIMIT 10")]
        p["news"] = [dict(r) for r in db.execute(
            "SELECT title,ai_summary FROM news_items ORDER BY id DESC LIMIT 12")]

    kws = _kw_of(p["sucai"], p["news"])
    p["kws"] = kws
    th = _like_any(db, "SELECT board,topic,title,content FROM theory_items WHERE %s", kws,
                   ["topic", "title", "content"], 6)
    if not th:
        th = db.execute("SELECT board,topic,title,content FROM theory_items "
                        "ORDER BY RANDOM() LIMIT 4").fetchall()
    p["theory"] = [dict(r) for r in th]
    tf = _like_any(db, "SELECT title,content FROM changkao_items WHERE board='提法' AND (%s)", kws,
                   ["title", "content"], 6)
    if not tf:
        tf = db.execute("SELECT title,content FROM changkao_items WHERE board='提法' "
                        "ORDER BY RANDOM() LIMIT 4").fetchall()
    p["tifa"] = [dict(r) for r in tf]
    p["idiom"] = [dict(r) for r in db.execute(
        "SELECT title,content FROM changkao_items WHERE board='成语' "
        "ORDER BY freq DESC LIMIT 12")]
    return p


def _pool_text(p):
    """素材池 → 喂给 AI 的清单。每条都编号，写完要报告用了哪几条，好核对。"""
    L, idx = [], []

    def sec(name, items, fmt):
        if not items:
            return
        L.append("【%s】" % name)
        for it in items:
            n = len(idx) + 1
            idx.append((name, fmt(it)))
            L.append("%d. %s" % (n, fmt(it)))
        L.append("")

    sec("人物事例/具体事例/理论论据", p["sucai"],
        lambda x: "（%s·%s）%s" % (x.get("kind") or "", x.get("topic") or "", x["content"]))
    sec("衔接表达（写作时必须用上，不要自己造口语过渡）", p["lianjie"], lambda x: x["content"])
    sec("政治理论（行测·理论基础）", p["theory"],
        lambda x: "（%s）%s：%s" % (x.get("board") or "", x.get("title") or "", x.get("content") or ""))
    sec("常考提法", p["tifa"], lambda x: "%s：%s" % (x.get("title") or "", x.get("content") or ""))
    sec("高频成语（用在恰当处，别堆砌）", p["idiom"],
        lambda x: "%s：%s" % (x.get("title") or "", (x.get("content") or "")[:40]))
    sec("规范概括句", p["gaikuo"], lambda x: x.get("sentence") or "")
    sec("金句（习语/权威表述）", p["xiyu"], lambda x: x.get("quote") or "")
    sec("当日时政（可作背景，不必强用）", p["news"], lambda x: x.get("title") or "")
    return "\n".join(L), idx


def _used_hit(item, content):
    """AI 报的「我用了这条素材」到底是不是真的？逐条回正文里核对。
       它很爱把没用上的也报进来（实测 24 条里有 4 条是虚报的），这个清单是给人回查素材用的，
       有水分就没意义了 —— 宁可少列，不能列错。"""
    t = (item or "").strip()
    if not t:
        return False
    if "…" in t:                       # 衔接表达是带省略号的模板：拆成骨架片段，一半以上出现才算用了
        frag = [x for x in re.split(r"…+", re.sub(r"[（(].*?[)）]", "", t)) if len(x.strip()) >= 2]
        if not frag:
            return False
        hit = sum(1 for f in frag if f.strip(" ，,。.、—-") and f.strip(" ，,。.、—-") in content)
        return hit * 2 >= len(frag)
    head = t.split("：")[0].strip("（）() ")   # 成语/提法：词本身出现即可
    if 2 <= len(head) <= 8 and "：" in t:
        return head in content
    body = re.sub(r"^[（(].*?[)）]", "", t)   # 事例/金句：里面任意一个 4 字以上的实词短语出现
    return any(x in content for x in re.findall(r"[一-龥]{4,12}", body))


def _write_lack(p, content):
    """检查「综合运用」的硬指标到底达没达标 —— 模型对「必须用上 N 条」极不敏感，
       光在提示词里说一遍它就照抄要求、该不用还是不用（字数也是同一个毛病）。
       所以生成完要真去数，缺什么就回头让它补什么。

       ⚠️ 缺项里**必须把候选原文摆出来**：只说「要用 2~3 个成语」，它得回头自己去几十条池子里翻，
       实测就是不翻；把「就用这几个」摆到面前，它才会用。"""
    need = []
    n_ex = sum(1 for x in p["sucai"] if _used_hit(
        "（%s·%s）%s" % (x.get("kind") or "", x.get("topic") or "", x["content"]), content))
    if n_ex < 3:
        need.append("事例只用了 %d 条，至少要 3 条，且分散在三个分论点里" % n_ex)
    n_th = sum(1 for x in p["theory"] + p["tifa"]
               if (x.get("title") or "") and x["title"] in content)
    if n_th < 2:
        cand = [x["title"] for x in (p["tifa"] + p["theory"]) if x.get("title")][:5]
        need.append("政治理论/常考提法只用了 %d 条，至少要 2 条（支撑分论点的道理，不是贴标签）。"
                    "从这些里挑：%s" % (n_th, "、".join(cand)))
    n_jj = sum(1 for x in p["xiyu"] if (x.get("quote") or "")[:12] in content)
    if not n_jj and p["xiyu"]:
        cand = [x["quote"] for x in p["xiyu"] if x.get("quote")][:3]
        need.append("一句金句都没用，开头或结尾至少原样引 1 句。就从这几句里挑：\n  - "
                    + "\n  - ".join(cand))
    # 成语只要求「至少用上 1 个」：申论大作文堆成语反而扣分，用对一个就够了。
    # （初始提示词里仍写「2~3 个」引导，但检查不卡这个数，免得为了凑数多跑一轮重写。）
    n_id = sum(1 for x in p["idiom"] if x["title"] in content)
    if n_id < 1:
        cand = [x["title"] for x in p["idiom"]][:8]
        need.append("一个成语都没用，恰当处用上 1~3 个（别堆砌）。就从这些里挑：%s" % "、".join(cand))
    w = len(re.sub(r"\s", "", content))
    if w < WRITE_MIN:
        need.append("字数只有 %d，要写到 %d~%d" % (w, WRITE_MIN, WRITE_MAX))
    elif w > WRITE_MAX + 80:
        need.append("字数 %d 超了，压到 %d~%d" % (w, WRITE_MIN, WRITE_MAX))
    return need


_DIR_MIN = 5     # 一个方向至少要有这么多素材才够写成一篇（低于此的算冷门方向，先不轮到）


def _compose_dirs(db, p, n_hist=40, n_out=4):
    """给「综合应用」按方向轮换配题：谁最久没写过就先写谁，实现各方向公平分配。

       之前每期都收敛到「创新 / 高质量发展」——池子里创新素材最多、提示词又拿科技创新举例，
       模型每次输入几乎一样，就每次都挑同一个最安全的题。这里不排斥任何老方向，而是排一个队：
         · 候选 = 全库素材够料（≥_DIR_MIN 条）的所有方向——新素材带出的新方向会自动进来，
           老方向（创新/发展等）也一直在队里，不会被永久踢掉；
         · 排序按「上一次写它是哪天」，从没写过的排最前，写过的越久越靠前——
           轮到谁就写谁，创新只是暂时沉底，等别的方向都轮过一遍自然回到前面。
       再把靠前几个方向的素材补进池子，保证换了方向也有东西可写。

       返回 (dirs, recent)：dirs 是本期优先方向（越靠前越久没写），recent 是最近几期已写话题。"""
    hist = [((r[0] or "").strip(), r[1]) for r in db.execute(   # [(topic, date), ...] 近 n_hist 期
        "SELECT topic, date FROM daily_essays WHERE mode='compose' ORDER BY date DESC LIMIT ?",
        (n_hist,))]
    recent = [t for t, _ in hist[:8]]
    # 全库素材够料的方向（按 topic 标签词频，和 _kw_of 同一套分隔符）。随素材增减自动变。
    cnt = {}
    for r in db.execute("SELECT topic FROM sucai_items WHERE kind!='衔接表达'"):
        for w in re.split(r"[·、,，/]", r[0] or ""):
            w = w.strip()
            if 2 <= len(w) <= 4:
                cnt[w] = cnt.get(w, 0) + 1
    cand = [(w, c) for w, c in cnt.items() if c >= _DIR_MIN]

    def last_used(w):   # 该方向上一次被写的日期（子串命中即算写过）；从没写过→空串，排最前
        ds = [d for t, d in hist if w in t]
        return max(ds) if ds else ""

    # 轮换排序：最久没写的在前；同样久的，素材多的优先（能写得更实在）。
    dirs = [w for w, _ in sorted(cand, key=lambda wc: (last_used(wc[0]), -wc[1]))][:n_out]
    # 补料：把靠前几个方向的素材塞进池子，保证轮到冷门方向也有得写；按 (kind,content) 去重。
    if dirs:
        have = {(x.get("kind"), x.get("content")) for x in p["sucai"]}
        for w in dirs:
            for r in db.execute(
                "SELECT kind,topic,content FROM sucai_items "
                "WHERE kind!='衔接表达' AND topic LIKE ? ORDER BY date DESC LIMIT 4",
                ("%" + w + "%",)):
                key = (r["kind"], r["content"])
                if key not in have:
                    have.add(key)
                    p["sucai"].append(dict(r))
    return dirs, recent


def _write_gen(db, mode, date):
    """生成一篇。返回 (essay_dict, None) 或 (None, (json, code))。"""
    p = _write_pool(db, date if mode == "daily" else None)
    if mode == "daily" and not p["sucai"] and not p["lianjie"]:
        return None, (jsonify({"error": "这一天没有素材，写不了"}), 400)

    if mode == "daily":
        head = ("下面是 %s 这一天更新的备考素材。请**只用这些素材**，写一篇申论大作文。\n"
                "立意从素材里长出来——先看这批素材共同指向什么问题，再定题目，"
                "不要硬凑一个宏大题目再往里塞素材。\n" % date)
    else:
        dirs, recent = _compose_dirs(db, p)   # 会把优先方向的素材补进 p["sucai"]，须在 _pool_text 前调
        rec_hint = "、".join(dict.fromkeys(t for t in recent[:5] if t)) or "创新、高质量发展"
        cand_hint = "、".join(dirs) if dirs else "为民、奉献、担当、坚守"
        head = ("下面是素材库里挑出来的一批素材（跨越多日）。请从中选一个方向，写一篇申论大作文。\n"
                "为了让各方向轮流覆盖、不天天写同一个题，这一期请**优先从下面这几个"
                "最久没写过的方向里挑一个**（越靠前越该写，挑你素材最足、最能写好的）：%s。\n"
                "最近几期已经写过「%s」，尽量别再挑这些重复；但只要素材撑得住、和上面方向不重复，"
                "另选省考真考方向（基层治理、乡村振兴、文化自信、民生保障、法治建设等）也行。\n"
                "选定后从素材里挑真正用得上的写，用不上的别硬塞。\n" % (cand_hint, rec_hint))

    pool, idx = _pool_text(p)

    prompt = (head + "\n" + pool + "\n\n"
              "【要求】\n"
              "1. 标题：8~16 字，观点鲜明，不要「浅谈」「论」这种套话开头。\n"
              "2. 结构：开头（引材料+亮总论点）→ 三个分论点（每段：分论点句+素材论证+回扣）→ 结尾升华。\n"
              "   ⚠️ **outline 里的每一句，必须在正文里逐字找得到**，这是硬要求：\n"
              "   · 分论点句**原样当那一段的第一句**——不许拿名句、古语、衔接表达开头再绕回论点，\n"
              "     那样读的人对着提纲在正文里一句都对不上，提纲就废了；\n"
              "   · 总论点句原样出现在开头段（一般是最后一句）。\n"
              "   写完请自己回头核一遍：提纲那 4 句，是不是都能在正文里原样找到。\n"
              "3. 每个分论点段**必须实打实用上面素材里的事例或理论**，写清是谁、做了什么、说明什么；"
              "不要写「某地某人」这种空壳。\n"
              "4. 段落之间**必须使用上面给的衔接表达**，不要自己造「首先其次最后」这种口水过渡。\n"
              "5. **各类素材都要用上**（这是「综合运用」的硬指标，不许只挑事例和衔接表达省事）：\n"
              "   · 事例（人物/具体）≥3 条，且分散在三个分论点里，不要堆在一段\n"
              "   · 政治理论 或 常考提法 ≥2 条，用来支撑分论点的道理，不是贴标签\n"
              "   · 金句（习语/权威表述）≥1 条，放在开头或结尾\n"
              "   · 高频成语 2~3 个，用在恰当处，别堆砌\n"
              "6. 字数 %d~%d 字，**必须达标**（这是评分硬指标）。\n"
              "7. 正文用 \\n 分段，不要 markdown 标记、不要小标题、不要「分论点一」这种标签。\n\n"
              "只输出 JSON：\n"
              '{"title":"","topic":"话题标签，4~8字","outline":["总论点","分论点1","分论点2","分论点3"],'
              '"content":"正文全文","used":[序号,...],"note":"一句话说明为什么这么选材"}\n'
              "used 里填你**真正用进文章**的素材序号（就是上面每条前面的数字），没用的别写。"
              % (WRITE_MIN, WRITE_MAX))

    rep, err = _ai_call_or_error(
        [{"role": "system", "content": "你是申论阅卷组的范文作者。文章要能直接当范文用："
                                       "论点立得住、素材是真的、衔接不生硬、字数达标。严格输出 JSON。"},
         {"role": "user", "content": prompt}],
        temperature=0.6, max_tokens=4000, timeout=300, json_mode=True)
    if err:
        return None, err
    try:
        d = json.loads(rep)
    except Exception:
        return None, (jsonify({"error": "AI 返回格式异常，请重试"}), 502)

    content = (d.get("content") or "").strip()
    if not content:
        return None, (jsonify({"error": "AI 没写出正文，请重试"}), 502)

    # 数一遍「综合运用」的硬指标。缺了就把缺项（连同候选原文）摆到它面前让它补。
    # 最多补两轮：一轮通常能把理论/提法补进去，第二轮才轮到金句和成语；再补就是浪费调用了。
    for _ in range(2):
        lack = _write_lack(p, content)
        if not lack:
            break
        fix, ferr = _ai_call_or_error(
            [{"role": "system", "content": "你是申论阅卷组的范文作者。严格输出 JSON。"},
             {"role": "user", "content":
              "这是你刚写的文章，还差几处没达标：\n· " + "\n· ".join(lack) +
              "\n\n【可用素材】（还是这些，序号不变）\n" + pool +
              "\n\n【你的文章】\n" + content +
              "\n\n请在**不打乱原有结构和论点**的前提下改好上面每一条：该补的素材织进对应段落里"
              "（要自然，不是硬贴一句）。\n"
              "⚠️ **每段的第一句（分论点句）和开头段的总论点句，一个字都不许动、不许换位置**——"
              "补素材时最容易顺手把段首改成新引的名句，一改提纲就对不上正文了。\n"
              "⚠️ 补内容会撑长篇幅——**补一句就删一句冗余的**，全文仍要控制在 %d~%d 字，"
              "不许为了塞素材把字数写超。\n"
              '只输出 JSON：{"content":"改好的正文全文","used":[序号,...]}'
              % (WRITE_MIN, WRITE_MAX)}],
            temperature=0.5, max_tokens=4000, timeout=300, json_mode=True)
        if ferr:
            break
        try:
            f = json.loads(fix)
            c2 = (f.get("content") or "").strip()
        except Exception:
            break
        if not c2 or len(_write_lack(p, c2)) >= len(lack):
            break                       # 没改好就别越改越乱，保住上一版
        content, d["used"] = c2, f.get("used") or d.get("used")

    # 提纲和正文对齐。**必须在这儿、在补素材循环之后**——那个循环只回写 content 不回写 outline，
    # 补一轮正文就和提纲差一轮，这正是「提纲的分论点在正文里找不到」的根子。
    # 提示词里已经硬要求过一遍了，但模型对这种结构性要求一贯不敏感，所以入库前真去核一遍。
    outline = d.get("outline") or []
    content, outline, arep = align(content, outline)

    words = len(re.sub(r"\s", "", content))

    # 「用了哪些素材」——**能自己数出来的就别问 AI**。
    # AI 自报这份清单两头都不靠谱：会把没用的报上来（虚报），也会用了不报（漏报，实测正文里
    # 明明有提法和成语，它一个都不提）。所以：
    #   · 成语/提法/理论/金句/概括句/衔接表达 —— 词或句子是确定的，直接回正文里扫，谁在就是谁
    #   · 事例 —— 只能靠 AI 指认（它是被改写着用进去的，没法精确匹配），但仍要过一遍核对
    ai_used = set()
    for i in (d.get("used") or []):
        try:
            ai_used.add(int(i) - 1)
        except Exception:
            log.debug("used 里有非法序号，已跳过", exc_info=True)
    used = []
    for k, (sec, text) in enumerate(idx):
        fuzzy = sec.startswith("人物事例")          # 事例这一档没法精确匹配
        if fuzzy and k not in ai_used:
            continue
        if _used_hit(text, content):
            used.append({"sec": sec, "text": text})
    e = {"mode": mode, "date": date, "topic": (d.get("topic") or "").strip(),
         "title": (d.get("title") or "").strip(),
         "outline": json.dumps(outline, ensure_ascii=False),
         "content": content, "words": words,
         "used": json.dumps(used, ensure_ascii=False), "note": (d.get("note") or "").strip(),
         "align": json.dumps(arep.get("items") or [], ensure_ascii=False)}
    db.execute("INSERT OR REPLACE INTO daily_essays"
               "(id,mode,date,topic,title,outline,content,words,used,note,align) VALUES("
               "(SELECT id FROM daily_essays WHERE mode=? AND date=?),?,?,?,?,?,?,?,?,?,?)",
               (mode, date, mode, date, e["topic"], e["title"], e["outline"],
                e["content"], e["words"], e["used"], e["note"], e["align"]))
    db.commit()
    e["id"] = db.execute("SELECT id FROM daily_essays WHERE mode=? AND date=?",
                         (mode, date)).fetchone()[0]
    return e, None


def _e_row(r):
    d = dict(r)
    # align：议论文的「提纲 ↔ 正文」对照（提纲每条落在哪段、正文里的原句是哪句），见 mods/align
    for k in ("outline", "used", "align"):   # 应用文的 outline 存的是逐段批注 segs
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    try:
        d["spec"] = json.loads(d.get("spec") or "{}")
    except Exception:
        d["spec"] = {}
    return d
