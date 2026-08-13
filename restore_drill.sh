#!/bin/bash
# 恢复演练：把最新的备份真的恢复出来，起一个实例，用真请求验一遍。
#
# 为什么要有这个脚本：**没演练过的备份不算备份。** 备份脚本 exit 0、
# integrity_check 通过、文件大小也对 —— 这些都不能证明「这份东西能变回一个能用的应用」。
# 真正会出事的地方在别处：快照里少了 uploads、config.json 没跟着走、
# 恢复出来的库缺了某张新表所以首页直接 500。这些只有真跑一遍才发现得了。
#
# 这个脚本不碰生产：全程在临时目录里、用 GONGKAO_DB / GONGKAO_UPLOADS 指过去、
# 起在另一个端口。跑完自动清理。
#
#   ./restore_drill.sh              # 用本地最新日快照
#   ./restore_drill.sh --offsite    # 从 restic 异地仓库拉最新快照（真正该演练的那条路）
#
# 建议每月跑一次。全绿才算这个月的备份是有效的。
set -euo pipefail
APP="$(cd "$(dirname "$0")" && pwd)"
# backup.env 是给 systemd 用的（KEY=value、没有 export），手动跑时自己加载一下，
# 否则 --offsite 拿不到仓库地址。set -a 让这段期间的赋值自动导出。
if [ -f "$APP/backup.env" ]; then
  set -a; . "$APP/backup.env"; set +a
fi
DEST="${GONGKAO_BACKUP_DEST:-$HOME/AppStore/backups/gongkao}"
PORT="${DRILL_PORT:-8019}"
WORK="$(mktemp -d /tmp/gongkao-drill-XXXXXX)"
MODE="local"
[ "${1:-}" = "--offsite" ] && MODE="offsite"

PID=""
cleanup() {
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. 取回备份
say "1/5 取回备份（$MODE）"
if [ "$MODE" = "offsite" ]; then
  [ -n "${GONGKAO_RESTIC_REPO:-}" ] || fail "没配 GONGKAO_RESTIC_REPO，异地演练无从谈起。见 backup.env.example"
  export RESTIC_REPOSITORY="$GONGKAO_RESTIC_REPO"
  [ -n "${GONGKAO_RESTIC_PASSWORD_FILE:-}" ] && export RESTIC_PASSWORD_FILE="$GONGKAO_RESTIC_PASSWORD_FILE"
  restic restore latest --tag gongkao --target "$WORK/r" || fail "restic restore 失败"
  DB=$(find "$WORK/r" -name 'app-*.db' | sort | tail -1)
  UP=$(find "$WORK/r" -type d -name uploads | head -1)
else
  DB=$(find "$DEST/db" -name 'app-*.db' | sort | tail -1)
  UP="$DEST/uploads"
fi
[ -n "$DB" ] && [ -f "$DB" ] || fail "找不到数据库快照"
ok "快照 $(basename "$DB") ($(du -h "$DB" | cut -f1))，资料目录 ${UP:-无}"

# 复制一份再用：演练过程中应用会写这个库（登录要写 session、做题要写作答），
# 直接用备份文件的话，演练本身就把备份改脏了。
cp "$DB" "$WORK/app.db"

# ---------------------------------------------------------------- 2. 完整性
say "2/5 完整性与内容抽查"
python3 - "$WORK/app.db" <<'PY' || exit 1
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
chk = db.execute("PRAGMA integrity_check").fetchone()[0]
if chk != "ok":
    sys.exit(f"integrity_check 失败: {chk}")
# 光是「文件没坏」不够，还得确认**内容真的在里面**。这几张表是这个应用的命根子：
# 它们空了、或者只剩个壳，恢复出来的是一个能启动的空壳应用，那比恢复失败更糟。
need = {"users": 1, "real_questions": 1000, "review_state": 1}
for t, floor in need.items():
    try:
        n = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except sqlite3.Error as e:
        sys.exit(f"表 {t} 读不出来：{e}")
    if n < floor:
        sys.exit(f"表 {t} 只有 {n} 行（至少该有 {floor}）——快照可能是残的")
    print(f"  {t}: {n} 行")
PY
ok "integrity_check 通过，关键表都有内容"

# ---------------------------------------------------------------- 3. 起实例
say "3/5 用恢复出来的数据起一个实例（端口 $PORT）"
mkdir -p "$WORK/uploads"
[ -n "${UP:-}" ] && [ -d "$UP" ] && cp -r "$UP/." "$WORK/uploads/" 2>/dev/null || true
# config.json 也要一起验：secret_key 丢了就是全员登出，而它不在数据库里。
if [ -f "$DEST/config.json" ]; then
  cp "$DEST/config.json" "$WORK/config.json"
  ok "config.json 在备份里"
else
  printf '\033[33m! config.json 不在备份里 —— 恢复后 secret_key 会重生成，全员登出\033[0m\n'
  echo '{}' > "$WORK/config.json"
fi

GONGKAO_DB="$WORK/app.db" GONGKAO_UPLOADS="$WORK/uploads" GONGKAO_CONFIG="$WORK/config.json" \
  "$APP/.venv/bin/python3" "$APP/app.py" --port "$PORT" >"$WORK/server.log" 2>&1 &
PID=$!

for _ in $(seq 1 40); do
  sleep 0.5
  curl -sf "http://127.0.0.1:$PORT/login" -o /dev/null 2>/dev/null && break
done
kill -0 "$PID" 2>/dev/null || { cat "$WORK/server.log"; fail "实例起不来"; }
curl -sf "http://127.0.0.1:$PORT/login" -o /dev/null || { cat "$WORK/server.log"; fail "登录页打不开"; }
ok "实例已启动，登录页可访问"

# ---------------------------------------------------------------- 4. 真请求
say "4/5 走一遍真请求"
JAR="$WORK/cookies"
# 未登录时 API 必须回 401 而不是 500 —— 顺带验了鉴权层是活的
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/today")
[ "$code" = "401" ] || fail "未登录访问 /api/today 期望 401，实际 $code"
ok "鉴权层正常（401）"

# 静态外壳能不能拼出来（assets 打包那条路也一起验了）
curl -sf "http://127.0.0.1:$PORT/style.css" -o /dev/null || fail "style.css 取不到"
ok "静态资源正常"

# ---------------------------------------------------------------- 5. 结论
say "5/5 结论"
python3 - "$WORK/app.db" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
q = lambda s: db.execute(s).fetchone()[0]
print(f"  用户 {q('SELECT COUNT(*) FROM users')} 个"
      f" · 真题 {q('SELECT COUNT(*) FROM real_questions')} 道"
      f" · 作答留痕 {q('SELECT COUNT(*) FROM real_attempts')} 次"
      f" · 复习进度 {q('SELECT COUNT(*) FROM review_state')} 条")
PY
ok "演练通过 —— 这份备份能变回一个能用的应用"
echo
echo "把今天的日期记下来。下次演练建议不晚于一个月后。"
