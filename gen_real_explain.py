#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给真题补答案和解析（DeepSeek 出、智谱核验）。

**解析存成结构化字段，不存一坨文本。**这是刻意的：官方解析的内容其实不差，
但排版是 PDF 直接拉下来的一整片字，手机上读完一道题要滑三屏、还找不到重点。
拆成「关键 / 步骤 / 错项 / 举一反三」四段之后，前端才能按统一版式排，
一眼扫到「这题卡在哪」，要细看再往下读步骤。

  keypoint  一句话点破这道题卡在哪（最重要，排在最前面）
  steps     解题过程，一步一行（计算题就是算式，推理题就是推导链）
  wrong     每个错误选项错在哪（只列错的，正确项在 steps 里已经讲了）
  tip       同类题下次怎么更快（可选）

三种情况分三条路，代价和风险都不一样：
  · 有官方答案 → 告诉模型答案，只让它写解析。**最安全**，不需要核验。
  · 没有官方答案 → 模型自己作答，再由**另一家模型独立作答**，一致才采纳。
    （drill_bank 的老经验：单模型出题一致率只有 89%，每 9 道就有 1 道值得怀疑）
  · 两个模型答案不一致 → 入库但标 agree=0，**不发给人做**，留着回查。

用法：
    python3 gen_real_explain.py --plan            # 只报要处理多少、不调 AI
    python3 gen_real_explain.py --limit 40        # 先小批试跑，看看解析质量
    python3 gen_real_explain.py                   # 全量（可随时 Ctrl-C，下次接着跑）
    python3 gen_real_explain.py --module 数量关系
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import realbank as R                                       # noqa: E402

DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG = json.load(open(os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json")),
                     encoding="utf-8"))

AI_BASE = (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = CFG.get("ai_model") or "deepseek-chat"
AI_KEY = CFG.get("ai_key") or ""
AUDIT_BASE = (CFG.get("vision_base") or "").rstrip("/")
AUDIT_KEY = CFG.get("vision_key") or ""
AUDIT_MODEL = "glm-4-plus"          # 非推理版：推理版一道要 15~30 秒，核验几千道等不起

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_explains(
    qid INTEGER PRIMARY KEY,
    answer TEXT,                 -- 模型给的答案（题目本来就有官方答案时，这里存官方的）
    src TEXT,                    -- official=答案来自原卷 / ai=模型作答
    module TEXT DEFAULT '',      -- 原卷没分节时，让模型判的模块
    qtype TEXT,                  -- 顺手判的题型（规则法判不出的那 44% 靠这个补）
    keypoint TEXT,               -- 一句话点破关键
    steps TEXT,                  -- JSON 数组：解题步骤，一步一行
    wrong TEXT,                  -- JSON 对象：{"A":"错在哪", ...}，只列错项
    tip TEXT,                    -- 举一反三（可选）
    model TEXT,
    audit_ans TEXT DEFAULT '',   -- 核验模型独立作答的结果
    agree INTEGER DEFAULT 1,     -- 0 = 两个模型答案不一致，**不发给人做**
    flaw TEXT DEFAULT 'ok',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_rex_agree ON real_explains(agree);
"""

_PRINT = threading.Lock()


def _post(url, key, payload, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _url(base):
    """两家的 base 写法不一样，拼错了直接 404，而且 404 会被当成「核验模型没响应」
       静默降级成 unchecked —— 表现是「全部存疑、一道可用的都没有」，很难一眼看出是拼错了 URL。
         DeepSeek: https://api.deepseek.com        → 要补 /v1/chat/completions
         智谱:     .../api/paas/v4                 → 只补 /chat/completions
    """
    if base.endswith("/chat/completions"):
        return base
    if re.search(r"/v\d+$", base):          # 已经带了版本号（/v1、/v4）
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _chat(base, key, model, prompt, system, max_tokens=4096, temperature=0.2, tries=3):
    """跑几千道题的过程里，网络抖动是常态（实测撞到过 SSL UNEXPECTED_EOF）。
       不重试的话，一次抖动就白扔掉 4 道题的生成结果。"""
    url = _url(base)
    last = None
    for k in range(tries):
        try:
            d = _post(url, key, {"model": model, "temperature": temperature,
                                 "max_tokens": max_tokens,
                                 "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": prompt}]})
            return (d["choices"][0]["message"].get("content") or "").strip()
        except Exception as e:
            last = e
            time.sleep(2 * (k + 1))
    raise last


def salvage(rep):
    """JSON 被 max_tokens 截断时，把写完整的那几条捞回来。

    用栈记每层花括号的起点 —— 只盯「深度回到 0」的话，外层那个 `{"items":[` 永远
    等不到它的闭合花括号（就是它被截断的），一条也捞不出来。这个坑在 drill.py 踩过一次。
    """
    out, stack, instr, esc = [], [], False, False
    for i, ch in enumerate(rep):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            try:
                o = json.loads(rep[start:i + 1])
            except Exception:
                continue
            if isinstance(o, dict) and o.get("id") and (o.get("steps") or o.get("keypoint")):
                out.append(o)
    return out


def parse_items(rep):
    try:
        got = json.loads(rep).get("items")
        if isinstance(got, list):
            return got
    except Exception:
        pass
    return salvage(rep)


# ---------------------------------------------------------------- 出解析
SYS = ("你是公考阅卷组的资深讲师，给考生讲真题。讲究三件事："
       "①先点破这道题卡在哪，别绕弯子；②过程一步一步写清楚，计算题要有算式；"
       "③每个错误选项都要说清错在哪（尤其是最容易误选的那个）。"
       "语言口语化、直给，不要套话空话。严格输出 JSON，用简体中文。")

FMT = ('只输出 JSON：{"items":[{"id":题目编号,"module":"模块","qtype":"题型","answer":"A",'
       '"keypoint":"一句话点破关键","steps":["第一步…","第二步…"],'
       '"wrong":{"B":"错在哪","C":"错在哪","D":"错在哪"},"tip":"举一反三（可省）"}]}')

RULES = (
    "【每道题怎么写】\n"
    "· module：模块。只能是这五个之一：常识判断、言语理解与表达、数量关系、判断推理、资料分析。"
    "题目那行已经写了模块的，照抄。\n"
    "· qtype：题型。**只能从该题自己那行「可选题型」里挑一个**，不许跨模块、不许自创。"
    "那行写的是「（模块未知，先判模块再从该模块的题型里挑）」时，"
    "先定 module，再从该模块的题型里选 —— 自己造一个名字等于白判，会被丢掉。\n"
    "· answer：正确选项字母。%s\n"
    "· keypoint：**一句话**（40 字以内）点破这道题的关键或陷阱在哪，"
    "比如「增长率的分母是去年不是今年」「问的是意图不是主旨」。这是考生最先看的一行。\n"
    "· steps：解题过程，**一步一个数组元素**，每步 60 字以内。"
    # 注意这段是 %% —— 整个 RULES 要走 % 格式化，字面量的百分号必须转义
    "计算题要写出算式和数字（如「增长率 =（3.5−3.0）÷3.0 = 16.7%%」）；"
    "推理题要写出推导链；言语题要指出定位到原文哪一句。**别把整段推理挤成一句**。\n"
    "· wrong：每个**错误**选项错在哪，一项一句（正确项不要写进来，steps 里已经讲了）。"
    "要具体到「错在哪个字眼」，别写「不符合文意」这种废话。\n"
    "· tip：同类题下次怎么更快，一句话。想不出就省略。\n\n"
    "【硬要求】\n"
    "1. steps 至少 2 步；只有一步能讲完的题，也要拆成「怎么定位」和「怎么得出」。\n"
    "2. 每个字段都不要用 Markdown 符号（不要 ** 不要 # 不要 -），前端会自己排版。\n"
    "3. 一次把这 %d 道题全写完，**解析写简洁点**，写太长会把输出撑爆、后面的题一道都收不到。\n")


def build_prompt(rows, qtypes):
    body = []
    for i, r in enumerate(rows, 1):
        opts = json.loads(r["options"])
        known = ("（本题原卷给出的正确答案是 %s，直接按这个讲，不要改）" % r["answer"]) \
            if r["answer"] else "（原卷没给答案，请你判断）"
        # 题型清单**按这道题所属的模块给**，不给全表：给全表的话，常识判断的题会被
        # 判成「习近平新时代中国特色社会主义思想」（那是政治理论的题型），归类全乱。
        allow = qtypes.get(r["module"] or "", [])
        body.append("【第 %d 题】%s %s\n可选题型：%s\n题干：%s\n%s"
                    % (i, r["module"] or "（模块未知，先判模块）", known,
                       "、".join(allow) or "（模块未知，先判模块再从该模块的题型里挑）",
                       r["stem"],
                       "\n".join("%s. %s" % ("ABCD"[j], o) for j, o in enumerate(opts))))
    has_ans = any(r["answer"] for r in rows)
    ans_note = ("已给出原卷答案的题，answer 必须照抄，不许改。" if has_ans else
                "没给答案的题请你自己判断，务必反复核对。")
    return ("给下面 %d 道公务员考试真题写解析。\n\n%s\n\n%s\n\n%s"
            % (len(rows), "\n\n".join(body),
               RULES % (ans_note, len(rows)), FMT))


# 解析末尾那句结论里的选项字母：「综上，选 C」「因此正确答案为 B」「共 2 项，选 A」。
_CONCLUDE = re.compile(r"(?:综上|因此|所以|故)[^。]{0,20}?(?:选|答案为?|正确答案是?)\s*[（(【]?([A-D])"
                       r"|(?:选|答案为?|正确答案是?)\s*[（(【]?([A-D])\s*[）)】]?\s*(?:项|选项)?\s*$")


def steps_conclusion(steps):
    """从解题步骤的结论里把字母抠出来 —— 这是**免费的第二意见**。

    模型真的会自己打自己脸：实测有一道题，步骤一条条数下来「正确的有①③，共2项」，
    最后 answer 却填了 B（3项）。步骤是它自己推的，比 answer 字段可信得多，
    两者打架就说明这道题它没想清楚，不能发给人做。
    """
    for s in reversed(steps or []):
        m = _CONCLUDE.search(str(s).strip())
        if m:
            return (m.group(1) or m.group(2) or "").upper()
    return ""


def audit_batch(rows):
    """让另一家模型**独立作答**（绝不告诉它我们的答案，否则会被锚定）。
       返回 {题号: 字母}。核验模型没配或没响应就返回空，调用方按「未核验」处理。"""
    if not AUDIT_KEY or not AUDIT_BASE:
        return {}
    body = []
    for i, r in enumerate(rows, 1):
        opts = json.loads(r["options"])
        body.append("【第 %d 题】%s\n%s" % (i, r["stem"],
                    "\n".join("%s. %s" % ("ABCD"[j], o) for j, o in enumerate(opts))))
    prompt = ("下面是几道公务员考试真题，**不告诉你答案**，请你自己独立做一遍。\n\n%s\n\n"
              '只输出 JSON：{"items":[{"id":1,"answer":"A"}]}' % "\n\n".join(body))
    try:
        rep = _chat(AUDIT_BASE, AUDIT_KEY, AUDIT_MODEL, prompt,
                    "你是公考做题高手，只管作答，不用解释。严格输出 JSON。",
                    max_tokens=800, temperature=0.1)
        return {int(x["id"]): (x.get("answer") or "").strip().upper()[:1]
                for x in parse_items(rep) if str(x.get("id", "")).isdigit()}
    except Exception:
        return {}


def _clean_tag(module, it, qtypes):
    """把模型给的模块/题型**对着白名单校一遍**，对不上就丢掉留空。

    光在提示词里写「只能从清单里挑」是不够的：模块未知的题清单是空的，模型照样
    自己发明「逻辑填空」「主旨概括题」，甚至把模块名（常识判断）当题型填进来。
    留着这些名字，前端「按题型刷」的清单里就会混进一堆对不上专项练的野名字。
    """
    # 只认行测卷面真有的五个模块。qtypes 是从 DRILL_TYPES 建的、含「政治理论」
    # （专项练有这个板块，行测卷面没有），不卡的话模型会把时政题判成政治理论，
    # 回填进 real_questions.module 后，按模块刷的清单里会冒出一个卷面上不存在的桶。
    mod = (module or (it.get("module") or "").strip())
    if mod not in R.MODULES:
        mod = module or ""
    qt = (it.get("qtype") or "").strip()
    if qt not in qtypes.get(mod, []):
        qt = ""
    return mod, qt


def do_batch(rows, qtypes):
    """出一批解析 + 核验。返回可以入库的记录列表。"""
    rep = _chat(AI_BASE, AI_KEY, AI_MODEL, build_prompt(rows, qtypes), SYS)
    got = {int(x["id"]): x for x in parse_items(rep) if str(x.get("id", "")).isdigit()}
    if not got:
        return []

    # 只有「原卷没答案、得靠模型判」的题才需要核验：原卷给了答案的，我们是照着讲的，没有判错的余地。
    # ⚠️ audit_batch 返回的键是**它收到的那个列表里的序号**（1..len(need)），
    #    不是 rows 里的序号 —— 批次里只要有一道自带官方答案、或者模型漏答了一道，
    #    两套序号就错开，拿到的会是**隔壁那道题**的核验答案：本来一致的被判 disagree 白丢，
    #    本来不一致的被判 agree（错答案当成「过了核验」发给人做）。所以必须显式映射回去。
    need = [(i, r) for i, r in enumerate(rows, 1) if i in got and not r["answer"]]
    raw = audit_batch([r for _, r in need]) if need else {}
    audit = {orig: raw.get(k, "") for k, (orig, _) in enumerate(need, 1)}

    out = []
    for i, r in enumerate(rows, 1):
        it = got.get(i)
        if not it:
            continue
        steps = [str(s).strip() for s in (it.get("steps") or []) if str(s).strip()]
        wrong = {k.upper()[:1]: str(v).strip()
                 for k, v in (it.get("wrong") or {}).items() if str(v).strip()}
        ans = (r["answer"] or (it.get("answer") or "")).strip().upper()[:1]
        if ans not in "ABCD" or len(steps) < 1:
            continue
        # 免费的自洽检查：解析步骤自己推出的结论，和 answer 字段对不上就是没想清楚
        concl = steps_conclusion(steps)
        bad_mod, bad_qt = _clean_tag(r["module"], it, qtypes)
        if concl and concl != ans:
            out.append({
                "qid": r["id"], "answer": ans, "src": "ai", "module": bad_mod, "qtype": bad_qt,
                "keypoint": (it.get("keypoint") or "").strip()[:120],
                "steps": json.dumps(steps[:8], ensure_ascii=False),
                "wrong": json.dumps(wrong, ensure_ascii=False),
                "tip": (it.get("tip") or "").strip()[:120],
                "model": AI_MODEL, "audit_ans": concl, "agree": 0, "flaw": "self_contradict",
            })
            continue

        if r["answer"]:
            src, aud, agree, flaw = "official", "", 1, "ok"
        else:
            aud = audit.get(i, "")
            src = "ai"
            if not aud:
                agree, flaw = 0, "unchecked"       # 没核验成功的一律不发给人做
            else:
                agree = 1 if aud == ans else 0
                flaw = "ok" if agree else "disagree"
        out.append({
            "qid": r["id"], "answer": ans, "src": src, "module": bad_mod, "qtype": bad_qt,
            "keypoint": (it.get("keypoint") or "").strip()[:120],
            "steps": json.dumps(steps[:8], ensure_ascii=False),
            "wrong": json.dumps(wrong, ensure_ascii=False),
            "tip": (it.get("tip") or "").strip()[:120],
            "model": AI_MODEL, "audit_ans": aud, "agree": agree, "flaw": flaw,
        })
    return out


# ---------------------------------------------------------------- 只重跑核验
def reaudit(con, workers=6, size=6):
    """把**模型自己作答**的那些题重新核验一遍，不重新生成解析。

    先前 audit_batch 的返回值按错误的下标取用（见 do_batch 里那段注释），
    凡是混合批次或模型漏答的批次，拿到的都是隔壁题的核验答案。生成很贵、核验很便宜，
    所以只重跑核验：既能把被冤枉的题（假 disagree）放出来，
    也能把混进来的错答案（假 agree）挡回去。
    """
    rows = con.execute(
        "SELECT e.qid, e.answer, q.stem, q.options FROM real_explains e "
        "JOIN real_questions q ON q.id=e.qid "
        "WHERE e.src='ai' AND e.flaw<>'self_contradict'").fetchall()
    print("要重新核验 %d 道（模型自己作答的）" % len(rows))
    if not rows:
        return
    batches = [rows[i:i + size] for i in range(0, len(rows), size)]
    t0, done, flip = time.time(), 0, [0, 0]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(audit_batch, b): b for b in batches}
        for f in as_completed(futs):
            b = futs[f]
            done += 1
            try:
                got = f.result()
            except Exception:
                continue
            for k, r in enumerate(b, 1):
                aud = got.get(k, "")
                if not aud:
                    continue
                agree = 1 if aud == (r["answer"] or "") else 0
                cur = con.execute("SELECT agree FROM real_explains WHERE qid=?",
                                  (r["qid"],)).fetchone()["agree"]
                if cur != agree:
                    flip[agree] += 1          # flip[1]=被放出来的, flip[0]=被挡回去的
                con.execute("UPDATE real_explains SET audit_ans=?, agree=?, flaw=? WHERE qid=?",
                            (aud, agree, "ok" if agree else "disagree", r["qid"]))
            con.commit()
            if done % 20 == 0 or done == len(batches):
                el = time.time() - t0
                print("  [%d/%d 批] 纠正：放出 %d、挡回 %d，已跑 %.1f 分钟，还要约 %.1f 分钟"
                      % (done, len(batches), flip[1], flip[0], el / 60,
                         el / max(1, done) * (len(batches) - done) / 60))
    print("完成：原判错的共 %d 道（放出 %d、挡回 %d）" % (flip[0] + flip[1], flip[1], flip[0]))


# ---------------------------------------------------------------- 主流程
def pick(con, module, limit, redo):
    """挑要处理的题：可练（不依赖图/材料）、还没生成过的。"""
    where = ["q.needs_asset=0", "LENGTH(q.stem)>=10"]
    args = []
    if not redo:
        where.append("e.qid IS NULL")
    if module:
        where.append("q.module=?")
        args.append(module)
    sql = ("SELECT q.id, q.module, q.stem, q.options, q.answer FROM real_questions q "
           "LEFT JOIN real_explains e ON e.qid=q.id WHERE " + " AND ".join(where) +
           " ORDER BY q.has_answer, q.id")     # 没答案的排前面：它们最缺
    if limit:
        sql += " LIMIT %d" % limit
    return con.execute(sql, args).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="只处理前 N 道（先试跑）")
    ap.add_argument("--module", help="只处理这个模块")
    ap.add_argument("--batch", type=int, default=4, help="每次 AI 调用出几道（默认 4）")
    ap.add_argument("--workers", type=int, default=6, help="并发数（默认 6）")
    ap.add_argument("--redo", action="store_true", help="已生成过的也重做")
    ap.add_argument("--plan", action="store_true", help="只报数量，不调 AI")
    ap.add_argument("--reaudit", action="store_true",
                    help="不生成解析，只把已入库的 AI 作答重新核验一遍（修下标错位用）")
    a = ap.parse_args()

    if not AI_KEY:
        raise SystemExit("config.json 里没有 ai_key")
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)

    if a.reaudit:
        reaudit(con, a.workers)
        con.close()
        return

    rows = pick(con, a.module, a.limit, a.redo)
    n_noans = sum(1 for r in rows if not r["answer"])
    print("待处理 %d 道（其中 %d 道原卷没答案、需要模型作答并核验）"
          % (len(rows), n_noans))
    if a.plan or not rows:
        calls = (len(rows) + a.batch - 1) // a.batch
        print("预计 AI 调用：出解析 %d 次 + 核验约 %d 次"
              % (calls, (n_noans + 5) // 6))
        return

    from mods.drill import DRILL_TYPES
    qtypes = {b: [t[0] for t in ts] for b, ts in DRILL_TYPES.items()}
    # 常识判断的卷面里混着大量时政/理论题，光给常识那七类会硬塞进不合适的桶
    qtypes["常识判断"] = qtypes.get("常识判断", []) + qtypes.get("政治理论", [])

    batches = [rows[i:i + a.batch] for i in range(0, len(rows), a.batch)]
    t0, done, ok, bad = time.time(), 0, 0, 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(do_batch, b, qtypes): b for b in batches}
        for f in as_completed(futs):
            done += 1
            try:
                recs = f.result()
            except Exception as e:
                with _PRINT:
                    print("  [%d/%d] 批次出错：%s" % (done, len(batches), str(e)[:90]))
                continue
            for rec in recs:
                con.execute(
                    "INSERT OR REPLACE INTO real_explains(qid,answer,src,module,qtype,keypoint,"
                    "steps,wrong,tip,model,audit_ans,agree,flaw) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec["qid"], rec["answer"], rec["src"], rec["module"], rec["qtype"],
                     rec["keypoint"],
                     rec["steps"], rec["wrong"], rec["tip"], rec["model"],
                     rec["audit_ans"], rec["agree"], rec["flaw"]))
                ok += rec["agree"]
                bad += 1 - rec["agree"]
            con.commit()
            if done % 10 == 0 or done == len(batches):
                el = time.time() - t0
                with _PRINT:
                    print("  [%d/%d 批] 可用 %d、存疑 %d，已跑 %.1f 分钟，预计还要 %.1f 分钟"
                          % (done, len(batches), ok, bad, el / 60,
                             el / max(1, done) * (len(batches) - done) / 60))
    print("\n完成：可用 %d 道、存疑 %d 道（存疑的不发给人做，留着回查），耗时 %.1f 分钟"
          % (ok, bad, (time.time() - t0) / 60))
    con.close()


if __name__ == "__main__":
    main()
