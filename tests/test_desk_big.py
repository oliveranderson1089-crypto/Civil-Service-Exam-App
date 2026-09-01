"""桌面壳的大文件通道：三份源码里手抄的同一批常量，别让它们走散。

桌面壳里拖进来的大文件走的是「网页按需向壳要一片」的路（见 static/js/desktop.js 顶上
那段协议注释）。这条路上的数字被抄了三份 —— 后端 mods/social.py、Linux 壳
desktop/gongkao_native.py、Windows 壳 desktop/win/files.js —— 抄本走散的后果很具体：

  · 壳的上限比服务端大：壳兴冲冲把 3GB 的文件推给网页，chunk/init 一句
    「文件超过 2048 MB」当场拒收，用户看到的是传了半天才失败；
  · 两个壳不一样大：同一个文件在 Windows 上传得上、在 Linux 上传不上；
  · 片大小和网页的 DV_CHUNK 不一致：网页要 [0,4M) 而壳按别的粒度读，
    多出来的字节要么白读要么对不上。

所以这里不测「功能对不对」（那是 tests/frontend/deskbig.test.js 的事），只钉住这几个
数字之间的关系。
"""
import os
import re

from mods import social

DESK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop")
NATIVE = os.path.join(DESK, "gongkao_native.py")
WIN = os.path.join(DESK, "win", "files.js")
WEB = os.path.join(os.path.dirname(DESK), "static", "js", "drive.js")


def _read(p):
    with open(p, encoding="utf-8") as fp:
        return fp.read()


def _const(src, name):
    """抠出 `名字 = 2 * 1024 * 1024 * 1024` 这种一眼能算的常量，算成字节数。"""
    m = re.search(r"^\s*(?:const\s+)?%s\s*=\s*([\d\s*]+?)\s*;?\s*(?://|#|$)" % name, src, re.M)
    assert m, "%s 没找到了 —— 是不是改名了？" % name
    return eval(m.group(1))                     # 只可能是数字和 *，来源是本仓库的源码


def test_两个壳的大文件上限一样():
    linux = _const(_read(NATIVE), "DESK_BIG_MAX")
    win = _const(_read(WIN), "BIG_MAX")
    assert linux == win, "同一个文件在 Windows 上传得上、在 Linux 上传不上"
    assert linux == 2 * 1024 * 1024 * 1024, "大文件上限不再是 2GB —— 文档和提示语也得跟着改"


def test_壳不许承诺比服务端更大():
    """壳放行了、服务端拒收，用户看到的是「传了半天才失败」。"""
    linux = _const(_read(NATIVE), "DESK_BIG_MAX")
    assert linux <= social.BIG_MAX, (
        "壳的上限（%d MB）超过了分片通道的 BIG_MAX（%d MB，config.json 的 drive_big_max_mb）"
        % (linux // (1024 * 1024), social.BIG_MAX // (1024 * 1024)))


def test_壳读的片和网页要的片一样大():
    """网页按 DV_CHUNK 切片、按 [start,len) 向壳要，壳一次读多少必须对得上。"""
    web = _const(_read(WEB), "DV_CHUNK")
    linux = _const(_read(NATIVE), "DESK_PART")
    assert linux == web, "壳读的片和网页切的片不一样大"
    # 上限是防御性的：网页要多少都不该让壳读出一个大内存块来
    assert _const(_read(NATIVE), "DESK_PART_MAX") >= web
    assert _const(_read(WIN), "PART_MAX") >= web


def test_大文件走的是分片而不是整发那条路():
    """整发那条路的上限（DRIVE_MAX）比分片小得多，大文件必须走分片。"""
    assert social.BIG_MAX > social.DRIVE_MAX
    assert _const(_read(NATIVE), "DESK_BIG_MAX") > _const(_read(NATIVE), "DESK_MAX_FILE"), \
        "大文件的上限还没有 base64 桥那条路大，等于这条通道白开"


def test_两个壳和网页说的是同一套暗号():
    """协议是三方共享的字符串，少一个动作就是一方永远等不到回音。"""
    # Windows 侧分两半：动作名在 main.js 的分发表里，读盘在 files.js
    native = _read(NATIVE)
    win = _read(WIN) + _read(os.path.join(DESK, "win", "main.js"))
    web = _read(os.path.join(os.path.dirname(WEB), "desktop.js"))
    for act in ("bigpart", "bigdone"):
        assert act in native and act in win and act in web, "动作 %s 有一方不认" % act
    for fn in ("__onBigFile", "__deskBigPart", "__deskBigFail"):
        assert fn in native and fn in win and fn in web, "%s 有一方不认" % fn
