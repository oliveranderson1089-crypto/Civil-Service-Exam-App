"""异地备份状态：**没配置绝不能显示成绿灯**。

这一块存在的理由就是这一条。本地备份天天成功、灯是绿的，可数据仍然只有一份 ——
「看起来一切正常」是这类事故最典型的样子。所以：
  · 没配异地 → 黄灯（一直提醒着，不是「可选功能未启用」）
  · 推送失败 / 上次没跑完 → 红灯（你以为有异地，实际没有，比没配更危险）
  · 同步过但陈旧 → 按天数降级

另外盯住 backup.sh 那一侧的顺序：状态文件必须在碰 restic **之前**就落成 running、
trap 也必须在那之前挂上。这条真出过 —— trap 挂在 restic init 后面时，
密码错会在 init 那步就退出，状态停在上一次的 "ok"：退出码是 1、systemd 记 failed，
后台面板却照样绿着说「已同步」。
"""
import json
import re
import time
from pathlib import Path

import pytest

from mods import capacity

BASE = Path(__file__).resolve().parent.parent


def _state(offsite, backup_last=None):
    """只取异地那一档的结论。"""
    out = {"backup": {"last": backup_last or time.strftime("%Y-%m-%d %H:%M")},
           "disk": {"pct": 10}, "stuck_tasks": [], "offsite": offsite,
           "conc": {"pct": 0}}
    return capacity._states(out)["offsite"]


class Test异地状态分档:
    def test_没配异地是黄灯不是绿灯(self):
        """整块东西存在的理由。绿灯意味着「不用管了」，而这时数据只有一份。"""
        assert _state({"state": "off"}) == "warn"

    def test_状态未知也是黄灯(self):
        """备份脚本还是改造前的旧版本，或者从没跑过 —— 同样不能当没事。"""
        assert _state({"state": "unknown"}) == "warn"
        assert _state({}) == "warn"

    def test_推送失败是红灯(self):
        """比没配更危险：你以为有异地。"""
        assert _state({"state": "bad", "at": "2026-08-13 03:30"}) == "bad"

    def test_上次没跑完是红灯(self):
        """状态停在 running = 上次中途挂了（断电、restic 卡住）。"""
        assert _state({"state": "running", "at": "2026-08-13 03:30"}) == "bad"

    def test_今天推送成功是绿灯(self):
        assert _state({"state": "ok", "at": time.strftime("%Y-%m-%d %H:%M")}) == "ok"

    def test_昨天推送成功还算绿(self):
        """每天 03:30 跑，隔夜看到昨天是正常的。"""
        y = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        assert _state({"state": "ok", "at": y + " 03:30"}) == "ok"

    def test_三天没推成功要留意(self):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        assert _state({"state": "ok", "at": d + " 03:30"}) == "warn"

    def test_一周没推成功报红(self):
        """有异地也要看新不新 —— 一周前的副本，中间那一周的东西一样是没的。"""
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
        assert _state({"state": "ok", "at": d + " 03:30"}) == "bad"

    def test_时间戳坏了不当成正常(self):
        assert _state({"state": "ok", "at": "不是日期"}) == "warn"


class Test读状态文件:
    def test_文件不存在时说得出是哪种情况(self, monkeypatch, tmp_path):
        """「没这个文件」和「配了但没开」是两件事，不能混成一句。"""
        monkeypatch.setattr(capacity, "BACKUP_DEST", str(tmp_path))
        info = capacity._offsite_info()
        assert info["state"] == "unknown"
        assert info["note"], "得说明为什么不知道，不能空着"

    def test_文件损坏时不崩(self, monkeypatch, tmp_path):
        monkeypatch.setattr(capacity, "BACKUP_DEST", str(tmp_path))
        (tmp_path / "offsite.json").write_text("{不是 json", encoding="utf-8")
        assert capacity._offsite_info()["state"] == "unknown"

    def test_正常读出(self, monkeypatch, tmp_path):
        monkeypatch.setattr(capacity, "BACKUP_DEST", str(tmp_path))
        (tmp_path / "offsite.json").write_text(json.dumps(
            {"state": "ok", "note": "异地副本已更新", "at": "2026-08-13 03:31",
             "snapshots": 7, "repo_bytes": 882100738}), encoding="utf-8")
        info = capacity._offsite_info()
        assert info["state"] == "ok"
        assert info["snapshots"] == 7
        assert info["repo_bytes"] == 882100738


class Test备份脚本本身:
    """backup.sh 是 shell，pytest 跑不了它的逻辑，但能盯住几处**顺序**。
    这几处错了不会报错，只会让面板说谎。"""

    def _sh(self):
        return (BASE / "backup.sh").read_text(encoding="utf-8")

    def _first_restic(self, sh):
        """第一条**真正动仓库**的 restic 命令在第几个字符。

        两处要排掉，否则测的不是想测的东西：
          · 注释 —— 这个脚本的注释里就写着「trap 挂在 restic init 后面时…」，
            按字符串裸找会找到那句话（第一版正是如此）
          · `command -v restic` —— 那是探测命令装没装，不碰仓库，
            而且它自己就写了状态，本来就该排在 running 之前
        所以只认「restic 作为命令本身出现」：行首，或者 `if ! ` 之后。
        """
        pos = 0
        for line in sh.splitlines(keepends=True):
            code = line.split("#", 1)[0]
            if re.match(r"\s*(if\s+!\s+)?restic\s", code):
                return pos
            pos += len(line)
        raise AssertionError("backup.sh 里没有动仓库的 restic 命令了？")

    def test_状态文件先落再碰restic(self):
        sh = self._sh()
        running = sh.index('write_offsite "running"')
        first_restic = self._first_restic(sh)
        assert running < first_restic, (
            "write_offsite \"running\" 必须排在所有 restic 命令之前："
            "否则失败时状态会停在上一次的 ok，面板绿着说已同步")

    def test_trap先挂再碰restic(self):
        sh = self._sh()
        trap = sh.index("trap 'write_offsite \"bad\"")
        first_restic = self._first_restic(sh)
        assert trap < first_restic, "ERR trap 必须先挂上，否则 set -e 会带着旧状态直接退出"

    def test_没配异地时也写状态(self):
        """静默跳过是最坏的：面板会一直显示上一次的结论。"""
        sh = self._sh()
        seg = sh[sh.index('if [ -z "${GONGKAO_RESTIC_REPO:-}" ]'):]
        assert 'write_offsite "off"' in seg[:400]

    def test_状态文件是原子写(self):
        """面板随时可能来读。写一半被读到 = 后台报「状态未知」，白吓一跳。"""
        assert ".replace(p)" in self._sh() or "os.replace" in self._sh()

    @pytest.mark.parametrize("key", ["GONGKAO_RESTIC_REPO", "GONGKAO_RESTIC_PASSWORD_FILE"])
    def test_环境变量名与示例文件一致(self, key):
        """backup.env.example 里写错一个名字，用户照着填了却不生效，而且没有任何提示。"""
        assert key in self._sh()
        assert key in (BASE / "backup.env.example").read_text(encoding="utf-8")

    def test_示例文件不含export(self):
        """systemd 的 EnvironmentFile 只认 KEY=value，写了 export 会把它当变量名的一部分。"""
        txt = (BASE / "backup.env.example").read_text(encoding="utf-8")
        bad = [ln for ln in txt.splitlines()
               if re.match(r"^\s*export\s", ln)]
        assert bad == [], "backup.env.example 里有 export，systemd 读不了：%s" % bad


def test_恢复演练脚本存在且可执行():
    """没演练过的备份不算备份。脚本丢了或没执行位 = 那条纪律断了。"""
    p = BASE / "restore_drill.sh"
    assert p.exists(), "restore_drill.sh 不见了"
    assert p.stat().st_mode & 0o111, "restore_drill.sh 没有执行位"
    txt = p.read_text(encoding="utf-8")
    # 演练必须用临时目录和另一个端口，绝不能碰生产
    assert "GONGKAO_DB=" in txt and "mktemp" in txt
    assert "integrity_check" in txt, "演练要验完整性"
