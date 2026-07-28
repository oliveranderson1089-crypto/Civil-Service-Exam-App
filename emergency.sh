#!/usr/bin/env bash
# 应急自救：AI 挂了、后台进不去、也没人能帮你改代码时用这个。
#
# 设计前提是「能用的东西越少越好」：只要 bash + python3 + systemctl。
# 不需要 venv（venv 坏了也能跑）、不需要网页能打开、更不需要 AI 是好的——
# AI 本身就可能是坏掉的那一环。
#
# 用法：
#   ./emergency.sh check                 体检：模型名对不对、服务活着没
#   ./emergency.sh autofix               问接口要现有模型名，自动写回配置并重启
#   ./emergency.sh model <fast> [pro]    手动指定模型名，写回配置并重启
#   ./emergency.sh restart [单元...]      不带参数=重启全部 gongkao 单元
#   ./emergency.sh logs [单元]            看日志（默认主服务）
#   ./emergency.sh rollback              把配置回滚到本脚本上次改动之前
set -uo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="${GONGKAO_CONFIG:-$APP/config.json}"
BAK="$CFG.emergency.bak"
MAIN="gongkao.service"

# venv 里的 python 可能就是坏的那一环，找不到就退回系统的
PY="$APP/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
[ -n "$PY" ] || { echo "找不到 python3，改不了配置。请手工编辑 $CFG"; exit 1; }

units() { systemctl --user list-units --all --no-legend --type=service,timer \
          | sed 's/^[●*] *//' | awk '{print $1}' | grep -E '^gongkao[-.]' ; }

# ---------------------------------------------------------------- 写配置
# 单独一个 python 片段：原子写（临时文件 + rename），和 core.py 的 _write_cfg 一个规格。
# 直接用 sed 改 JSON 是不行的——写坏了服务连 secret_key 都读不出来，会全员登出。
set_models() {
  "$PY" - "$CFG" "$BAK" "$1" "${2:-}" <<'PYEOF'
import json, os, shutil, sys
cfg_path, bak, fast, pro = sys.argv[1:5]
with open(cfg_path, encoding="utf-8") as f:
    cfg = json.load(f)          # 读不出来就让它抛——绝不拿空字典去覆盖
shutil.copy2(cfg_path, bak)     # 先留退路，再动手
old = (cfg.get("ai_model"), cfg.get("ai_model_pro"))
if fast:
    cfg["ai_model"] = fast
if pro:
    cfg["ai_model_pro"] = pro
tmp = cfg_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.flush(); os.fsync(f.fileno())
os.replace(tmp, cfg_path)
print("  fast: %s → %s" % (old[0], cfg.get("ai_model")))
print("  pro : %s → %s" % (old[1], cfg.get("ai_model_pro")))
print("  备份: %s" % bak)
PYEOF
}

restart_units() {
  local list=("$@")
  [ ${#list[@]} -eq 0 ] && mapfile -t list < <(units)
  local rc=0
  # 主服务在这儿可以直接重启：本脚本跑在服务外面，杀掉它不影响自己。
  # （后台网页那条路不行，会连响应一起断，所以 mods/ops.py 走 systemd-run 延迟。）
  for u in "${list[@]}"; do
    systemctl --user restart "$u" && echo "  ✓ $u" || { echo "  ✗ $u"; rc=1; }
  done
  return $rc
}

case "${1:-check}" in

check)
  echo "═══ 1/2 AI 配置体检 ═══"
  "$PY" "$APP/aiclient.py"; ai_rc=$?
  echo
  echo "═══ 2/2 服务状态 ═══"
  printf '%-32s %-10s %s\n' 单元 状态 说明
  while read -r u; do
    printf '%-32s %-10s %s\n' "$u" \
      "$(systemctl --user is-active "$u")" \
      "$(systemctl --user show "$u" -p Description --value)"
  done < <(units)
  echo
  fail=$(systemctl --user list-units --state=failed --no-legend | grep -c '^gongkao' || true)
  [ "$fail" -gt 0 ] && echo "**有 $fail 个单元处于 failed** → ./emergency.sh logs <单元名>"
  [ "$ai_rc" -ne 0 ] && echo "**AI 配置有问题** → ./emergency.sh autofix"
  exit 0
  ;;

autofix)
  echo "问接口现在有哪些模型…"
  read -r F P < <("$PY" - "$APP" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])     # 从任意目录调用本脚本都能 import 到 aiclient
import aiclient
ids = aiclient.list_models(ttl=0)
if not ids:
    sys.exit(1)
sys.stderr.write("  接口现有：%s\n" % ", ".join(ids))
# 只有这一行进 stdout，给外面的 read 取走；提示信息一律走 stderr
print(aiclient.pick_model(ids, "fast"), aiclient.pick_model(ids, "pro"))
PYEOF
)
  if [ -z "${F:-}" ]; then
    echo "拉不到模型清单（Key 无效 / 断网 / 代理挡了）。"
    echo "先确认能上网：curl -s https://api.deepseek.com/v1/models -H \"Authorization: Bearer \$KEY\""
    echo "知道名字的话直接：./emergency.sh model <fast名> <pro名>"
    exit 1
  fi
  echo "选定 fast=$F  pro=$P"
  set_models "$F" "$P" || exit 1
  echo "重启服务…"; restart_units
  echo "完成。再体检一次：./emergency.sh check"
  ;;

model)
  [ -n "${2:-}" ] || { echo "用法: ./emergency.sh model <fast模型名> [pro模型名]"; exit 1; }
  set_models "$2" "${3:-}" || exit 1
  echo "重启服务…"; restart_units
  ;;

restart)
  shift || true
  echo "重启中…"; restart_units "$@"
  ;;

logs)
  journalctl --user -u "${2:-$MAIN}" -n 100 --no-pager
  ;;

rollback)
  [ -f "$BAK" ] || { echo "没有备份可回滚（$BAK 不存在）"; exit 1; }
  cp -- "$BAK" "$CFG" && echo "已回滚 $CFG"
  restart_units
  ;;

*)
  sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
  exit 1
  ;;
esac
