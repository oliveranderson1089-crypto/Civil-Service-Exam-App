#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「加古诗积累之前」已经背过的古诗卡补进 gushi_log。

流水表是新加的（见 schema.py 的 gushi_log），从今往后由 mods/review.py 每天自动记；
但之前背过的那批只在 review_state 里留了 kind='gushi'，那儿**没有首次日期** ——
只有 last_done（每复习一次就被覆盖）和 stage（复习过几轮）。所以这里按遗忘曲线倒推：

    第一次出现日 ≈ last_done − (前 stage-1 轮的间隔之和)

stage=1（今天才第一次背）就落在 last_done 当天；stage=2 的往前推 1 天（第 1 轮的间隔）。
倒推结果不会早于卡本身的入库日（gushi_cards.created_at）—— 卡还没建出来，不可能背过它。
是估算，不是记录：只影响这批老数据挂在哪一天，往后的都是真日期。跑一次就行（幂等）。

用法: python3 backfill_gushi_log.py [--dry]
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import DB                                   # noqa: E402
from mods.review import REVIEW_INTERVALS              # noqa: E402

DRY = "--dry" in sys.argv

db = sqlite3.connect(DB, timeout=60)
db.row_factory = sqlite3.Row
db.execute("""CREATE TABLE IF NOT EXISTS gushi_log(
                  user_id INTEGER NOT NULL, card_id INTEGER NOT NULL, added_on TEXT,
                  created_at TEXT DEFAULT (datetime('now','localtime')),
                  UNIQUE(user_id, card_id))""")

born = {r["id"]: (r["created_at"] or "")[:10]
        for r in db.execute("SELECT id, created_at FROM gushi_cards")}
rows = db.execute(
    "SELECT s.user_id, s.item_id, s.stage, s.last_done FROM review_state s "
    "WHERE s.kind='gushi' AND NOT EXISTS("
    "  SELECT 1 FROM gushi_log l WHERE l.user_id=s.user_id AND l.card_id=s.item_id)").fetchall()
if not rows:
    print("没有要补的（流水已经是齐的）")
    sys.exit()

added = 0
for r in rows:
    last = (r["last_done"] or "")[:10]
    if not last:
        continue
    back = sum(REVIEW_INTERVALS[min(i, len(REVIEW_INTERVALS) - 1)]
               for i in range(1, int(r["stage"] or 0)))      # stage<=1 → 0 天
    day = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=back)).strftime("%Y-%m-%d")
    day = max(day, born.get(r["item_id"], day))               # 不早于卡的入库日
    print("  用户%d 卡%-4d stage=%d last=%s → %s" % (r["user_id"], r["item_id"],
                                                   r["stage"] or 0, last, day))
    if not DRY:
        db.execute("INSERT OR IGNORE INTO gushi_log(user_id,card_id,added_on) VALUES(?,?,?)",
                   (r["user_id"], r["item_id"], day))
    added += 1
if not DRY:
    db.commit()
print("%s %d 条" % ("试跑（没写库）" if DRY else "已补", added))
