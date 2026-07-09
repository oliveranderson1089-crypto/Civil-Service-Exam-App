#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""理论基础（马原/毛概/中特/习思想）知识点生成器（DeepSeek）。
用法:
  python3 gen_theory.py seed              # 一次性生成全部板块×专题
  python3 gen_theory.py seed 毛泽东思想    # 只生成某板块
写入 theory_items(UNIQUE(board,title))，幂等去重。
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

BOARDS = {
    "马克思主义基本原理": [
        "马克思主义的产生与发展", "辩证唯物论（物质与意识）", "唯物辩证法（三大规律五对范畴）",
        "认识论（实践与认识、真理）", "唯物史观（社会存在与社会意识）",
        "政治经济学（商品、剩余价值）", "科学社会主义",
    ],
    "毛泽东思想": [
        "毛泽东思想的形成与发展", "新民主主义革命理论", "社会主义改造理论",
        "社会主义建设道路初步探索", "毛泽东思想活的灵魂（实事求是·群众路线·独立自主）",
        "重要会议与著作", "军事思想与统一战线",
    ],
    "中国特色社会主义理论体系": [
        "邓小平理论", "“三个代表”重要思想", "科学发展观",
        "社会主义初级阶段与基本路线", "改革开放史上的重要会议",
    ],
    "习近平新时代中国特色社会主义思想": [
        "核心要义（“十个明确”）", "基本方略（“十四个坚持”）", "新发展理念与新发展格局",
        "中国式现代化", "全过程人民民主", "全面依法治国与全面从严治党",
        "新质生产力与高质量发展", "生态文明与“两山”理念", "总体国家安全观与人类命运共同体",
    ],
}

SYS = "你是公务员考试政治理论教研老师，只讲考点，结论准确、表述与党的正式文件一致，不夸张不注水。"


def ai(messages, max_tokens=4000, temperature=0.3, retry=2):
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
        except Exception as e:
            last = e
            time.sleep(3 + 3 * i)
    raise last


def gen(con, board, topic):
    have = con.execute("SELECT COUNT(*) FROM theory_items WHERE board=? AND topic=?",
                       (board, topic)).fetchone()[0]
    if have >= 6:
        print("    %s 已有 %d 条，跳过" % (topic, have))
        return 0
    prompt = ("板块：%s\n专题：%s\n\n请给出该专题下行测常识判断/事业单位公基最常考的 8~10 个知识点。\n"
              "输出 JSON：{\"items\":[{\"title\":\"知识点名（16字内）\","
              "\"content\":\"考点内容（60~110字，直接给结论与关键表述，含时间/会议/文件等易考细节）\"}]}\n"
              "要求：概念的定义、地位、首次提出的会议或文献、常考数字（如“十个明确”）务必准确；"
              "不要写“综上所述”“需要注意”之类废话。" % (board, topic))
    d = ai([{"role": "system", "content": SYS}, {"role": "user", "content": prompt}])
    n = 0
    for it in d.get("items") or []:
        t = (it.get("title") or "").strip()
        if not t:
            continue
        cur = con.execute("INSERT OR IGNORE INTO theory_items(board,topic,title,content) VALUES(?,?,?,?)",
                          (board, topic, t, (it.get("content") or "").strip()))
        n += cur.rowcount
    con.commit()
    print("    %s +%d" % (topic, n))
    return n


def main():
    if not AI_KEY:
        sys.exit("未配置 ai_key")
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    con = sqlite3.connect(DB, timeout=30)
    total = 0
    for b, topics in BOARDS.items():
        if only and b != only:
            continue
        print("→", b)
        for t in topics:
            try:
                total += gen(con, b, t)
            except Exception as e:
                print("    ✗", t, e)
    print("合计 +%d 条，库内 %d 条" % (total, con.execute("SELECT COUNT(*) FROM theory_items").fetchone()[0]))


if __name__ == "__main__":
    main()
