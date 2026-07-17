"""配置读写：这几条守的都是「静默」——secret_key 悄悄换掉、配置悄悄丢。

坏掉的 config.json 会让服务拒绝启动，所以启动路径得开子进程测，不能在本进程 import。
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from conftest import BASE, appmod


def _boot(tmp_path, config_text=None, extra=""):
    """在子进程里以指定 config.json 启动一次 app，返回 CompletedProcess。"""
    cfg = tmp_path / "config.json"
    if config_text is not None:
        cfg.write_text(config_text, encoding="utf-8")
    env = dict(os.environ,
               GONGKAO_DB=str(tmp_path / "b.db"),
               GONGKAO_CONFIG=str(cfg),
               GONGKAO_UPLOADS=str(tmp_path / "up"))
    code = "import app\n" + textwrap.dedent(extra)
    return subprocess.run([sys.executable, "-c", code], cwd=str(BASE), env=env,
                          capture_output=True, text=True, timeout=180)


class TestBoot:
    def test_config损坏就拒绝启动而不是重置(self, tmp_path):
        """半个 JSON 曾会被当成「没有配置」：另生 secret_key 全员登出，再覆盖掉原文件。"""
        r = _boot(tmp_path, '{"secret_key": "abc", "ai_ke')
        assert r.returncode != 0, "config.json 损坏却照常启动了"
        assert "读不出来" in (r.stderr + r.stdout)

    def test_拒绝启动时不碰坏文件(self, tmp_path):
        """启动失败也不能顺手把损坏的 config 覆盖掉——里面还有 ai_key 等着人去救。"""
        broken = '{"secret_key": "abc", "ai_ke'
        _boot(tmp_path, broken)
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == broken

    def test_首次启动能自己建配置(self, tmp_path):
        r = _boot(tmp_path, config_text=None)
        assert r.returncode == 0, r.stderr[-500:]
        cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert len(cfg["secret_key"]) >= 32

    def test_已有secret_key不会被换掉(self, tmp_path):
        """换 key = 把所有人登出，只该在首次启动时发生。"""
        key = "a" * 64
        r = _boot(tmp_path, json.dumps({"secret_key": key}))
        assert r.returncode == 0, r.stderr[-500:]
        assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["secret_key"] == key


class TestSaveCfg:
    def test_存不下要抛出来而不是假装成功(self, tmp_path, monkeypatch):
        monkeypatch.setattr(appmod, "CONFIG", str(tmp_path / "没有这个目录" / "config.json"))
        with pytest.raises(Exception):
            appmod._save_cfg()

    def test_原子写不会留下半个文件(self, tmp_path, monkeypatch):
        """json.dump 写到一半炸掉时，原文件必须原样还在。"""
        cfg = tmp_path / "config.json"
        cfg.write_text('{"secret_key": "good"}', encoding="utf-8")
        monkeypatch.setattr(appmod, "CONFIG", str(cfg))

        def boom(*a, **k):
            raise IOError("磁盘满了")
        monkeypatch.setattr(appmod.json, "dump", boom)
        with pytest.raises(IOError):
            appmod._save_cfg()
        assert json.loads(cfg.read_text(encoding="utf-8"))["secret_key"] == "good"
