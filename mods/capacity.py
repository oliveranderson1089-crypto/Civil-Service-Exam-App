"""备份与容量：备份到底跑没跑、盘还剩多少、谁在长胖。

backup.sh 每天 03:30 跑得挺好（VACUUM INTO + integrity_check + 14 天滚动），
问题是**它跑得好不好在后台一个字都看不见**——出事那天才发现最近一次备份是三周前，
是这类系统最典型的死法。

三块：
  · 备份：最近一次什么时候、多大、几份、下次什么时候；可以当场补跑一次
  · 容量：库 / 上传 / 数据 / 备份各占多少，盘还剩多少
  · 长任务：bg_tasks 里有没有卡死的（status=running 但半天不动）

**目录大小是算出来的，不是查出来的**：uploads 有近千个文件、868M，每次刷后台都
走一遍 os.walk 是浪费。所以带 TTL 缓存，5 分钟内复用——容量这种东西也没必要秒级准。

删文件的能力**不放这儿**。手工快照该留哪几个是人的判断（它们是历次改造前的保命点），
所以只报告 + 给命令，跟内容质检同一条规矩。
"""
import os
import shutil
import time

from flask import Blueprint, jsonify

from core import BASE, DB, UPLOADS, get_db, log

bp = Blueprint("capacity", __name__)

# 跟 backup.sh 同一个口径（那边是 ${GONGKAO_BACKUP_DEST:-$HOME/AppStore/backups/gongkao}）。
# 两边不一致的话，后台会对着一个空目录说「从来没备份过」。
BACKUP_DEST = os.environ.get(
    "GONGKAO_BACKUP_DEST",
    os.path.join(os.path.expanduser("~"), "AppStore", "backups", "gongkao"))

_CACHE_TTL = 300
_cache = {"at": 0.0, "data": None}


def _dir_size(path):
    """目录总字节。走 scandir 不用 du：不 fork 进程，也不受 shell 转义影响。"""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += _dir_size(e.path)
                except OSError:
                    continue          # 权限/竞态删除，跳过这一个就好
    except (OSError, FileNotFoundError):
        return 0
    return total


def _mtime_str(p):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    except OSError:
        return ""


def _backup_info():
    """最近一次备份、份数、跨度。

    不在这儿跑 integrity_check：145M 的库要好几秒，而 backup.sh **每次备份时已经跑过**
    （校验不过就 exit 非 0，systemd 会记 failed）。所以「最近的快照存在」本身
    就是「它当时校验通过」的证据，重复跑纯属浪费。
    """
    d = os.path.join(BACKUP_DEST, "db")
    info = {"dir": d, "count": 0, "last": "", "last_size": 0, "oldest": "",
            "db_bytes": 0, "uploads_bytes": 0}
    try:
        snaps = sorted(f for f in os.listdir(d) if f.startswith("app-") and f.endswith(".db"))
    except (OSError, FileNotFoundError):
        return info
    info["count"] = len(snaps)
    if snaps:
        newest = os.path.join(d, snaps[-1])
        info["last"] = _mtime_str(newest)
        try:
            info["last_size"] = os.path.getsize(newest)
        except OSError:
            pass
        info["oldest"] = snaps[0].replace("app-", "").replace(".db", "")
    info["db_bytes"] = _dir_size(d)
    info["uploads_bytes"] = _dir_size(os.path.join(BACKUP_DEST, "uploads"))
    return info


def _manual_snaps():
    """项目根上的 app.db.bak.*：历次改造前手动留的保命点。

    它们没有保留策略、没人清，是最容易悄悄吃掉几个 G 的地方。这里只列出来，
    删不删由人定——每一个都对应一次「万一改坏了要回滚」的时刻。
    """
    out = []
    try:
        for f in sorted(os.listdir(BASE)):
            if f.startswith("app.db.bak."):
                p = os.path.join(BASE, f)
                try:
                    out.append({"name": f, "bytes": os.path.getsize(p), "at": _mtime_str(p)})
                except OSError:
                    continue
    except OSError:
        log.debug("列手工快照失败", exc_info=True)
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


def _stuck_tasks(db):
    """卡住的长任务：还标着 running，但超过 30 分钟没动静。

    bg_tasks 本来只按 user_id 索引、只给用户自己看，管理员看不到全局——
    于是「某个文档识题卡在 60%」这种事只能等用户来说。
    """
    try:
        rows = db.execute(
            "SELECT id,user_id,kind,title,progress,total,updated_at FROM bg_tasks "
            "WHERE status='running' "
            "AND updated_at < datetime('now','localtime','-30 minute') "
            "ORDER BY id DESC LIMIT 20").fetchall()
        recent = db.execute(
            "SELECT COUNT(*) c FROM bg_tasks "
            "WHERE created_at >= datetime('now','localtime','-7 day')").fetchone()["c"]
    except Exception:
        log.debug("读 bg_tasks 失败", exc_info=True)
        return [], 0
    return [dict(r) for r in rows], recent


def _sizes():
    data_dir = os.path.join(BASE, "data")
    return {
        "db": os.path.getsize(DB) if os.path.exists(DB) else 0,
        "uploads": _dir_size(UPLOADS),
        "data": _dir_size(data_dir),
    }


def snapshot(db):
    now = time.time()
    if _cache["data"] and now - _cache["at"] < _CACHE_TTL:
        out = dict(_cache["data"])
    else:
        # 只有这部分要扫盘，缓存的就是它
        bk = _backup_info()
        snaps = _manual_snaps()
        sizes = _sizes()
        try:
            du = shutil.disk_usage(BASE)
            disk = {"total": du.total, "used": du.used, "free": du.free,
                    "pct": round(du.used * 100.0 / du.total, 1) if du.total else 0}
        except OSError:
            disk = {"total": 0, "used": 0, "free": 0, "pct": 0}
        out = {"backup": bk, "manual_snaps": snaps, "sizes": sizes, "disk": disk,
               "manual_bytes": sum(s["bytes"] for s in snaps),
               "scanned_at": time.strftime("%H:%M:%S")}
        _cache.update(at=now, data=out)
    # 任务状态每次都查（便宜，而且它正是要看「此刻」的东西）
    stuck, recent = _stuck_tasks(db)
    out["stuck_tasks"] = stuck
    out["tasks_7d"] = recent
    return out


def _states(out):
    """红黄绿由后端判——和产出健康、内容质检同一套口径，前端只负责显示。

    备份的宽限期比内容宽一天：它每天 03:30 跑，隔夜看到「昨天」是正常的。
    """
    today = time.strftime("%Y-%m-%d")
    last = (out["backup"]["last"] or "")[:10]
    if not last:
        bk = "bad"                      # 一份备份都没有
    else:
        lag = (time.mktime(time.strptime(today, "%Y-%m-%d"))
               - time.mktime(time.strptime(last, "%Y-%m-%d"))) / 86400
        bk = "ok" if lag <= 1 else ("warn" if lag <= 3 else "bad")
    pct = out["disk"]["pct"]
    disk = "bad" if pct >= 92 else ("warn" if pct >= 85 else "ok")
    return {"backup": bk, "disk": disk,
            "tasks": "warn" if out["stuck_tasks"] else "ok"}


@bp.get("/api/admin/capacity")
def capacity():
    out = snapshot(get_db())
    out["states"] = _states(out)
    return jsonify(out)
