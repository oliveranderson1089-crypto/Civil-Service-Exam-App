"""运维：后台看服务状态、一键/勾选重启，不用开终端。

场景是「AI 挂了、定时任务不出内容，人在手机上」。所以这儿的每个动作都得能在
手机后台点完，且**不依赖 AI**——AI 本身就可能是坏掉的那一环。

为什么用 systemctl --user 而不是 sudo/docker：这套东西就是一堆用户级 systemd
单元（gongkao.service + 十几个 gongkao-*.timer），跑在同一个用户下。Web 进程
的环境里有 XDG_RUNTIME_DIR 和 DBUS_SESSION_BUS_ADDRESS，直接调就行，不需要提权。

安全边界：单元名只从 systemd 里**发现**，且必须匹配 gongkao 前缀；请求里带来的
名字只用于在这个已发现的集合里做**筛选**，绝不拼进命令行。所以后台就算被越权
访问，也变不出「重启别的服务」这种能力。
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from core import BASE, log

bp = Blueprint("ops", __name__)

# 主服务是 gongkao.service，其余一律 gongkao-xxx。别写成 gongkao[\w.-]* ——
# 那样 gongkaox.service 也能过，白名单就漏了一个口子。
UNIT_RE = re.compile(r"^gongkao(-[\w.-]+)?\.(service|timer)$")
OPS_LOG = os.path.join(BASE, "data", "ops.log")     # 谁在什么时候重启了什么，跨重启要留痕
TIMEOUT = 30


def _systemctl(*args, timeout=TIMEOUT):
    """跑 systemctl --user，返回 (rc, stdout, stderr)。"""
    try:
        p = subprocess.run(("systemctl", "--user") + args, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "systemctl 超时（%d 秒）" % timeout
    except FileNotFoundError:
        return 127, "", "找不到 systemctl（这台机器不是 systemd？）"


def self_unit():
    """本进程属于哪个单元——重启它等于自杀，得特殊处理。

    从 cgroup 读而不是猜名字：/proc/self/cgroup 末段就是单元名，
    改了 service 文件名也不会认错。
    """
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as f:
            path = f.read().strip().split(":")[-1]
        last = path.rstrip("/").split("/")[-1]
        return last if last.endswith(".service") else ""
    except Exception:
        log.debug("读 cgroup 判断自身单元失败", exc_info=True)
        return ""


def discover():
    """列出本项目的所有单元名。只信 systemd 说有什么，不维护硬编码清单——
    加一个新定时器不用回来改这儿。"""
    names = set()
    # 两条都要跑：list-units 能看到已加载但没有 unit 文件的（比如手写后 daemon-reload 过的），
    # list-unit-files 能看到装了但从没启动过的。合并才是全集。
    for args in (("list-units", "--all", "--no-legend", "--type=service,timer"),
                 ("list-unit-files", "--no-legend", "--type=service,timer")):
        rc, out, err = _systemctl(*args)
        if rc != 0:
            # 这里曾经静默 continue，结果误用了不存在的 --plural 选项也没人知道，
            # 只是恰好被另一条兜住了。失败必须留声。
            log.warning("systemctl %s 失败：%s", " ".join(args), err)
            continue
        for line in out.splitlines():
            tok = line.strip().lstrip("●* ").split()
            if tok and UNIT_RE.match(tok[0]):
                names.add(tok[0])
    return sorted(names)


_SHOW = ("Id", "Description", "ActiveState", "SubState", "UnitFileState", "Result",
         "ExecMainStartTimestamp", "ExecMainExitTimestamp",
         # timer 单元没有 ExecMain*，它的「上次/下次」在这两个属性里。
         # NextElapseUSecRealtime 名字带 USec，值却是可读时间串（"Wed 2026-07-29 08:40:00 CST"），
         # 按微秒去 int() 会全部解析失败、界面上一片空白。
         "LastTriggerUSec", "NextElapseUSecRealtime")


def status(names=None):
    """一次 show 拿全部单元的属性。逐个 show 十几次要好几秒，手机上等不起。"""
    units = names if names is not None else discover()
    if not units:
        return []
    rc, out, err = _systemctl("show", "--property=" + ",".join(_SHOW), *units)
    if rc != 0:
        log.warning("systemctl show 失败：%s", err)
        return []
    # 多个单元的属性块之间用空行分隔
    blocks, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    if cur:
        blocks.append(cur)

    self_u = self_unit()
    rows = []
    for b in blocks:
        uid_ = b.get("Id", "")
        if not uid_:
            continue
        act = b.get("ActiveState", "")
        sub = b.get("SubState", "")
        rows.append({
            "name": uid_,
            "kind": "timer" if uid_.endswith(".timer") else "service",
            "desc": b.get("Description", ""),
            "active": act,
            "sub": sub,
            "enabled": b.get("UnitFileState", ""),
            # 定时器任务是 oneshot：跑完就 inactive(dead)，那是**正常**的，不是挂了。
            # 只有 failed 才算真出事——UI 得按这个标色，否则满屏红。
            "healthy": act != "failed" and b.get("Result", "success") in ("success", ""),
            "running": act == "active" and sub in ("running", "waiting"),
            "last_run": _ts(b.get("ExecMainStartTimestamp") or b.get("LastTriggerUSec")),
            "last_exit": _ts(b.get("ExecMainExitTimestamp", "")),
            "next_run": _ts(b.get("NextElapseUSecRealtime", "")),
            "is_self": uid_ == self_u,
        })
    rows.sort(key=lambda r: (r["kind"] != "service", r["name"]))
    return rows


def _ts(s):
    """systemd 的时间戳形如 'Tue 2026-07-28 09:00:46 CST'，切掉星期和时区。"""
    s = (s or "").strip()
    if not s or s == "n/a":
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", s)
    return m.group(1) if m else s


def _record(who, names, results):
    """把操作留痕落盘。内存里记没用——重启自己就把内存清了，而这正是要查的那次。"""
    try:
        os.makedirs(os.path.dirname(OPS_LOG), exist_ok=True)
        with open(OPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "who": who, "units": names,
                "results": {k: v["ok"] for k, v in results.items()},
            }, ensure_ascii=False) + "\n")
    except Exception:
        log.warning("写运维日志失败", exc_info=True)


# ---------------------------------------------------------------- 路由
@bp.get("/api/admin/services")
def svc_list():
    return jsonify({"services": status(), "self": self_unit()})


@bp.post("/api/admin/services/restart")
def svc_restart():
    data = request.get_json(silent=True) or {}
    known = set(discover())
    want = data.get("names")
    if want is None or data.get("all"):
        names = sorted(known)
    else:
        # 只拿请求里的名字**筛选**已发现的集合。不存在的名字直接丢掉，
        # 保证进 subprocess 的每一个字符串都来自 systemd 自己。
        names = sorted(known & {str(n) for n in (want or [])})
    if not names:
        return jsonify({"error": "没有可重启的服务（名字不在本项目的单元里）"}), 400

    who = session.get("username") or ("uid:%s" % session.get("user_id"))
    me = self_unit()
    results, deferred = {}, []
    for n in names:
        if n == me:
            deferred.append(n)      # 自己最后处理，否则这个响应发不出去
            continue
        rc, _, err = _systemctl("restart", n)
        results[n] = {"ok": rc == 0, "msg": "已重启" if rc == 0 else (err or "rc=%d" % rc)}

    for n in deferred:
        # 重启自己：直接 restart 会在响应写回之前就把进程杀掉，前端只看到「网络错误」，
        # 分不清是重启成功了还是没执行。改成让 systemd 起一个瞬态单元，2 秒后再动手——
        # 响应先出去，前端能给出确定的提示，然后再轮询等它活过来。
        rc, _, err = _systemd_run_restart(n)
        results[n] = {"ok": rc == 0,
                      "msg": "2 秒后重启（页面会短暂断开）" if rc == 0 else (err or "rc=%d" % rc)}

    _record(who, names, results)
    log.info("[ops] %s 重启了 %s", who, ", ".join(names))
    ok = sum(1 for v in results.values() if v["ok"])
    return jsonify({"ok": ok == len(results), "done": ok, "total": len(results),
                    "results": results, "deferred": deferred})


def _systemd_run_restart(unit, delay=2):
    """用瞬态单元延迟重启，避免把自己连同响应一起杀掉。"""
    try:
        p = subprocess.run(
            ["systemd-run", "--user", "--on-active=%d" % delay, "--quiet",
             "--unit=gongkao-selfrestart-%d" % int(time.time()),
             "systemctl", "--user", "restart", unit],
            capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, p.stdout, p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


@bp.get("/api/admin/services/log")
def svc_log():
    """最近的重启记录（操作人 / 时间 / 单元）。"""
    try:
        with open(OPS_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-50:]
    except FileNotFoundError:
        return jsonify({"log": []})
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return jsonify({"log": out})


@bp.get("/api/admin/services/journal/<name>")
def svc_journal(name):
    """看某个单元最近的日志——重启完发现还是不对时，得能当场看到报错。"""
    if name not in set(discover()):
        return jsonify({"error": "未知服务"}), 404
    try:
        p = subprocess.run(["journalctl", "--user", "-u", name, "-n", "80",
                            "--no-pager", "-o", "short-iso"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        return jsonify({"name": name, "text": p.stdout or p.stderr})
    except Exception as e:
        return jsonify({"error": "读日志失败：%s" % e}), 500
