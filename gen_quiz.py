#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""题库生成器：按四川省考卷面结构 AI 生成一套新题（每周二/五定时跑）。
行测 100 题：常识15 / 言语30(选词15+片段12+语句3) / 数量10 /
判断30(**图形推理8** + 定义8+类比7+逻辑7) / 资料15(3篇材料×5题，其中2篇是程序生成的表格/图表)。
图形推理与资料分析材料由 figgen.py 程序化生成（AI 画不准图、也给不出自洽材料）。
申论 1 套：归纳概括 + 综合分析 + 贯彻执行 + 大作文（含给定资料与参考答案）。
用法: python3 gen_quiz.py [xingce|shenlun|both]
"""
import json, os, sys, sqlite3, time, urllib.request
from datetime import date

from figgen import _gen_figure_q, _gen_ziliao   # 图形推理/资料分析：程序化出题，答案由代码保证

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("GONGKAO_DB", os.path.join(BASE, "app.db"))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
AI_BASE = (CFG.get("ai_base") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = CFG.get("ai_model") or "deepseek-chat"
AI_KEY = CFG.get("ai_key") or ""
AI_URL = AI_BASE if AI_BASE.endswith("/chat/completions") else (
    AI_BASE + "/chat/completions" if AI_BASE.endswith("/v1") else AI_BASE + "/v1/chat/completions")


def ai(prompt, max_tokens=4000, temperature=0.6, tries=2):
    last = None
    for _ in range(tries):
        try:
            payload = {"model": AI_MODEL, "temperature": temperature, "max_tokens": max_tokens,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system",
                                     "content": "你是资深公务员考试命题人，题目规范、答案唯一、解析清晰，严格输出 JSON，用简体中文。"},
                                    {"role": "user", "content": prompt}]}
            req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Authorization": "Bearer " + AI_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            return json.loads(j["choices"][0]["message"]["content"])
        except Exception as e:  # JSON 截断等：重试一次
            last = e
            time.sleep(1)
    raise last


Q_FMT = ('每题：{"question":"题干","options":["A....","B....","C....","D...."],'
         '"answer":"A/B/C/D 中一个字母","explanation":"解析（含正确思路与排除理由）"}。'
         '选项要以 A. B. C. D. 开头；答案必须唯一且与解析一致。')

XC_PLAN = [
    ("常识判断", "常识判断", 15,
     "出15道公务员省考常识判断单选题，覆盖：时政政治理论4题、法律3题、人文历史3题、科技生物2题、地理经济3题。难度中等，贴近真题风格。"),
    ("言语理解与表达", "选词填空", 15,
     "出15道选词填空（逻辑填空）单选题：给一段60~120字的语境，挖1~2个空，四个选项为近义词语/成语辨析，难度中等偏上。"),
    ("言语理解与表达", "片段阅读", 12,
     "出12道片段阅读单选题：给120~200字文段，考主旨概括、意图推断、细节理解、标题添加等。"),
    ("言语理解与表达", "语句表达", 3,
     "出3道语句表达单选题：语句排序（给5个打乱的句子选正确顺序）或语句衔接。"),
    ("数量关系", "数学运算", 10,
     "出10道数量关系数学运算单选题：覆盖工程、行程、利润折扣、排列组合概率、容斥、最值、几何、浓度等，计算量适中，答案为具体数值。解析给出最优解法（如赋值法、比例法）。"),
    ("判断推理", "定义判断", 8,
     "出8道定义判断单选题：给出一个规范定义，问下列哪项属于/不属于该定义。定义要严谨。"),
    ("判断推理", "类比推理", 7,
     "出7道类比推理单选题：两词型、三词型、括号填空型混合，考语义/逻辑/语法关系。"),
    ("判断推理", "逻辑判断", 7,
     "出7道逻辑判断单选题：翻译推理、真假推理、加强削弱、前提假设、结论推出混合。"),
]


def gen_xingce(con):
    today = date.today().isoformat()
    name = "行测模拟卷 · %s" % today
    if con.execute("SELECT 1 FROM quiz_sets WHERE name=?", (name,)).fetchone():
        print("今日行测卷已存在，跳过")
        return
    cur = con.execute("INSERT INTO quiz_sets(name,kind) VALUES(?,?)", (name, "行测"))
    sid = cur.lastrowid
    seq = 0
    for module, qtype, n, spec in XC_PLAN:
        try:
            d = ai("为四川省公务员考试行测【%s·%s】%s\n%s\n只输出 JSON：{\"items\":[...]}"
                   % (module, qtype, spec, Q_FMT), max_tokens=6000)
            items = d.get("items", [])[:n]
            for it in items:
                seq += 1
                con.execute("INSERT INTO quiz_questions(set_id,seq,module,qtype,material,question,options,answer,explanation) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (sid, seq, module, qtype, "", it.get("question", ""),
                             json.dumps(it.get("options", []), ensure_ascii=False),
                             (it.get("answer", "") or "").strip()[:1].upper(), it.get("explanation", "")))
            con.commit()
            print("✓ %s·%s +%d" % (module, qtype, len(items)))
            time.sleep(0.5)
        except Exception as e:
            print("✗ %s·%s: %s" % (module, qtype, e))
    # 图形推理：程序化出 8 题（答案由构造保证正确，AI 画不准图）
    for _ in range(8):
        q = _gen_figure_q()
        seq += 1
        con.execute("INSERT INTO quiz_questions(set_id,seq,module,qtype,material,question,options,answer,explanation) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (sid, seq, "判断推理", "图形推理",
                     json.dumps({"type": "figs", **q["figs"]}, ensure_ascii=False),   # 图存 material（前端会渲染成 SVG）
                     q["q"], json.dumps([], ensure_ascii=False), q["answer"], q["explain"]))
    con.commit()
    print("✓ 判断推理·图形推理 +8（程序化）")

    # 资料分析：2 篇程序化材料（真表格/图表，5 题/篇）+ 1 篇 AI 文字材料
    for _ in range(2):
        qs = _gen_ziliao(5)
        mat = json.dumps(qs[0]["material"], ensure_ascii=False)
        for it in qs:
            seq += 1
            con.execute("INSERT INTO quiz_questions(set_id,seq,module,qtype,material,question,options,answer,explanation) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid, seq, "资料分析", "资料分析", mat, it["q"],
                         json.dumps(it["options"], ensure_ascii=False), it["answer"], it["explain"]))
        con.commit()
        print("✓ 资料分析（程序化表格/图表）+5")

    for gi in range(1):
        try:
            d = ai("为四川省考行测【资料分析】出1篇统计材料和5道单选题。材料为200~350字的统计文字材料"
                   "（含具体年份与数据：总量、增速、比重等，数据自洽）。5题覆盖增长率、增长量、比重、平均数、综合判断。\n"
                   '输出 JSON：{"material":"材料全文","items":[5道题目，' + Q_FMT + "]}", max_tokens=4000)
            mat = d.get("material", "")
            for it in d.get("items", [])[:5]:
                seq += 1
                con.execute("INSERT INTO quiz_questions(set_id,seq,module,qtype,material,question,options,answer,explanation) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (sid, seq, "资料分析", "资料分析", mat, it.get("question", ""),
                             json.dumps(it.get("options", []), ensure_ascii=False),
                             (it.get("answer", "") or "").strip()[:1].upper(), it.get("explanation", "")))
            con.commit()
            print("✓ 资料分析材料%d +5" % (gi + 1))
            time.sleep(0.5)
        except Exception as e:
            print("✗ 资料分析%d: %s" % (gi + 1, e))
    print("行测卷完成：%d 题（套卷 id=%d）" % (seq, sid))


def gen_shenlun(con):
    today = date.today().isoformat()
    name = "申论模拟卷 · %s" % today
    if con.execute("SELECT 1 FROM quiz_sets WHERE name=?", (name,)).fetchone():
        print("今日申论卷已存在，跳过")
        return
    try:
        d = ai("为四川省公务员考试出一套申论模拟卷（县乡卷风格）。主题从基层治理/乡村振兴/民生服务/营商环境/生态文明中选一个。\n"
               "先写 3 则给定资料（每则300~450字，编号资料1/2/3，含具体案例与数据）。再出4题：\n"
               "1.归纳概括题(15分,150字内) 2.综合分析题(20分,200字内) 3.贯彻执行题(25分,400字内,写通知/倡议书/短评等) "
               "4.文章写作(40分,800~1000字议论文)。\n每题给【作答要求】和【参考答案】（大作文给提纲式范文要点+精彩开头结尾段）。\n"
               '输出 JSON：{"theme":"主题","materials":"三则资料全文","items":[{"question":"题目与作答要求",'
               '"answer_ref":"参考答案"},...4题]}', max_tokens=7000, temperature=0.7)
        cur = con.execute("INSERT INTO quiz_sets(name,kind) VALUES(?,?)", (name, "申论"))
        sid = cur.lastrowid
        mats = d.get("materials", "")
        names = ["归纳概括", "综合分析", "贯彻执行", "文章写作"]
        for i, it in enumerate(d.get("items", [])[:4]):
            con.execute("INSERT INTO quiz_questions(set_id,seq,module,qtype,material,question,options,answer,explanation) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid, i + 1, "申论", names[i] if i < 4 else "题目", mats if i == 0 else "",
                         it.get("question", ""), "[]", "", it.get("answer_ref", "")))
        con.commit()
        print("申论卷完成（主题：%s，套卷 id=%d）" % (d.get("theme", ""), sid))
    except Exception as e:
        print("✗ 申论卷: %s" % e)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    con = sqlite3.connect(DB)
    if mode in ("xingce", "both"):
        gen_xingce(con)
    if mode in ("shenlun", "both"):
        gen_shenlun(con)
    con.close()


if __name__ == "__main__":
    main()
