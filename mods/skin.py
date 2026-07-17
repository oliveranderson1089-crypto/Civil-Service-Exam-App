"""外观：头像 / 壁纸。


"""
import os
import secrets

from flask import Blueprint, jsonify, request, send_from_directory

from core import UPLOADS, get_db, log, uid

bp = Blueprint("skin", __name__)


SKIN_DIR = os.path.join(UPLOADS, "skin")
SKIN_KINDS = {                     # 各自的最大边长与用途
    "avatar": 320,                 # 左上角头像
    "wall_app": 2000,              # 应用内壁纸（首页背景）
    "wall_login": 2000,            # 登录/加载页壁纸
}


def _skin_urls(row):
    """把库里存的文件名变成可访问的 URL；没设置就返回空。"""
    out = {}
    for k in SKIN_KINDS:
        fn = (row[k] if row and k in row.keys() else None) or ""
        out[k] = ("/skin/%d/%s" % (row["id"], fn)) if fn else ""
    return out


@bp.get("/api/skin")
def skin_get():
    r = get_db().execute("SELECT id, avatar, wall_app, wall_login FROM users WHERE id=?", (uid(),)).fetchone()
    return jsonify(_skin_urls(r))


@bp.post("/api/skin/<kind>")
def skin_set(kind):
    """上传头像 / 壁纸：统一压成 JPEG（头像保正方形），文件名随机，旧图删掉。"""
    if kind not in SKIN_KINDS:
        return jsonify({"error": "不支持的类型"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择图片"}), 400
    try:
        from PIL import Image, ImageOps
        im = Image.open(f.stream)
        im = ImageOps.exif_transpose(im)           # 手机拍的照片会带旋转信息
        im = im.convert("RGB")
        side = SKIN_KINDS[kind]
        if kind == "avatar":
            im = ImageOps.fit(im, (side, side), Image.LANCZOS)   # 居中裁成正方形
        else:
            im.thumbnail((side, side), Image.LANCZOS)
    except Exception:
        return jsonify({"error": "这不是有效的图片"}), 400

    d = os.path.join(SKIN_DIR, str(uid()))
    os.makedirs(d, exist_ok=True)
    db = get_db()
    old = (db.execute("SELECT %s FROM users WHERE id=?" % kind, (uid(),)).fetchone() or [None])[0]
    fn = "%s-%s.jpg" % (kind, secrets.token_urlsafe(10))         # 文件名不可猜 → 登录页可公开读
    im.save(os.path.join(d, fn), "JPEG", quality=84, optimize=True)
    if old:
        try:
            os.remove(os.path.join(d, old))
        except Exception:
            log.debug("删旧皮肤图失败（残留不影响功能）", exc_info=True)
    db.execute("UPDATE users SET %s=? WHERE id=?" % kind, (fn, uid()))
    db.commit()
    return jsonify({"url": "/skin/%d/%s" % (uid(), fn), "kind": kind})


@bp.delete("/api/skin/<kind>")
def skin_del(kind):
    if kind not in SKIN_KINDS:
        return jsonify({"error": "不支持的类型"}), 400
    db = get_db()
    old = (db.execute("SELECT %s FROM users WHERE id=?" % kind, (uid(),)).fetchone() or [None])[0]
    if old:
        try:
            os.remove(os.path.join(SKIN_DIR, str(uid()), old))
        except Exception:
            log.debug("删旧皮肤图失败（残留不影响功能）", exc_info=True)
    db.execute("UPDATE users SET %s=NULL WHERE id=?" % kind, (uid(),))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/skin/<int:sid>/<path:fname>")
def skin_file(sid, fname):
    """公开可读（文件名随机不可猜）——登录页在没登录时也要显示壁纸。"""
    if "/" in fname or ".." in fname:
        return "", 404
    p = os.path.join(SKIN_DIR, str(sid))
    if not os.path.exists(os.path.join(p, fname)):
        return "", 404
    return send_from_directory(p, fname, max_age=2592000)
