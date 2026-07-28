#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""申论范文推荐：按热门话题生成「仿真卷 + 全套参考答案」。

给定资料按真题规格（国考 6000~8000 字 / 四川省考 5000~7000 字，4~6 则）分则生成，
每则都校验字数；总量以 9000 字为硬上限，但绝不丢弃整则材料（宁可长，不可残）。
题目一次生成，参考答案逐题生成并校验字数。

用法:
  python3 gen_essays.py                # 按热门顺序补齐还没生成的话题（默认最多 3 套）
  python3 gen_essays.py 6              # 最多补 6 套
  python3 gen_essays.py --topic 乡村振兴 # 只生成某个话题
  python3 gen_essays.py --list         # 看已生成/待生成
"""
import os, re, sys, json, sqlite3, time
import aiclient

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")

CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
# 模型档位：pro —— 创作：范文/应用文，质量敏感
# 真实模型名不写在这儿：aiclient 负责 档位→模型名 的映射，官方改名时只动 config.json。
TIER = "pro"
_AI = aiclient.conf(TIER, CFG)
AI_BASE, AI_URL, AI_MODEL, AI_KEY = _AI["base"], _AI["url"], _AI["model"], _AI["key"]

META = json.load(open(os.path.join(BASE, "shenlun_meta.json"), encoding="utf-8"))
SPECS = META["specs"]
TYPES = {t["key"]: t for t in META["types"]}

# 热门在前，话题尽量覆盖申论常考主题
TOPICS = [
    ("基层治理", "sichuan"), ("科技创新", "guokao"), ("乡村振兴", "guokao"),
    ("文化自信", "sichuan"), ("生态文明", "guokao"), ("民生保障", "sichuan"),
    ("法治政府", "guokao"), ("营商环境", "sichuan"), ("数字治理", "guokao"),
    ("青年成长", "sichuan"), ("共同富裕", "guokao"), ("城乡融合", "sichuan"),
    # —— 每日更新的话题池：按公考热度铺开，够 --daily 每天补一套跑一个多月 ——
    ("绿色低碳", "guokao"), ("新质生产力", "guokao"), ("以人民为中心", "sichuan"),
    ("诚信建设", "sichuan"), ("工匠精神", "sichuan"), ("志愿服务", "sichuan"),
    ("公共服务", "guokao"), ("社会治理现代化", "guokao"), ("就业优先", "sichuan"),
    ("教育强国", "guokao"), ("健康中国", "sichuan"), ("银发经济", "sichuan"),
    ("消费提振", "guokao"), ("实体经济", "guokao"), ("民营经济", "sichuan"),
    ("粮食安全", "guokao"), ("耕地保护", "sichuan"), ("防返贫", "sichuan"),
    ("非遗传承", "sichuan"), ("文旅融合", "sichuan"), ("人工智能治理", "guokao"),
    ("数据要素", "guokao"), ("社区养老", "sichuan"), ("未成年人保护", "sichuan"),
    ("市场监管", "guokao"), ("政务服务", "sichuan"), ("信用监管", "guokao"),
    ("河湖治理", "sichuan"), ("城市更新", "guokao"), ("安全生产", "sichuan"),
]

SYS = "你是命制过多年申论真题的教研专家，材料真实可信、题目规范、参考答案能拿高分。"

# 给定资料的硬上限：真题规格只是目标，超一点没关系，但不能为了压字数把整则材料砍掉
HARD_MAX = int(os.environ.get("GONGKAO_ESSAY_MAX_WORDS", "9000"))


def _words(t):
    return len(re.sub(r"\s+", "", t or ""))


def ai(messages, max_tokens=4000, temperature=0.6, json_mode=False, retry=2):
    # retries=0：网络重试交给 aiclient，这层只兜 JSON 截断，别让两层重试次数相乘。
    last = None
    for i in range(retry + 1):
        try:
            txt = aiclient.chat(messages, tier=TIER, temperature=temperature,
                                max_tokens=max_tokens, timeout=420, json_mode=json_mode,
                                cfg=CFG, retries=0)
            return json.loads(txt) if json_mode else txt
        except Exception as e:
            last = e
            time.sleep(3 + 4 * i)
    raise last


def fit_words(base_prompt, lo, hi, tries=2, temperature=0.6, target=None):
    """生成一段文字并把字数收进 [lo, hi]。超/欠就带着上一稿让它重写。
    模型对「多少字」很不敏感，只说一次基本管不住，必须实测后返工。"""
    target = target or (lo + int((hi - lo) * 0.35))
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": base_prompt}]
    best = ""
    for _ in range(tries + 1):
        txt = re.sub(r"[*#`]+", "", ai(msgs, max_tokens=max(1500, int(hi * 2.4)),
                                       temperature=temperature)).strip()
        n = _words(txt)
        if lo <= n <= hi:
            return txt
        if not best or abs(n - target) < abs(_words(best) - target):
            best = txt
        how = "扩写到" if n < lo else "压缩到"
        msgs = msgs[:1] + [
            {"role": "user", "content": base_prompt},
            {"role": "assistant", "content": txt},
            {"role": "user", "content": "这一稿 %d 字，不符合要求。请%s %d~%d 字（目标 %d 字），"
                                        "保持内容与结构，只输出正文。" % (n, how, lo, hi, target)}]
    return best


def gen_material(topic, spec, n_passages, per_words, total_words):
    """逐则生成给定资料，凑够真题的总字数。一次生成全部会被 max_tokens 截断。"""
    lo, hi = per_words
    tlo, thi = total_words
    passages, sofar = [], []
    angles = ["现象与成效（具体地区、具体做法、具体数据）",
              "存在的问题与困难（基层声音、群众抱怨）",
              "典型经验（一个县/乡/企业的完整案例，有人物有细节）",
              "专家观点与政策依据（引用文件、学者论述）",
              "他山之石或反面案例（可对比借鉴）",
              "一段讲话或评论（可作为大作文立意来源）"]
    for i in range(n_passages):
        angle = angles[i % len(angles)]
        avoid = ("已经写过的材料主旨：" + "；".join(sofar)) if sofar else ""
        prompt = ("请命制一份申论试卷的「给定资料 %d」，主题：%s。\n"
                  "本则材料的角度：%s\n%s\n"
                  "要求：字数 %d~%d 字（硬性要求，不得超出）；像真题材料那样有具体地名、人名、数据、对话；"
                  "不要出现「材料%d」以外的标题，不要 Markdown 记号，直接输出正文。" %
                  (i + 1, topic, angle, avoid, lo, hi, i + 1))
        txt = fit_words(prompt, lo, hi, temperature=0.75)
        n = _words(txt)
        passages.append(txt)
        sofar.append(txt[:40])
        print("    材料%d：%d 字 %s" % (i + 1, n, "✅" if lo <= n <= hi else "⚠️"), flush=True)

    # 不再丢弃最后一则——材料是一个整体，少一则就残缺了。
    # 单则字数已经收敛过，总量落在真题区间~9000 字之间都可接受。
    total = sum(_words(x) for x in passages)
    if total > HARD_MAX:
        print("    ⚠️ 总量 %d 字超过 %d 字的上限，但保留全部 %d 则（宁可长，不可残）"
              % (total, HARD_MAX, len(passages)), flush=True)
    return "\n\n".join("材料%d\n%s" % (i + 1, t) for i, t in enumerate(passages))


def gen_questions(topic, spec, material):
    n = SPECS[spec]["questions"]
    kinds = (["guina", "zonghe", "duice", "guanche", "zuowen"] if n >= 5
             else ["guina", "zonghe", "guanche", "zuowen"])
    lines = []
    for i, k in enumerate(kinds, 1):
        t = TYPES[k]
        lines.append("第%d题：%s，%d 分，%d~%d 字" % (i, t["name"], t["full"], t["word_min"], t["word_max"]))
    prompt = ("下面是一份申论试卷的给定资料（主题：%s）。请据此命制 %d 道题，题型与分值如下：\n%s\n\n"
              "每道题的 stem 要写成真题的样子：交代作答任务、限定资料范围、写清要求与字数。\n"
              "大作文要给出一句引言（出自材料）并要求自拟题目。\n"
              '只输出 JSON：{"items":[{"seq":1,"qtype":"guina","stem":"...","full":15,"word_min":150,"word_max":200}]}\n\n'
              "【给定资料】\n%s" % (topic, n, "\n".join(lines), material[:12000]))
    d = ai([{"role": "system", "content": SYS}, {"role": "user", "content": prompt}],
           max_tokens=2500, temperature=0.4, json_mode=True)
    out = []
    for it in d.get("items", [])[:n]:
        k = it.get("qtype") if it.get("qtype") in TYPES else kinds[len(out)]
        t = TYPES[k]
        out.append({"seq": len(out) + 1, "qtype": k, "type_name": t["name"],
                    "stem": (it.get("stem") or "").strip(),
                    "full": int(it.get("full") or t["full"]),
                    "word_min": int(it.get("word_min") or t["word_min"]),
                    "word_max": int(it.get("word_max") or t["word_max"])})
    return out


def gen_answer(q, material):
    """参考答案 / 范文，字数严格落在题目要求区间。"""
    is_essay = q["qtype"] == "zuowen"
    lo, hi = q["word_min"], q["word_max"]
    target = lo + int((hi - lo) * 0.35)
    frame = ("按「开头点题—分论点1—分论点2—分论点3—结尾升华」写完整议论文，第一行是自拟标题。"
             if is_essay else "按该题型的规范答案框架分条作答，要点齐全、语言书面化。")
    base = ("请为下面这道申论题写一份能拿满分的参考答案。\n\n【题目】\n%s\n\n【给定资料】\n%s\n\n"
            "%s\n字数 %d~%d 字（硬性要求，写到 %d 字左右；绝不能超过 %d 字）。\n"
            "只输出答案正文：不要 Markdown 记号，不要解释和字数统计。" %
            (q["stem"], material[:12000], frame, lo, hi, target, hi))
    return fit_words(base, lo, hi, tries=3, temperature=0.5, target=target)


def gen_outline(q, answer):
    if q["qtype"] != "zuowen":
        return ""
    prompt = ("下面是一篇申论大作文范文。请用三行提炼它的写作思路：\n"
              "第一行「总论点：…」，第二行「分论点：…／…／…」，第三行「亮点：…」。\n"
              "只输出这三行。\n\n" + answer[:2500])
    try:
        return ai([{"role": "system", "content": SYS}, {"role": "user", "content": prompt}],
                  max_tokens=400, temperature=0.3).strip()
    except Exception:
        return ""


def build_topic(con, topic, spec):
    if con.execute("SELECT 1 FROM essay_papers WHERE topic=?", (topic,)).fetchone():
        print("  「%s」已存在，跳过" % topic)
        return 0
    sp = SPECS[spec]
    lo, hi = sp["material_words"]
    n_pass = sp["passages"][0] + 1                      # 取 5 则，落在 4~6 之间
    per = sp["passage_words"]
    print("→ %s（%s，目标材料 %d~%d 字，%d 则，%d 题）"
          % (topic, sp["name"], lo, hi, n_pass, sp["questions"]), flush=True)

    material = gen_material(topic, spec, n_pass, per, (lo, hi))
    mw = _words(material)
    if lo <= mw <= hi:
        tag = "✅ 符合真题规格"
    elif mw <= HARD_MAX:
        tag = "✅ 略高于规格但在 %d 字以内，可接受" % HARD_MAX
    else:
        tag = "⚠️ 超过 %d 字" % HARD_MAX
    print("  材料合计 %d 字（%d 则）%s" % (mw, n_pass, tag), flush=True)

    qs = gen_questions(topic, spec, material)
    print("  命制 %d 道题" % len(qs), flush=True)

    cur = con.execute("INSERT INTO essay_papers(topic,spec,title,material,words) VALUES(?,?,?,?,?)",
                      (topic, spec, "%s · %s仿真卷" % (topic, sp["name"]), material, mw))
    pid = cur.lastrowid
    for q in qs:
        ans = gen_answer(q, material)
        aw = _words(ans)
        ok = "✅" if q["word_min"] <= aw <= q["word_max"] else "⚠️"
        print("    第%d题 %s 参考答案 %d 字（要求 %d-%d）%s"
              % (q["seq"], q["type_name"], aw, q["word_min"], q["word_max"], ok), flush=True)
        con.execute("INSERT INTO essays(paper_id,seq,qtype,type_name,stem,full,word_min,word_max,"
                    "answer,answer_words,outline) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, q["seq"], q["qtype"], q["type_name"], q["stem"], q["full"],
                     q["word_min"], q["word_max"], ans, aw, gen_outline(q, ans)))
        con.commit()
    con.commit()
    return 1


def main():
    if not AI_KEY:
        sys.exit("未配置 ai_key")
    con = sqlite3.connect(DB, timeout=60)
    have = {r[0] for r in con.execute("SELECT topic FROM essay_papers")}

    if "--list" in sys.argv:
        for t, s in TOPICS:
            print("  %s %-8s %s" % ("✅" if t in have else "⬜", t, SPECS[s]["name"]))
        return
    if "--topic" in sys.argv:
        t = sys.argv[sys.argv.index("--topic") + 1]
        spec = dict(TOPICS).get(t, "guokao")
        build_topic(con, t, spec)
        return

    # 每日更新：定时器每天补一套还没生成的话题（含大作文 + 应用文小题）
    if "--daily" in sys.argv:
        nxt = next(((t, s) for t, s in TOPICS if t not in have), None)
        if not nxt:
            print("话题池已全部生成（%d 套），今天不新增；可在 TOPICS 里补充新话题。" % len(have))
            return
        try:
            build_topic(con, *nxt)
            print("每日范文已更新：%s" % nxt[0])
        except Exception as e:
            print("  ✗ %s 失败：%s" % (nxt[0], e))
        return

    limit = 3
    for a in sys.argv[1:]:
        if a.isdigit():
            limit = int(a)
    n = 0
    for t, spec in TOPICS:
        if n >= limit:
            break
        if t in have:
            continue
        try:
            n += build_topic(con, t, spec)
        except Exception as e:
            print("  ✗ %s 失败：%s" % (t, e))
    print("\n本次新增 %d 套，库内共 %d 套"
          % (n, con.execute("SELECT COUNT(*) FROM essay_papers").fetchone()[0]))


if __name__ == "__main__":
    main()
