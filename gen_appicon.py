#!/usr/bin/env python3
"""生成应用图标 PNG：一天六个时段各一版（米纸 → 暮色 → 墨）。

为什么要「生成」而不是画一张图片放进来：图标的底色和网页那套日夜渐变是**同一份色表**
（static/js/daylight.js 里的 DL_KEYS）。手工导出的话，两边迟早对不上 —— 改了网页的夜色，
桌面图标还是老的，而且没人会发现。

产物：
  static/icons/gk-<phase>-512.png / -192.png   六个时段，给桌面版按启动时刻挑
  static/icon-512.png / icon-192.png           清单(PWA)和网页用的固定版 = 夜色版
  android/app/src/main/res/drawable/ic_launcher.png   安卓桌面图标 = 夜色版

固定版为什么用夜色：安卓的 launcher 图标是打包死在 APK 里的，换不了；
深色底在浅色和深色壁纸上都有轮廓，米纸底压在浅色壁纸上就化了。

依赖 google-chrome（无头截图）。跑：python3 gen_appicon.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "static" / "icons"

# 和 static/js/daylight.js 的 DL_KEYS 一一对应：改一处就要改另一处，
# 所以两边都写了对方的路径。rim = 底色越暗越需要的一圈内描边（黑壁纸上把图标抠出来）。
# (时段, 底色1, 底色2, 内描边强度, 方章色1, 方章色2)
# 方章始终在品牌蓝这一族里，只挪明度和冷暖 —— 一成不变的蓝压在黄昏的暖底上像贴上去的
PHASES = [
    ("dawn",    "#2a3346", "#1a2438", 1.0,  "#4d86c8", "#22548c"),
    ("morning", "#fdfaf3", "#f0e8d8", 0.0,  "#35a3e2", "#1a6fb5"),
    ("day",     "#fffdf7", "#f3ece0", 0.0,  "#2b8fd6", "#1668ad"),
    ("dusk",    "#f6d9b4", "#c98f6e", 0.15, "#3f9ccb", "#1d6390"),
    ("evening", "#4a4a5e", "#2a3348", 0.7,  "#3f8ac9", "#1b5388"),
    ("night",   "#1c2a44", "#121c2e", 1.0,  "#3d8fd4", "#17548f"),
]
STATIC_PHASE = "night"          # 固定版（清单 / 安卓）用哪一版

HTML = """<!doctype html><meta charset="utf8">
<style>
  html,body{margin:0;padding:0;background:transparent;}
  .ic{width:%(s)dpx;height:%(s)dpx;border-radius:23%%;position:relative;overflow:hidden;
    display:grid;place-items:center;
    background:linear-gradient(155deg,%(c1)s,%(c2)s);
    box-shadow:inset 0 0 0 %(rimw).2fpx rgba(255,255,255,%(rim).3f);}
  .grain{position:absolute;inset:0;mix-blend-mode:soft-light;opacity:%(grain).2f;}
  .seal{position:relative;width:60%%;height:60%%;border-radius:17%%;display:grid;place-items:center;
    color:#fff;font-weight:800;font-size:%(fs).1fpx;line-height:1;
    font-family:"PingFang SC","Noto Sans CJK SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    background:linear-gradient(150deg,%(s1)s,%(s2)s 70%%);
    box-shadow:0 %(sh).1fpx %(shb).1fpx rgba(20,60,110,.30),inset 0 %(hl).1fpx 0 rgba(255,255,255,.35);}
</style>
<div class="ic">
  <svg class="grain"><filter id="g"><feTurbulence type="fractalNoise" baseFrequency="%(bf).2f" numOctaves="3"/>
    <feColorMatrix type="saturate" values="0"/></filter>
  <rect width="100%%" height="100%%" filter="url(#g)"/></svg>
  <div class="seal">公</div>
</div>
"""


def render(c1, c2, rim, s1, s2, size, dest):
    """无头 Chrome 截一张透明底的 PNG。窗口就是图标大小，截出来正好等身。"""
    html = HTML % {
        "s": size, "c1": c1, "c2": c2, "s1": s1, "s2": s2, "rim": 0.16 * rim, "rimw": max(1.0, size / 170),
        # 纸感只在浅色底上有意义：同样的噪点压在墨底上会变成一块块的脏斑，
        # 所以深色版把它调细（频率高）并压到几乎看不见
        "grain": 0.5 if rim < 0.4 else 0.10,
        "bf": 0.85 if rim < 0.4 else 1.6,
        "fs": size * 0.30, "sh": size * 0.04, "shb": size * 0.11, "hl": max(1, size / 300),
    }
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "icon.html"
        src.write_text(html, encoding="utf8")
        shot = Path(td) / "icon.png"
        subprocess.run(
            ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
             "--default-background-color=00000000",
             "--force-device-scale-factor=1",
             "--window-size=%d,%d" % (size, size),
             "--screenshot=%s" % shot, "--virtual-time-budget=1200", str(src)],
            check=True, capture_output=True)
        if not shot.exists():
            sys.exit("Chrome 没吐出 PNG，看看 google-chrome 在不在")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shot, dest)
        return dest.stat().st_size


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, c1, c2, rim, s1, s2 in PHASES:
        for size in (512, 192):
            p = OUT / ("gk-%s-%d.png" % (name, size))
            n = render(c1, c2, rim, s1, s2, size, p)
            print("  %-26s %6d B" % (p.relative_to(ROOT), n))

    # 固定版：清单/网页/安卓都指着这两个文件名，内容换成夜色版
    for size in (512, 192):
        shutil.copyfile(OUT / ("gk-%s-%d.png" % (STATIC_PHASE, size)),
                        ROOT / "static" / ("icon-%d.png" % size))
    android = ROOT / "android/app/src/main/res/drawable/ic_launcher.png"
    if android.exists():
        shutil.copyfile(ROOT / "static/icon-512.png", android)
        print("  安卓 ic_launcher 已更新（%s 版）" % STATIC_PHASE)
    print("完成：%d 个时段 × 2 尺寸 + 固定版" % len(PHASES))


if __name__ == "__main__":
    main()
