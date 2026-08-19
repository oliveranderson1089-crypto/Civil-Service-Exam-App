"""资料库：上传 / 查看 / 逐页出图 / 共享 / 自定义分类。

路由原先散在四个区段里，其中「幻灯片播放」那段装的其实是 materials 的
CRUD（改名/删除/复制/下载）——又一处区段注释名不副实。按实际归到一处。

文件处理（OCR/转 PDF/抽文本）已经在 mods/files.py，这里只剩资料库自己的事。
"""
import json
import os
import re
import shutil
import subprocess
import uuid

from flask import Blueprint, Response, jsonify, request, send_file

from core import SECTIONS, UPLOADS, get_db, log, uid
from mods.files import (INLINE_EXT, OFFICE_EXT, TEXT_EXT, _cacheable,
                        _extract_text, _no_script, _office_to_pdf, _remove_blob,
                        _remove_file, _user_dir)

bp = Blueprint("materials", __name__)


# ---- 资料库 ----
def finish_material_upload(db, tmp, name, board, title, mime):
    """分片通道传完的临时文件 → 资料库的一行。

    云盘和资料库共用 mods/social.py 那条 chunk 通道（init → 每片 → done），
    done 按会话里记的 target 决定落到哪边，落资料库就走这里。
    返回 (行字典, None) 或 (None, (json响应, 状态码))。
    """
    ext = os.path.splitext(name)[1].lower()
    stored = uuid.uuid4().hex + ext
    dst = os.path.join(_user_dir(uid()), stored)
    try:
        # 分片是在 uploads/drive/<id>/ 底下拼的，和资料库同一个文件系统，能直接 rename；
        # 万一不是（有人把 drive 挂到别处），退回复制再删。
        os.replace(tmp, dst)
    except OSError:
        shutil.copyfile(tmp, dst)
        _remove_blob(tmp)
    size = os.path.getsize(dst)
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), "", (board or "")[:20], title or name, name, stored, ext, mime or "", size))
    db.commit()
    return dict(db.execute("SELECT * FROM materials WHERE id=?", (cur.lastrowid,)).fetchone()), None


@bp.post("/api/materials")
def material_upload():
    section = (request.form.get("section") or "").strip()
    board = (request.form.get("board") or "").strip()
    title = (request.form.get("title") or "").strip()
    # 板块支持自定义分类（如「晨读」），不再限定固定板块
    if len(board) > 20:
        return jsonify({"error": "分类名太长"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    orig = f.filename
    ext = os.path.splitext(orig)[1].lower()
    stored = uuid.uuid4().hex + ext
    path = os.path.join(_user_dir(uid()), stored)
    f.save(path)
    size = os.path.getsize(path)
    db = get_db()
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), section, board, title or orig, orig, stored, ext, f.mimetype or "", size))
    db.commit()
    row = db.execute("SELECT * FROM materials WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@bp.get("/api/materials/boards")
def material_boards():
    """分类 = 已有资料反推出来的 + 用户自己存下来的 + 固定板块。
       只反推的话，新建了但还没往里传东西的分类（如「其它」）重启就没了 —— 这正是踩过的坑。

    items 比 boards 多两样东西：**这个分类下有几份资料**，以及**按「用得多 + 最近用」排好的
    顺序**。分类攒到十几个之后全平铺在顶上就没法用了（手机上得横着划找），前端据此只把前
    几个摆在外面、其余收进「更多」面板。

    排序为什么要带上「最近」：份数相同的分类不少（这库里 1 份的就有三个），只按份数排，它们
    就退化成建库顺序（最老的排最前），正好是最没用的一头。份数一样就看最近传的那份资料是哪
    条，手头正在攒的那个分类自然浮上来。

    排序放服务端做：同一份口径前后端各排一次，迟早会不一致（小记那边同理，见 mods/notes.py）。
    """
    db = get_db()
    rows = db.execute(
        "SELECT board, COUNT(*) n, MAX(id) last FROM materials "
        "WHERE user_id=? AND board<>'' GROUP BY board", (uid(),)).fetchall()
    stat = {r["board"]: (r["n"], r["last"]) for r in rows}
    custom = []
    r = db.execute("SELECT mat_boards FROM users WHERE id=?", (uid(),)).fetchone()
    try:
        custom = [b for b in json.loads((r["mat_boards"] if r else None) or "[]") if b]
    except Exception:
        log.warning("用户 mat_boards 不是合法 JSON，自定义分类会丢", exc_info=True)
    # 固定板块也要在册：一份资料都没有的板块（如「数量关系」）前端要拿它当上传时的去处，
    # 只是排在后面、收进面板里，不占外面那一行。SECTIONS 而不是 ALL_BOARDS —— 后者是
    # set，顺序每次进程都可能不一样，空板块之间的次序就会跳。
    fixed = [b for s in SECTIONS for b in s["boards"]]
    order, seen = [], set()
    for b in list(stat) + custom + fixed:
        if b not in seen:
            seen.add(b)
            order.append(b)
    items = sorted(
        ({"board": b, "n": stat.get(b, (0, 0))[0], "last": stat.get(b, (0, 0))[1],
          "custom": b not in fixed} for b in order),
        key=lambda x: (-x["n"], -x["last"]))
    return jsonify({"boards": [x["board"] for x in items], "items": items})


@bp.get("/api/materials")
def material_list():
    board = (request.args.get("board") or "").strip()
    db = get_db()
    # 自己的 + 队友共享给我的（共享来的标 shared_from，不能改不能删）
    sql = ("SELECT m.*, 0 AS shared, '' AS shared_from FROM materials m WHERE m.user_id=?"
           + (" AND m.board=?" if board else "")
           + " UNION ALL "
           + "SELECT m.*, 1 AS shared, u.username AS shared_from FROM materials m "
             "JOIN material_shares s ON s.material_id=m.id "
             "JOIN users u ON u.id=m.user_id WHERE s.to_user=?"
           + (" AND m.board=?" if board else "")
           + " ORDER BY id DESC")
    args = [uid()] + ([board] if board else []) + [uid()] + ([board] if board else [])
    rows = db.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["viewable"] = (r["ext"] in INLINE_EXT) or (r["ext"] in OFFICE_EXT)
        out.append(d)
    return jsonify({"items": out})


def _get_material(mid):
    """自己的资料，或队友共享给我的（共享来的只读：查看/下载可以，改名删除不行）。"""
    return get_db().execute(
        "SELECT m.* FROM materials m WHERE m.id=? AND ("
        "  m.user_id=? OR EXISTS(SELECT 1 FROM material_shares s "
        "                        WHERE s.material_id=m.id AND s.to_user=?))",
        (mid, uid(), uid())).fetchone()


@bp.get("/api/materials/<int:mid>/text")
def material_text(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    t = _extract_text(os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"]), m["ext"])
    if t is None:
        return jsonify({"error": "文件丢失"}), 404
    return jsonify({"text": t})


# 朗读 TTS polyfill：APK 内（有 GongkaoNative 桥）用 Android TTS 实现 window.speechSynthesis，
# 让上传 HTML 里现成的朗读代码无需改动即可发声；普通浏览器不注入、保留原生。
# 注入到 <head> 最前，早于页面脚本执行；回调经 window.top 中转以支持 iframe 内的资料页。
_TTS_POLYFILL = """<script>(function(){
if(!(window.GongkaoNative&&window.GongkaoNative.ttsSpeak))return;
var T=window.top||window;
if(!T.__ttsReg){T.__ttsReg={};T.__ttsEvent=function(id,ev){var u=T.__ttsReg[id];if(!u)return;if(ev==='end'){delete T.__ttsReg[id];if(u.__sp)u.__sp.speaking=false;if(typeof u.onend==='function'){try{u.onend({});}catch(e){}}}};}
function U(t){this.text=t||'';this.rate=1;this.pitch=1;this.volume=1;this.lang='zh-CN';this.onend=null;this.onstart=null;this.onerror=null;this.onboundary=null;this._id='u'+Date.now()+'_'+Math.floor(Math.random()*1e6);this.__sp=null;}
var SP={speaking:false,pending:false,paused:false,
speak:function(u){if(!u||!u.text)return;u.__sp=this;T.__ttsReg[u._id]=u;this.speaking=true;if(typeof u.onstart==='function'){try{u.onstart({});}catch(e){}}try{window.GongkaoNative.ttsSpeak(u._id,String(u.text),u.rate||1);}catch(e){this.speaking=false;if(typeof u.onend==='function'){try{u.onend({});}catch(_){}}}},
cancel:function(){this.speaking=false;T.__ttsReg={};try{window.GongkaoNative.ttsCancel();}catch(e){}},
pause:function(){},resume:function(){},getVoices:function(){return[];}};
window.SpeechSynthesisUtterance=U;window.speechSynthesis=SP;
})();</script>"""


def _inject_tts(html_txt):
    low = html_txt.lower()
    for tag in ("<head", "<html"):
        i = low.find(tag)
        if i >= 0:
            j = html_txt.find(">", i)
            if j >= 0:
                return html_txt[:j + 1] + _TTS_POLYFILL + html_txt[j + 1:]
    return _TTS_POLYFILL + html_txt


def _linearized(pdf):
    """线性化（Fast Web View）：xref 前置，配合 Range 让阅读器先出首页再拉后面。
    服务器在家里、上行只有一百多 KB/s，这个优化对大 PDF 是决定性的。"""
    web = os.path.splitext(pdf)[0] + ".web.pdf"
    if os.path.exists(web) and os.path.getmtime(web) >= os.path.getmtime(pdf):
        return web
    try:
        subprocess.run(["qpdf", "--linearize", pdf, web], timeout=180, capture_output=True)
    except Exception:
        return pdf
    return web if os.path.exists(web) and os.path.getsize(web) > 0 else pdf


def _material_pdf(m, path):
    """拿到这份资料对应的 PDF（office 先转换），失败返回 None。"""
    if m["ext"] == ".pdf":
        return path
    if m["ext"] in OFFICE_EXT:
        return _office_to_pdf(path)
    return None


@bp.get("/api/materials/<int:mid>/view")
def material_view(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    ext = m["ext"]
    if ext in OFFICE_EXT:
        pdf = _office_to_pdf(path)
        if not pdf:
            return "文档转换失败，请下载查看", 500
        return _cacheable(_no_script(send_file(_linearized(pdf), mimetype="application/pdf", as_attachment=False)))
    if ext in (".html", ".htm"):
        with open(path, "rb") as fp:
            html_txt = fp.read().decode("utf-8", "ignore")
        return Response(_inject_tts(html_txt), mimetype="text/html; charset=utf-8")
    if ext in TEXT_EXT:
        with open(path, "rb") as fp:
            return Response(fp.read(), mimetype="text/plain; charset=utf-8")
    if ext == ".pdf":
        return _cacheable(_no_script(send_file(_linearized(path), mimetype="application/pdf",
                                               as_attachment=False, download_name=m["orig_name"])))
    # 图片等：浏览器内联打开
    return _cacheable(_no_script(send_file(path, as_attachment=False, download_name=m["orig_name"])))


# ---- 幻灯片播放（PPT/PDF 逐页出图） ----
def _pages_dir(m):
    d = os.path.join(UPLOADS, str(uid()), ".pages", os.path.splitext(m["stored_name"])[0])
    os.makedirs(d, exist_ok=True)
    return d


@bp.get("/api/materials/<int:mid>/pages")
def material_pages(mid):
    """返回总页数；PPT/PDF 才支持幻灯片播放。"""
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    pdf = _material_pdf(m, path) if os.path.exists(path) else None
    if not pdf:
        return jsonify({"pages": 0, "slides": False})
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, timeout=60)
        txt = out.stdout.decode("utf-8", "ignore")
        n = int(re.search(r"Pages:\s+(\d+)", txt).group(1))
    except Exception:
        return jsonify({"pages": 0, "slides": False})
    return jsonify({"pages": n, "slides": True,
                    "ppt": m["ext"] in (".ppt", ".pptx", ".odp")})


@bp.get("/api/materials/<int:mid>/page/<int:n>")
def material_page(mid, n):
    """单页渲染成 JPEG（约 100~200KB），比整份 PDF 小两个数量级，首屏立刻可见。"""
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    if n < 1 or n > 3000:
        return "页码越界", 400
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    pdf = _material_pdf(m, path)
    if not pdf:
        return "该格式不支持逐页预览", 400
    dpi = 110 if request.args.get("hd") else 90
    cache = os.path.join(_pages_dir(m), "p%04d_%d.jpg" % (n, dpi))
    if not os.path.exists(cache):
        prefix = cache[:-4]
        try:
            subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=72",
                            "-r", str(dpi), "-f", str(n), "-l", str(n),
                            "-singlefile", pdf, prefix],
                           check=True, timeout=120, capture_output=True)
        except Exception:
            return "渲染失败", 500
    if not os.path.exists(cache):
        return "页码超出范围", 404
    return _cacheable(send_file(cache, mimetype="image/jpeg"))


@bp.get("/api/materials/<int:mid>/download")
def material_download(mid):
    m = _get_material(mid)
    if not m:
        return "未找到", 404
    path = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(path):
        return "文件丢失", 404
    return send_file(path, as_attachment=True, download_name=m["orig_name"])


@bp.put("/api/materials/<int:mid>")
def material_update(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "名称不能为空"}), 400
    db = get_db()
    if "board" in data:
        board = (data.get("board") or "").strip()
        if len(board) > 20:
            return jsonify({"error": "分类名太长"}), 400
        db.execute("UPDATE materials SET title=?, board=? WHERE id=? AND user_id=?",
                   (title, board, mid, uid()))
    else:
        db.execute("UPDATE materials SET title=? WHERE id=? AND user_id=?", (title, mid, uid()))
    db.commit()
    return jsonify({"ok": True})


@bp.post("/api/materials/<int:mid>/duplicate")
def material_duplicate(mid):
    import shutil
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    src = os.path.join(UPLOADS, str(m["user_id"]), m["stored_name"])
    if not os.path.exists(src):
        return jsonify({"error": "源文件丢失"}), 404
    ext = m["ext"] or ""
    stored = uuid.uuid4().hex + ext
    dst = os.path.join(_user_dir(uid()), stored)
    shutil.copy2(src, dst)
    title = (m["title"] or m["orig_name"] or "文档") + " 副本"
    db = get_db()
    cur = db.execute(
        "INSERT INTO materials(user_id,section,board,title,orig_name,stored_name,ext,mime,size) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid(), m["section"], m["board"], title, m["orig_name"], stored, ext,
         m["mime"], os.path.getsize(dst)))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM materials WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.delete("/api/materials/<int:mid>")
def material_delete(mid):
    m = _get_material(mid)
    if not m:
        return jsonify({"error": "未找到"}), 404
    if m["user_id"] != uid():          # 共享给我的只读：能看能下，不能删（否则会把别人的文件删了）
        return jsonify({"error": "这是队友共享给你的资料，不能删除"}), 403
    _remove_file(uid(), m["stored_name"])
    get_db().execute("DELETE FROM materials WHERE id=?", (mid,))
    get_db().commit()
    return jsonify({"ok": True})


# ---- 资料库：自定义分类 ----
@bp.post("/api/materials/boards")
def mat_boards_set():
    d = request.get_json(silent=True) or {}
    boards = [str(x).strip()[:20] for x in (d.get("boards") or []) if str(x).strip()][:30]
    db = get_db()
    db.execute("UPDATE users SET mat_boards=? WHERE id=?", (json.dumps(boards, ensure_ascii=False), uid()))
    db.commit()
    return jsonify({"ok": True, "boards": boards})


# ---- 资料库：共享给指定成员 ----
@bp.get("/api/materials/<int:mid>/share")
def mat_share_get(mid):
    """能共享给谁：我的队友。顺带返回已经共享给了谁。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM materials WHERE id=? AND user_id=?", (mid, uid())).fetchone():
        return jsonify({"error": "只能共享自己的资料"}), 403
    mates = db.execute(
        "SELECT u.id, u.username FROM team_members m1 "
        "JOIN team_members m2 ON m2.team_id=m1.team_id AND m2.user_id!=m1.user_id "
        "JOIN users u ON u.id=m2.user_id WHERE m1.user_id=?", (uid(),)).fetchall()
    shared = {r["to_user"] for r in db.execute(
        "SELECT to_user FROM material_shares WHERE material_id=?", (mid,))}
    return jsonify({"members": [{"id": r["id"], "username": r["username"],
                                 "shared": r["id"] in shared} for r in mates]})


@bp.post("/api/materials/<int:mid>/share")
def mat_share_set(mid):
    """整份覆盖：传 to=[用户id...]，没在里面的就取消共享。"""
    db = get_db()
    if not db.execute("SELECT 1 FROM materials WHERE id=? AND user_id=?", (mid, uid())).fetchone():
        return jsonify({"error": "只能共享自己的资料"}), 403
    to = (request.get_json(silent=True) or {}).get("to") or []
    mates = {r["id"] for r in db.execute(
        "SELECT u.id FROM team_members m1 "
        "JOIN team_members m2 ON m2.team_id=m1.team_id AND m2.user_id!=m1.user_id "
        "JOIN users u ON u.id=m2.user_id WHERE m1.user_id=?", (uid(),))}
    to = [int(x) for x in to if int(x) in mates]        # 只能共享给队友，防越权
    db.execute("DELETE FROM material_shares WHERE material_id=?", (mid,))
    for t in to:
        db.execute("INSERT OR IGNORE INTO material_shares(material_id,owner_id,to_user) VALUES(?,?,?)",
                   (mid, uid(), t))
    db.commit()
    return jsonify({"ok": True, "n": len(to)})

