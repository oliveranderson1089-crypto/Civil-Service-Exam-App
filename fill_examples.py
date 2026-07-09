#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为「衔接表达」补齐 AI 例句（每天素材更新后跑一次，用户就不用挨个点按钮）。
用法: python3 fill_examples.py [最多生成条数，默认 30]
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

SYS = "你是申论写作辅导老师，例句规范、书面化。"
TPL = ("下面是一句申论写作的衔接表达/万能句式：\n%s\n\n"
       "请用它写一个申论语境下的规范例句（书面化、紧扣治理/民生/发展类主题，30~60字），只输出例句本身。")


def ai(content, retry=2):
    payload = {"model": AI_MODEL, "temperature": 0.6, "max_tokens": 200,
               "messages": [{"role": "system", "content": SYS},
                            {"role": "user", "content": TPL % content}]}
    last = None
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Authorization": "Bearer " + AI_KEY,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            return j["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = e
            time.sleep(2 + 2 * i)
    raise last


def main():
    if not AI_KEY:
        sys.exit("未配置 ai_key")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    con = sqlite3.connect(DB, timeout=30)
    rows = con.execute("SELECT id, content FROM sucai_items WHERE kind='衔接表达' "
                       "AND (example IS NULL OR example='') ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("衔接表达例句已齐全")
        return
    print("待生成 %d 条" % len(rows))
    ok = 0
    for sid, content in rows:
        try:
            ex = ai(content)
            con.execute("UPDATE sucai_items SET example=? WHERE id=?", (ex, sid))
            con.commit()
            ok += 1
            print("  ✓", ex[:34])
        except Exception as e:
            print("  ✗", e)
    print("完成 %d/%d" % (ok, len(rows)))


if __name__ == "__main__":
    main()
