#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给「加播放功能之前」入库的老视频补上播放地址。

新抓的视频在入库时就把播放地址算好了（见 crawl_video.resolve_play），
但库里还躺着一批老的 —— 不补的话，点播放只能跳浏览器。跑一次就行。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import DB        # noqa: E402
import crawl_video as C    # noqa: E402

db = sqlite3.connect(DB, timeout=60)
db.row_factory = sqlite3.Row
rows = db.execute("SELECT id,kind,guid,url,title FROM video_items "
                  "WHERE (play IS NULL OR play='') AND kind IN ('cctv','sc')").fetchall()
if not rows:
    print("没有要补的")
    sys.exit()

print("要补 %d 条" % len(rows))
need_browser = any(r["kind"] == "sc" for r in rows)
ch = C.Chrome() if need_browser else None
try:
    done = 0
    for r in rows:
        p = C.resolve_play(ch, {"kind": r["kind"], "guid": r["guid"], "url": r["url"]})
        if p:
            db.execute("UPDATE video_items SET play=? WHERE id=?",
                       (json.dumps(p, ensure_ascii=False), r["id"]))
            done += 1
        print("  %s %-5s %s" % ("✓" if p else "✗", r["kind"], r["title"][:40]))
finally:
    if ch:
        ch.close()
db.commit()
print("\n补上 %d / %d 条" % (done, len(rows)))
