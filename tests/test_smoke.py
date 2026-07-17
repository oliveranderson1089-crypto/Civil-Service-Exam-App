"""烟雾测试：不追覆盖率，只求「改完能一键知道有没有炸」。"""
import sqlite3

import pytest

from conftest import appmod, pass_captcha

# 会打外网 / 调 AI / 跑爬虫 / 生成大文件的，冒烟阶段不碰
SKIP_MARKS = ("/export", "/download", "/refresh", "/crawl", "/ai/", "/aichat",
              "/captcha", "/logout", "/pdf", "/ocr", "/summarize")


def _plain_get_routes():
    out = []
    for r in appmod.app.url_map.iter_rules():
        if "GET" not in r.methods or r.arguments:
            continue
        p = str(r.rule)
        if not p.startswith("/api/") or any(m in p for m in SKIP_MARKS):
            continue
        out.append(p)
    return sorted(out)


class TestInit:
    def test_空库能建起全部表(self):
        n = sqlite3.connect(appmod.DB).execute(
            "select count(*) from sqlite_master where type='table'").fetchone()[0]
        assert n > 50, f"只建了 {n} 张表，init_db() 可能中途被吞了异常"

    def test_关键表都在(self):
        got = {r[0] for r in sqlite3.connect(appmod.DB).execute(
            "select name from sqlite_master where type='table'")}
        for t in ("users", "entries", "annotations", "materials", "notes", "review_state"):
            assert t in got, f"缺表 {t}"


class TestAuth:
    def test_未登录访问受保护接口返回401(self, client):
        r = client.get("/api/me")
        assert r.status_code == 401

    def test_注册后能登录并认得自己(self, auth_client, account):
        r = auth_client.get("/api/me")
        assert r.status_code == 200
        assert r.get_json()["username"] == account["username"]

    def test_首个用户是管理员(self, auth_client):
        assert auth_client.get("/api/me").get_json()["role"] == "admin"

    def test_错密码登不进去(self, flask_app, auth_client, account):
        c = flask_app.test_client()
        r = c.post("/api/login", json=pass_captcha(
            {"username": account["username"], "password": "wrong"}))
        assert r.status_code >= 400

    def test_验证码错了就拒绝(self, flask_app, auth_client, account):
        c = flask_app.test_client()
        r = c.post("/api/login", json={"username": account["username"],
                                       "password": account["password"],
                                       "captcha_id": "nope", "captcha": "zzzz"})
        assert r.status_code == 400


class TestRoutes:
    @pytest.mark.parametrize("path", _plain_get_routes())
    def test_登录后GET不应500(self, auth_client, path):
        r = auth_client.get(path)
        assert r.status_code < 500, \
            f"{path} -> {r.status_code}\n{r.get_data(as_text=True)[:300]}"
