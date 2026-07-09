#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常考模块 + 上位词积累 内容生成器（DeepSeek）。
用法:
  python3 gen_changkao.py seed          # 一次性：成语/实词/常识/提法 四个板块 + 上位词
  python3 gen_changkao.py seed 成语     # 只生成某板块（成语|实词|常识|提法|上位词）
  python3 gen_changkao.py hyper 30      # 追加 30 组上位词（避开已有）
写入 changkao_items(UNIQUE(board,title)) 与 hyper_items(UNIQUE(hyper))，幂等去重。
"""
import os, sys, json, sqlite3, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG_PATH = os.environ.get("GONGKAO_CONFIG", os.path.join(BASE, "config.json"))
os.environ.setdefault("NO_PROXY", "*")

CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
AI_BASE = (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = CFG.get("ai_model") or "deepseek-chat"
AI_KEY = CFG.get("ai_key") or os.environ.get("GONGKAO_AI_KEY", "")
AI_URL = AI_BASE if AI_BASE.endswith("/chat/completions") else (
    AI_BASE + "/chat/completions" if AI_BASE.endswith("/v1") else AI_BASE + "/v1/chat/completions")


def ai(messages, max_tokens=6000, temperature=0.4, retry=2):
    payload = {"model": AI_MODEL, "temperature": temperature, "max_tokens": max_tokens,
               "messages": messages, "response_format": {"type": "json_object"}}
    last = None
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Authorization": "Bearer " + AI_KEY,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            return json.loads(j["choices"][0]["message"]["content"])
        except Exception as e:          # 截断/网络抖动 → 重试
            last = e
            time.sleep(3 + 3 * i)
    raise last


SYS = "你是深耕公务员考试十余年的教研老师，只输出考试真正高频的内容，表述精准、不注水。"

BOARD_PROMPT = {
    "成语": ("列出国考/省考「逻辑填空」近十年出现频次最高的成语 60 个。\n"
             "输出 JSON：{\"items\":[{\"title\":\"成语\",\"content\":\"释义（20字内）\","
             "\"note\":\"考点提示：易混成语辨析或常见搭配，30字内\"}]}\n"
             "要求：优先收录反复考查且考生易错的；note 里如有易混词请写出对比。"),
    "实词": ("列出国考/省考「逻辑填空」近十年出现频次最高的实词（含双音节动词、形容词、名词）60 个。\n"
             "输出 JSON：{\"items\":[{\"title\":\"实词\",\"content\":\"释义与词义侧重（25字内）\","
             "\"note\":\"固定搭配 / 与近义词的差别，30字内\"}]}"),
    "常识": ("列出行测「常识判断」近十年反复出现的高频考点 60 条，覆盖政治、法律、人文、科技、地理、经济。\n"
             "输出 JSON：{\"items\":[{\"title\":\"考点名（12字内）\",\"content\":\"考点内容（50字内，直接给结论）\","
             "\"note\":\"命题角度或易错点（30字内）\"}]}"),
    "提法": ("列出当前（2025—2026）时政与申论写作中必须掌握的高频新提法/规范表述 50 条，"
             "例如新质生产力、乡村振兴战略、粤港澳大湾区、中国式现代化、全过程人民民主等。\n"
             "输出 JSON：{\"items\":[{\"title\":\"提法\",\"content\":\"权威内涵（45字内）\","
             "\"note\":\"申论里用在什么主题、怎么用（30字内）\"}]}\n"
             "要求：只收录党的十九大以来、尤其是二十大及其后中央文件里的规范表述。"),
}


def save_ck(con, board, items):
    n = 0
    for it in items:
        t = (it.get("title") or "").strip()
        if not t:
            continue
        cur = con.execute("INSERT OR IGNORE INTO changkao_items(board,title,content,note) VALUES(?,?,?,?)",
                          (board, t, (it.get("content") or "").strip(), (it.get("note") or "").strip()))
        n += cur.rowcount
    con.commit()
    return n


def seed_board(con, board):
    have = con.execute("SELECT COUNT(*) FROM changkao_items WHERE board=?", (board,)).fetchone()[0]
    if have >= 40:
        print("  %s 已有 %d 条，跳过" % (board, have))
        return
    d = ai([{"role": "system", "content": SYS}, {"role": "user", "content": BOARD_PROMPT[board]}])
    n = save_ck(con, board, d.get("items") or [])
    print("  %s +%d 条" % (board, n))


HYPER_PROMPT = (
    "公考「逻辑填空」的上位词（概括词）提示：题干里出现一个**类别名词**，"
    "空格处要填的词必须是这个类别下的**具体成员**（下位词），或与这些成员同类。\n\n"
    "【正确示范】\n"
    "  hyper=戏曲，subs=京剧、越剧、黄梅戏、豫剧、评剧、昆曲、川剧、秦腔\n"
    "  hyper=文房四宝，subs=笔、墨、纸、砚\n"
    "  hyper=民族乐器，subs=二胡、琵琶、古筝、笛子、唢呐、编钟、箜篌\n"
    "  hyper=传统节日，subs=春节、元宵、清明、端午、七夕、中秋、重阳\n"
    "  hyper=非物质文化遗产，subs=剪纸、皮影戏、昆曲、书法、二十四节气、太极拳\n\n"
    "【严禁】\n"
    "  ✗ 抽象属性维度：质量、程度、频率、重要性、系统性、准确性…\n"
    "  ✗ 把形容词当下位词：质量→优、劣、高、低（错！这些是修饰词不是种类）\n"
    "  ✗ 单字下位词（除非像「文房四宝→笔墨纸砚」这种固定成组的）\n\n"
    "hyper 必须是一个**可数的类别名词**（能说「一种××」），subs 必须是该类别下真实存在的**具体事物名称**。\n"
    "优先收录人文常识/科技/自然/社会类里公考真题常出现的类别。\n\n"
    "请给出 %d 组。%s\n"
    '输出 JSON：{"items":[{"hyper":"类别名词","subs":"具体成员，顿号分隔6~10个",'
    '"note":"题干出现这个类别词时，答案要选什么样的词（40字内）",'
    '"example":"含 ____ 的逻辑填空式例句（30~50字）"}]}')

_BAD_TAIL = ("性", "度", "力", "率", "感", "量")


def _hyper_ok(h, subs):
    """挡掉「抽象属性 + 形容词」那类跑偏结果。"""
    if not h or len(h) < 2:
        return False
    if h[-1] in _BAD_TAIL and h not in ("生产力", "战斗力"):
        return False
    parts = [p.strip() for p in (subs or "").replace("，", "、").split("、") if p.strip()]
    if len(parts) < 4:
        return False
    single = sum(1 for p in parts if len(p) == 1)
    return single < len(parts) * 0.6      # 大半是单字 → 多半是形容词罗列


def gen_hyper(con, want=40):
    exist = [r[0] for r in con.execute("SELECT hyper FROM hyper_items")]
    avoid = ("已有的（不要重复）：" + "、".join(exist[:80])) if exist else ""
    d = ai([{"role": "system", "content": SYS},
            {"role": "user", "content": HYPER_PROMPT % (want, avoid)}])
    n, skip = 0, 0
    for it in d.get("items") or []:
        h = (it.get("hyper") or "").strip()
        subs = (it.get("subs") or "").strip()
        if not _hyper_ok(h, subs):
            skip += 1
            continue
        cur = con.execute("INSERT OR IGNORE INTO hyper_items(hyper,subs,note,example,source) VALUES(?,?,?,?,?)",
                          (h, subs, (it.get("note") or "").strip(),
                           (it.get("example") or "").strip(), "ai"))
        n += cur.rowcount
    con.commit()
    print("  上位词 +%d 组（过滤掉 %d 条不合格，库内共 %d）"
          % (n, skip, con.execute("SELECT COUNT(*) FROM hyper_items").fetchone()[0]))


def main():
    if not AI_KEY:
        sys.exit("未配置 ai_key")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    con = sqlite3.connect(DB, timeout=30)
    if cmd == "hyper":
        gen_hyper(con, int(sys.argv[2]) if len(sys.argv) > 2 else 40)
        return
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    if only == "上位词":
        gen_hyper(con, 40)
        return
    for b in (["成语", "实词", "常识", "提法"] if not only else [only]):
        print("→", b)
        try:
            seed_board(con, b)
        except Exception as e:
            print("  ✗", b, e)
    if not only:
        print("→ 上位词")
        try:
            gen_hyper(con, 40)
        except Exception as e:
            print("  ✗ 上位词", e)


if __name__ == "__main__":
    main()
