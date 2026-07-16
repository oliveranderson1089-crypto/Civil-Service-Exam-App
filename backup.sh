#!/bin/bash
# 公考助手每日备份：数据库快照（VACUUM INTO，WAL 模式下也能导出完整一致的单文件）
# + uploads 增量镜像 + config.json。快照保留最近 14 天。
set -euo pipefail
APP="$(cd "$(dirname "$0")" && pwd)"          # 脚本就在项目里，跟着项目走，移动目录无需改本文件
DEST="${GONGKAO_BACKUP_DEST:-$HOME/AppStore/backups/gongkao}"
DAY=$(date +%F)

mkdir -p "$DEST/db" "$DEST/uploads"

python3 - "$APP/app.db" "$DEST/db/app-$DAY.db" <<'PY'
import sqlite3, sys, pathlib
src, dst = sys.argv[1], sys.argv[2]
pathlib.Path(dst).unlink(missing_ok=True)  # VACUUM INTO 要求目标不存在
con = sqlite3.connect(src, timeout=60)
con.execute(f"VACUUM INTO '{dst}'")
con.close()
chk = sqlite3.connect(dst).execute("PRAGMA integrity_check").fetchone()[0]
if chk != "ok":
    sys.exit(f"备份校验失败: {chk}")
print(f"数据库快照 OK -> {dst}")
PY

rsync -a --delete "$APP/uploads/" "$DEST/uploads/"
cp -f "$APP/config.json" "$DEST/config.json" 2>/dev/null || true

find "$DEST/db" -name 'app-*.db' -mtime +14 -delete
echo "备份完成 $(date '+%F %T')"
