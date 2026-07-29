"""备份与容量（mods/capacity.py）。

要点：
1. **备份目录口径必须和 backup.sh 一致**。两边不一致的话，后台会对着一个空目录
   说「从来没备份过」——一个只会在你最需要它的时候骗你的 bug。
2. 备份不新鲜要报红。这块存在的全部理由就是「最近一次备份是三周前」别再无声无息。
3. 目录不存在、盘读不了都不能崩：出事时它得能说话。
"""
import os
import re
import time

import pytest

from conftest import BASE, appmod
from mods import capacity


@pytest.fixture(autouse=True)
def _clear_cache():
    """容量结果缓存 5 分钟，用例之间要清掉，否则互相看到对方的数据。"""
    capacity._cache.update(at=0.0, data=None)
    yield
    capacity._cache.update(at=0.0, data=None)


def test_非管理员进不来(flask_app):
    assert flask_app.test_client().get("/api/admin/capacity").status_code == 401


def test_接口结构完整(auth_client):
    d = auth_client.get("/api/admin/capacity").get_json()
    for k in ("backup", "sizes", "disk", "manual_snaps", "stuck_tasks", "states"):
        assert k in d, "少了 %s" % k
    assert d["states"]["backup"] in ("ok", "warn", "bad")
    assert d["disk"]["total"] > 0


def test_备份目录口径和backup_sh一致():
    """backup.sh 里是 ${GONGKAO_BACKUP_DEST:-$HOME/AppStore/backups/gongkao}。
    这两处任何一边改了路径而另一边没跟上，后台就会谎报「从未备份」。"""
    sh = (BASE / "backup.sh").read_text(encoding="utf-8")
    m = re.search(r'DEST="\$\{GONGKAO_BACKUP_DEST:-(.+?)\}"', sh)
    assert m, "backup.sh 里没找到 DEST 定义，口径对不上了"
    expect = m.group(1).replace("$HOME", os.path.expanduser("~"))
    assert capacity.BACKUP_DEST == expect
    # 环境变量名也要一致，不然自定义备份路径时只有一边生效
    assert "GONGKAO_BACKUP_DEST" in sh


class Test备份新鲜度:
    def _state(self, last):
        out = {"backup": {"last": last}, "disk": {"pct": 10}, "stuck_tasks": []}
        return capacity._states(out)["backup"]

    def test_今天备份过是正常(self):
        assert self._state(time.strftime("%Y-%m-%d %H:%M")) == "ok"

    def test_昨天也算正常(self):
        """每天 03:30 跑，隔夜看到「昨天」是正常的。"""
        y = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        assert self._state(y + " 03:30") == "ok"

    def test_三天前要留意(self):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        assert self._state(d + " 03:30") == "warn"

    def test_五天前必须报红(self):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - 5 * 86400))
        assert self._state(d + " 03:30") == "bad"

    def test_一份备份都没有是最严重的(self):
        assert self._state("") == "bad"


class Test磁盘水位:
    def _state(self, pct):
        out = {"backup": {"last": time.strftime("%Y-%m-%d")},
               "disk": {"pct": pct}, "stuck_tasks": []}
        return capacity._states(out)["disk"]

    @pytest.mark.parametrize("pct,expect", [
        (26, "ok"), (84, "ok"), (85, "warn"), (91, "warn"), (92, "bad"), (99, "bad")])
    def test_按水位分档(self, pct, expect):
        assert self._state(pct) == expect


def test_备份目录不存在时不崩(monkeypatch, auth_client):
    """新机器上还没跑过备份 —— 该说「从未备份」并报红，不是 500。"""
    monkeypatch.setattr(capacity, "BACKUP_DEST", "/nonexistent/path/xyz")
    d = auth_client.get("/api/admin/capacity").get_json()
    assert d["backup"]["count"] == 0 and d["backup"]["last"] == ""
    assert d["states"]["backup"] == "bad"


def test_目录大小算得对(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 500)
    assert capacity._dir_size(str(tmp_path)) == 1500
    # 不存在的目录返回 0 而不是抛异常
    assert capacity._dir_size("/nonexistent/xyz") == 0


def test_扫盘结果会缓存(auth_client):
    """uploads 有近千个文件，每次刷后台都走一遍 os.walk 是浪费。"""
    d1 = auth_client.get("/api/admin/capacity").get_json()
    d2 = auth_client.get("/api/admin/capacity").get_json()
    assert d1["scanned_at"] == d2["scanned_at"], "第二次请求应该命中缓存"


def test_卡死任务只算超过半小时没动的(auth_client):
    from core import get_db
    with appmod.app.app_context():
        db = get_db()
        db.execute("DELETE FROM bg_tasks")
        # 刚更新过的：还在跑，不算卡死
        db.execute("INSERT INTO bg_tasks(user_id,kind,title,status,updated_at) "
                   "VALUES(1,'docqa','刚开始','running',datetime('now','localtime'))")
        # 一小时没动了：卡死
        db.execute("INSERT INTO bg_tasks(user_id,kind,title,status,updated_at) "
                   "VALUES(1,'docqa','卡住了','running',"
                   "datetime('now','localtime','-60 minute'))")
        # 早就跑完的：不算
        db.execute("INSERT INTO bg_tasks(user_id,kind,title,status,updated_at) "
                   "VALUES(1,'write','完成了','done',datetime('now','localtime','-1 day'))")
        db.commit()
    d = auth_client.get("/api/admin/capacity").get_json()
    assert len(d["stuck_tasks"]) == 1
    assert d["stuck_tasks"][0]["title"] == "卡住了"
    assert d["states"]["tasks"] == "warn"


def test_没有删文件的路径():
    """手工快照留哪几个是人的判断，这块只报告、只给命令。"""
    src = (BASE / "mods" / "capacity.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    for bad in ("os.remove", "os.unlink", "shutil.rmtree", "os.rmdir"):
        assert bad not in code, "容量模块不该有删除能力，出现了 %s" % bad
