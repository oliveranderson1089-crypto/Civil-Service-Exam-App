"""测试环境隔离。

关键：app.py 在 import 时就跑 init_db()，所以环境变量必须在 import 之前设好。
这也顺带让「导入」本身成为一条测试——init_db() 在全新空库上崩过一次（4a5407b），
这里每跑一次测试就复验一次。
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="gongkao-test-"))

# ---- 必须先于 import app ----
os.environ["GONGKAO_DB"] = str(_TMP / "test.db")
os.environ["GONGKAO_UPLOADS"] = str(_TMP / "uploads")
os.environ["GONGKAO_CONFIG"] = str(_TMP / "config.json")

sys.path.insert(0, str(BASE))
import core  # noqa: E402  DB/路径常量拆模块后归了 core
import app as appmod  # noqa: E402
from mods import auth as authmod  # noqa: E402  图形验证码跟着登录走了

# 保命闸：确认测试没连上生产库
assert core.DB == str(_TMP / "test.db"), f"测试库指向了 {core.DB}，拒绝运行"
assert "AppStore/apps/gongkao-app/app.db" not in core.DB

DB = core.DB


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def flask_app():
    appmod.app.config.update(TESTING=True)
    return appmod.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def pass_captcha(data):
    """塞一个已知验证码再取用——_captcha_ok 是一次性 pop，每次请求都要重塞。"""
    cid = "test-cid-%s" % time.time()
    authmod._captchas[cid] = {"code": "abcd", "exp": time.time() + 300}
    data["captcha_id"] = cid
    data["captcha"] = "abcd"
    return data


@pytest.fixture(scope="session")
def account():
    return {"username": "tester", "password": "Test-passw0rd!"}


@pytest.fixture
def auth_client(flask_app, account):
    """注册（首个用户即管理员，免邀请码）并登录，返回带 session 的 client。"""
    c = flask_app.test_client()
    with flask_app.app_context():
        fresh = appmod.users_count() == 0
    if fresh:
        r = c.post("/api/register", json=pass_captcha({
            "username": account["username"],
            "password": account["password"],
            "sec_question": "测试问题",
            "sec_answer": "测试答案",
        }))
        assert r.status_code == 200, f"注册失败: {r.status_code} {r.get_data(as_text=True)[:200]}"
    r = c.post("/api/login", json=pass_captcha({
        "username": account["username"],
        "password": account["password"],
    }))
    assert r.status_code == 200, f"登录失败: {r.status_code} {r.get_data(as_text=True)[:200]}"
    return c
