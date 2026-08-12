"""分发：安卓 APK / 桌面 deb 下载 + 两端的应用内更新检查。

原先混在「草稿本」区段里——跟草稿本毫无关系，是区段边界漂出来的。
安卓那半（_apk_meta + /api/app/version）一度留在 app.py，跟桌面那半分居两处，
对称的 _apk_meta / _deb_meta 也隔着文件——现在归到一起。
"""
import json
import os
import re

from flask import Blueprint, jsonify, send_file

from core import BASE, STATIC

bp = Blueprint("dist", __name__)


def _deb_meta():
    """从 dist/deb.json 读桌面版发布信息（build_deb.sh 生成）。"""
    p = os.path.join(BASE, "dist", "deb.json")
    try:
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}

def _win_meta():
    """从 dist/win.json 读 Windows 桌面版发布信息（desktop/win/build_win.sh 生成）。"""
    p = os.path.join(BASE, "dist", "win.json")
    try:
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def _win_pkg():
    """Windows 装哪个包：有安装版就发安装版，只有便携版就发便携版（zip 解压即用）。
       返回 (绝对路径, 下载路径)；两个都没有就 (None, "")。"""
    for name, url in (("gongkao-setup.exe", "/download/gongkao-setup.exe"),
                      ("gongkao-win.zip", "/download/gongkao-win.zip")):
        f = os.path.join(BASE, "dist", name)
        if os.path.exists(f):
            return f, url
    return None, ""


def _sw_version():
    """读 static/sw.js 里的前端缓存版本号（gongkao-vNN），用于判断网页端有没有更新。"""
    try:
        with open(os.path.join(STATIC, "sw.js"), encoding="utf-8") as fp:
            m = re.search(r"gongkao-v(\d+)", fp.read())
            return "gongkao-v" + m.group(1) if m else ""
    except Exception:
        return ""


@bp.get("/api/desktop/version")
def desktop_version():
    """桌面版启动/手动检查更新时来问：前端有没有更新(刷新即可)、桌面壳有没有新版(需重下)。"""
    deb = os.path.join(BASE, "dist", "gongkao.deb")
    meta = _deb_meta()
    wmeta = _win_meta()
    wpkg, wurl = _win_pkg()
    return jsonify({
        "sw": _sw_version(),                                  # 当前网页端版本；和启动时不同 → 刷新即更新
        "deb_code": int(meta.get("version_code") or 0),       # 桌面壳版本；比本机新 → 需重新下载 .deb
        "deb_name": meta.get("version_name") or "",
        "deb_notes": meta.get("notes") or "",
        "deb_size": os.path.getsize(deb) if os.path.exists(deb) else 0,
        "deb_url": "/download/gongkao.deb",
        "deb_available": os.path.exists(deb),
        # Windows 壳。⚠️ deb_* 保持原样单独列一套：老版本的 Linux 壳只认 deb_*，
        # 把字段改成通用名会让所有已装的 Linux 客户端**再也收不到更新提示**。
        "win_code": int(wmeta.get("version_code") or 0),
        "win_name": wmeta.get("version_name") or "",
        "win_notes": wmeta.get("notes") or "",
        "win_size": os.path.getsize(wpkg) if wpkg else 0,
        "win_url": wurl,
        "win_available": bool(wpkg),
    })


@bp.get("/apk")
@bp.get("/download/gongkao.apk")
def download_apk():
    apk = os.path.join(BASE, "dist", "gongkao.apk")
    if not os.path.exists(apk):
        return "APK 尚未构建", 404
    return send_file(apk, mimetype="application/vnd.android.package-archive",
                     as_attachment=True, download_name="gongkao.apk")


@bp.get("/deb")
@bp.get("/download/gongkao.deb")
def download_deb():
    """电脑桌面版（Linux .deb）。"""
    deb = os.path.join(BASE, "dist", "gongkao.deb")
    if not os.path.exists(deb):
        return "桌面版尚未构建", 404
    return send_file(deb, mimetype="application/vnd.debian.binary-package",
                     as_attachment=True, download_name="gongkao.deb")


def _send_win(pkg):
    if not pkg or not os.path.exists(pkg):
        return "Windows 版尚未构建", 404
    return send_file(pkg,
                     mimetype="application/zip" if pkg.endswith(".zip")
                     else "application/vnd.microsoft.portable-executable",
                     as_attachment=True, download_name=os.path.basename(pkg))


@bp.get("/win")
def download_win():
    """电脑桌面版（Windows）。下载页那个按钮走这里：有安装版发安装版，否则发便携版。"""
    pkg, _url = _win_pkg()
    return _send_win(pkg)


# 两个具体文件名各发各的：更新提示里给的是 win_url（具体到文件），
# 要是这里也跟着「有哪个发哪个」，点便携版的链接会下到安装版 —— 名不副实。
@bp.get("/download/gongkao-setup.exe")
def download_win_setup():
    return _send_win(os.path.join(BASE, "dist", "gongkao-setup.exe"))


@bp.get("/download/gongkao-win.zip")
def download_win_zip():
    return _send_win(os.path.join(BASE, "dist", "gongkao-win.zip"))


def _apk_meta():
    """从 dist/apk.json 读当前发布的版本信息（构建脚本生成）。"""
    p = os.path.join(BASE, "dist", "apk.json")
    try:
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


@bp.get("/api/app/version")
def app_version():
    """APP 启动时来问一次：有没有新版本。"""
    apk = os.path.join(BASE, "dist", "gongkao.apk")
    meta = _apk_meta()
    return jsonify({
        "version_code": int(meta.get("version_code") or 0),
        "version_name": meta.get("version_name") or "",
        "notes": meta.get("notes") or "",
        "size": os.path.getsize(apk) if os.path.exists(apk) else 0,
        "url": "/download/gongkao.apk",
        "available": os.path.exists(apk),
    })
