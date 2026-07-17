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
    return jsonify({
        "sw": _sw_version(),                                  # 当前网页端版本；和启动时不同 → 刷新即更新
        "deb_code": int(meta.get("version_code") or 0),       # 桌面壳版本；比本机新 → 需重新下载 .deb
        "deb_name": meta.get("version_name") or "",
        "deb_notes": meta.get("notes") or "",
        "deb_size": os.path.getsize(deb) if os.path.exists(deb) else 0,
        "deb_url": "/download/gongkao.deb",
        "deb_available": os.path.exists(deb),
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
