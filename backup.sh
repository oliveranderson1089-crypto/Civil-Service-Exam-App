#!/bin/bash
# 公考助手每日备份：数据库快照（VACUUM INTO，WAL 模式下也能导出完整一致的单文件）
# + uploads 增量镜像 + config.json。快照保留最近 14 天。
#
# 本地快照做完之后，再把它推一份到**异地**（restic）。为什么必须有这一段：
# 本地快照和原始库在同一块盘上，盘挂了是一起没的。而这里面有一类东西
# 重跑脚本造不回来 —— OCR 和 AI 解析可以重来，「你自己做过哪些题、错在哪、
# 复习到第几轮」重不来。所以「备份」的定义是**另一个故障域里还有一份**。
#
# 异地那段没配也能跑（GONGKAO_RESTIC_REPO 留空就跳过），但**绝不静默跳过**：
# 每次都会把异地状态写进 offsite.json，后台「备份容量」据此显示黄灯，
# 一直提醒「数据只有一份」。这条是本项目的老规矩：静默失败是最贵的 bug。
#
# 配法：把 backup.env.example 复制成 backup.env 填好，systemd 会自动加载它
#（gongkao-backup.service 里的 EnvironmentFile=-，前面的 - 表示没这文件也不报错）。
set -euo pipefail
APP="$(cd "$(dirname "$0")" && pwd)"          # 脚本就在项目里，跟着项目走，移动目录无需改本文件
DEST="${GONGKAO_BACKUP_DEST:-$HOME/AppStore/backups/gongkao}"
DAY=$(date +%F)
SNAP="$DEST/db/app-$DAY.db"
OFFSITE_JSON="$DEST/offsite.json"

mkdir -p "$DEST/db" "$DEST/uploads"

# ---------------------------------------------------------------- 本地快照
python3 - "$APP/app.db" "$SNAP" <<'PY'
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
chmod 600 "$DEST/config.json" 2>/dev/null || true   # 里面是明文 ai_key / secret_key

find "$DEST/db" -name 'app-*.db' -mtime +14 -delete

# ---------------------------------------------------------------- 异地副本
# 状态文件先写「进行中」，再按结果覆盖。中途断电也能看出上次卡在哪一步，
# 而不是留一个「上次成功」的旧状态骗人。
write_offsite() {
  # $1=state  $2=一句话说明  $3=快照数(可空)  $4=仓库字节(可空)
  python3 - "$OFFSITE_JSON" "$1" "$2" "${3:-}" "${4:-}" <<'PY'
import json, sys, time, pathlib
p, state, note, snaps, size = sys.argv[1:6]
out = {"state": state, "note": note, "at": time.strftime("%Y-%m-%d %H:%M"),
       "snapshots": int(snaps) if snaps.isdigit() else None,
       "repo_bytes": int(size) if size.isdigit() else None}
tmp = p + ".tmp"
pathlib.Path(tmp).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
pathlib.Path(tmp).replace(p)          # 原子替换，别让面板读到写了一半的 JSON
PY
}

if [ -z "${GONGKAO_RESTIC_REPO:-}" ]; then
  write_offsite "off" "没有配异地仓库：本地快照和原始库在同一块盘上，盘挂了一起没。见 backup.env.example"
  echo "本地备份完成 $(date '+%F %T')；异地未配置（后台会显示黄灯）"
  exit 0
fi

if ! command -v restic >/dev/null 2>&1; then
  write_offsite "bad" "配了仓库但机器上没有 restic 命令"
  echo "异地备份失败：restic 未安装" >&2
  exit 1
fi

export RESTIC_REPOSITORY="$GONGKAO_RESTIC_REPO"
[ -n "${GONGKAO_RESTIC_PASSWORD_FILE:-}" ] && export RESTIC_PASSWORD_FILE="$GONGKAO_RESTIC_PASSWORD_FILE"

# 状态先落「running」、trap 先挂上，**然后**才碰 restic。顺序反了就出过一次事：
# trap 挂在 restic init 后面时，密码错 / U 盘没插会在 init 那步就 set -e 退出，
# 状态文件还停在上一次的 "ok" —— 退出码是 1、systemd 记 failed，可后台面板
# 照样绿着说「已同步」。那是这套东西最不该有的样子。
write_offsite "running" "正在推送 $DAY 的快照"
trap 'write_offsite "bad" "推送失败，详见 journalctl --user -u gongkao-backup -n 50"' ERR

# 仓库还不存在就先建（init 在已存在的仓库上会报错，所以先探一下）。
# 注意 `if ! cmd` 里的失败不触发 ERR trap，探测本身不会被误记成推送失败。
if ! restic cat config >/dev/null 2>&1; then
  echo "异地仓库还没初始化，正在 restic init …"
  restic init
fi

# 推的是**导出的快照**而不是活库：活库带 WAL，直接备份可能拿到撕裂的状态。
# uploads 推镜像目录而不是原目录，两边内容一样但镜像不会在推送中途被应用改写。
restic backup "$SNAP" "$DEST/uploads" \
  --tag gongkao --host gongkao --exclude-caches

# 保留策略和本地一致再宽一点：日快照 14 天、周快照 8 周、月快照 12 个月。
# 异地存储便宜且去重，留久一点的边际成本很低，而「三个月前那份」偶尔真的救命。
restic forget --tag gongkao --host gongkao \
  --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

SNAPS=$(restic snapshots --tag gongkao --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo "")
RSIZE=$(restic stats --mode raw-data --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("total_size",""))' 2>/dev/null || echo "")

write_offsite "ok" "异地副本已更新" "$SNAPS" "$RSIZE"
echo "备份完成（含异地）$(date '+%F %T')"
