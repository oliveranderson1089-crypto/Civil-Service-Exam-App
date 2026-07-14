#!/usr/bin/python3
# 公考助手 桌面版（原生 GTK + 系统 WebKit2GTK，不依赖 Chrome）。
# 用系统 python3（自带 gi）运行；一个真·原生窗口加载网页版。
import base64
import json
import os
import secrets
import shutil
import subprocess
from shlex import quote as shlex_quote
from urllib.parse import urlparse

# 中文输入法：GTK3 要靠 im module 才能弹候选框。从桌面菜单启动时环境可能是空的，
# 这里兜个底（系统里装的是 fcitx5）。必须在 import gi / Gtk 初始化之前设。
os.environ.setdefault("GTK_IM_MODULE", "fcitx")
os.environ.setdefault("XMODIFIERS", "@im=fcitx")
os.environ.setdefault("QT_IM_MODULE", "fcitx")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, GLib, Gio, Gdk  # noqa: E402

APP_ID = "com.gongkao.app"
DESKTOP_VER = "3.9"          # 桌面壳版本；改动壳本身时+1，网页据此判断「需重新下载」
TUNNEL = "https://gk.gongkaopei2026.click"
APP_HOSTS = {"gk.gongkaopei2026.click", "127.0.0.1", "localhost"}
ICONS = ["/usr/share/icons/hicolor/512x512/apps/gongkao-assistant.png",
         "/usr/share/icons/hicolor/256x256/apps/gongkao-assistant.png"]
# edge-tts 可选音色（白名单：网页传来的值要拼进 shell，不能放任）
EDGE_VOICES = ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural",
               "zh-CN-XiaoyiNeural", "zh-CN-YunjianNeural"]


def resolve_url():
    u = (os.environ.get("GONGKAO_URL") or "").strip()
    if u:
        return u
    try:                       # 本机在跑服务就用 localhost（更快），否则走公网隧道
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8011/", timeout=1)
        return "http://127.0.0.1:8011"
    except Exception:
        return TUNNEL


GLib.set_prgname("gongkao-assistant")
GLib.set_application_name("公考助手")


class Gongkao(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win:
            self.win.present()
            return
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title("公考助手")
        self.win.set_default_size(1120, 800)
        for p in ICONS:
            if os.path.exists(p):
                try:
                    self.win.set_icon_from_file(p)
                except Exception:
                    pass
                break
        try:
            self.win.set_wmclass("gongkao-assistant", "公考助手")
        except Exception:
            pass

        # 持久化：cookie/登录、localStorage、Service Worker 缓存跨启动保留
        data = os.path.join(GLib.get_user_data_dir(), "gongkao-assistant")
        cache = os.path.join(GLib.get_user_cache_dir(), "gongkao-assistant")
        os.makedirs(data, exist_ok=True)
        os.makedirs(cache, exist_ok=True)
        dm = WebKit2.WebsiteDataManager(base_data_directory=data, base_cache_directory=cache)
        ctx = WebKit2.WebContext.new_with_website_data_manager(dm)
        try:
            ctx.get_cookie_manager().set_persistent_storage(
                os.path.join(data, "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
        except Exception:
            pass

        # 注入「我是桌面版 + 版本号 + 有没有系统朗读」，网页端据此走对应实现
        ucm = WebKit2.UserContentManager()
        self.tts_ok = bool(self._tts_engines())        # WebKit 没有 speechSynthesis，只能借系统
        try:
            ucm.add_script(WebKit2.UserScript.new(
                "window.__desktop=true;window.__desktopVer='%s';window.__desktopTTS=%s;"
                "window.__desktopShot=true;window.__ttsEngines=%s;"
                % (DESKTOP_VER, "true" if self.tts_ok else "false",
                   json.dumps(list(self._tts_engines().keys()))),
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START, None, None))
            ucm.register_script_message_handler("gk")   # 网页 → 壳 的桥
            ucm.connect("script-message-received::gk", self.on_msg)
        except Exception:
            pass
        # 下载（更新用的 .deb、导出的文件等）默认存到「下载」文件夹
        try:
            ctx.connect("download-started", self.on_download)
        except Exception:
            pass

        self.web = WebKit2.WebView(web_context=ctx, user_content_manager=ucm)
        try:
            self.web.get_settings().set_property("enable-developer-extras", False)
        except Exception:
            pass
        self.web.connect("decide-policy", self.on_decide)
        self.web.connect("run-file-chooser", self.on_file_chooser)   # 自己弹文件框，见下
        self.web.connect("context-menu", self.on_context_menu)       # 右键菜单加「粘贴图片」

        # 拖放：WebKitGTK 的 drop 事件里 dataTransfer.files 是空的（dragover 有效、drop 拿不到文件），
        # 所以从 GTK 这一层接管：自己收 uri-list，读出文件内容交给网页。
        # ⚠️ WebView 自己也注册了拖放目标，必须先 unset 掉，否则 drop 被它先吃掉，我们的回调根本不触发。
        self.web.drag_dest_unset()
        self.web.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.DROP,
                               [Gtk.TargetEntry.new("text/uri-list", 0, 0),
                                Gtk.TargetEntry.new("text/plain", 0, 1)], Gdk.DragAction.COPY)
        self.web.connect("drag-motion", self.on_drag_motion)
        self.web.connect("drag-leave", self.on_drag_leave)
        self.web.connect("drag-drop", self.on_drag_drop)
        self.web.connect("drag-data-received", self.on_drag_data)
        self.web.load_uri(resolve_url())
        self.win.add(self.web)
        self.win.connect("key-press-event", self.on_key)   # F5 刷新等快捷键
        self.win.show_all()

    def on_key(self, widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        kv = event.keyval
        if kv == Gdk.KEY_F5 or (ctrl and kv in (Gdk.KEY_r, Gdk.KEY_R)):
            if shift:
                self.web.reload_bypass_cache()   # 强制刷新，绕缓存
            else:
                self.web.reload()                # 刷新（和浏览器 F5 一样）
            return True
        # Ctrl+V：剪贴板里是图片就自己接手（WebKit 往输入框粘图是粘不进去的，它只认文字）；
        # 是文字就放行，让 WebKit 正常粘贴。
        if ctrl and not shift and kv in (Gdk.KEY_v, Gdk.KEY_V):
            if self.paste_image():
                return True
            return False
        if ctrl and kv in (Gdk.KEY_q, Gdk.KEY_Q):
            self.quit()
            return True
        if ctrl and kv in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.web.set_zoom_level(self.web.get_zoom_level() + 0.1)
            return True
        if ctrl and kv in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.web.set_zoom_level(max(0.4, self.web.get_zoom_level() - 0.1))
            return True
        if ctrl and kv in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.web.set_zoom_level(1.0)
            return True
        return False

    def on_file_chooser(self, web, req):
        """自己弹文件选择框。
           WebKit 默认会把网页 accept 里混着的 image/* 和 .pdf/.docx 过滤成「只剩图片」——
           上传真题时就只能选图片了。这里按用途给全套过滤器，并默认停在「支持的文件」上。"""
        dlg = Gtk.FileChooserDialog(title="选择文件", transient_for=self.win,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("取消", Gtk.ResponseType.CANCEL, "打开", Gtk.ResponseType.ACCEPT)
        try:
            dlg.set_select_multiple(req.get_select_multiple())
        except Exception:
            pass

        def mk(name, patterns):
            f = Gtk.FileFilter()
            f.set_name(name)
            for p in patterns:
                f.add_pattern(p)
            return f

        docs = ["*.pdf", "*.doc", "*.docx", "*.ppt", "*.pptx", "*.txt", "*.md", "*.html", "*.htm"]
        imgs = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.bmp", "*.heic"]
        dlg.add_filter(mk("支持的文件（文档 + 图片）", docs + imgs))
        dlg.add_filter(mk("文档（PDF / Word / PPT / 文本）", docs))
        dlg.add_filter(mk("图片", imgs))
        dlg.add_filter(mk("所有文件", ["*"]))

        if dlg.run() == Gtk.ResponseType.ACCEPT:
            req.select_files(dlg.get_filenames())
        else:
            req.cancel()
        dlg.destroy()
        return True

    # ---------------- 拖放：GTK 层接管（WebKit 的 drop 给不到文件） ----------------
    def on_drag_motion(self, widget, ctx, x, y, time):
        Gdk.drag_status(ctx, Gdk.DragAction.COPY, time)
        self._js("window.__onDragOver && window.__onDragOver()")     # 页面自己画高亮
        return True

    def on_drag_leave(self, widget, ctx, time):
        self._js("window.__onDragLeave && window.__onDragLeave()")

    def on_drag_drop(self, widget, ctx, x, y, time):
        """松手：主动去要 uri-list 数据（要到了才会触发 drag-data-received）。"""
        target = None
        for t in ctx.list_targets():
            if t.name() == "text/uri-list":
                target = t
                break
        if target is None:
            return False
        widget.drag_get_data(ctx, target, time)
        return True

    def on_drag_data(self, widget, ctx, x, y, data, info, time):
        files = []
        for uri in (data.get_uris() or [])[:10]:
            try:
                p = GLib.filename_from_uri(uri)[0]
            except Exception:
                continue
            if not p or not os.path.isfile(p) or os.path.getsize(p) > 60 * 1024 * 1024:
                continue
            with open(p, "rb") as f:
                files.append({"name": os.path.basename(p),
                              "data": base64.b64encode(f.read()).decode()})
        Gtk.drag_finish(ctx, bool(files), False, time)
        self._js("window.__onDragLeave && window.__onDragLeave()")
        if files:
            self._js("window.__onDropFiles && window.__onDropFiles(%s)"
                     % json.dumps(files, ensure_ascii=False))
        else:
            self._toast("这些东西读不出文件（只支持本地文件）")

    # ---------------- 剪贴板里的图片：Ctrl+V / 右键粘贴 ----------------
    def _clip_image_b64(self):
        """剪贴板里有图就返回 PNG 的 base64；没有返回 None。
           WebKit 往 <textarea> 里粘图是粘不进去的（它只认文字），所以得从 GTK 这层拿。"""
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if not clip.wait_is_image_available():
            return None
        pb = clip.wait_for_image()
        if not pb:
            return None
        ok, buf = pb.save_to_bufferv("png", [], [])
        return base64.b64encode(buf).decode() if ok else None

    def paste_image(self):
        b64 = self._clip_image_b64()
        if not b64:
            return False
        self._js("window.__onPasteImage && window.__onPasteImage('data:image/png;base64,%s')" % b64)
        return True

    def on_context_menu(self, web, menu, event, hit):
        """剪贴板里有图时，右键菜单加一项「粘贴图片」——WebKit 自带的「粘贴」只粘文字。"""
        if not self._clip_image_b64():
            return False
        act = Gio.SimpleAction.new("gk-paste-image", None)
        act.connect("activate", lambda *a: self.paste_image())
        item = WebKit2.ContextMenuItem.new_from_gaction(act, "粘贴图片", None)
        menu.append(item)
        return False

    def _js(self, code):
        try:
            self.web.run_javascript(code, None, None, None)
        except Exception:
            pass

    def on_msg(self, ucm, result):
        """网页调 window.webkit.messageHandlers.gk.postMessage(JSON) → 这里执行。
           目前用于朗读：WebKit 里没有 speechSynthesis，借系统的 speech-dispatcher 发声。"""
        try:
            d = json.loads(result.get_js_value().to_string())
        except Exception:
            return
        act = d.get("a")
        if act == "tts":
            self.say(d.get("text") or "", float(d.get("rate") or 1.0),
                     d.get("engine") or "", d.get("voice") or "", str(d.get("id") or ""))
        elif act == "tts_stop":
            self._tts_stop()
        elif act == "shot":
            self.take_shot()

    def take_shot(self):
        """截图：走 xdg-desktop-portal（GNOME 直接的 Screenshot D-Bus 接口是禁掉的）。
           interactive=True → 弹 GNOME 自带的区域选择，鼠标拖、手写笔拖都行。
           抓完把图变成 data URL 交回网页，网页那边可以再用笔自由圈一次。"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return
        token = "gk%s" % secrets.token_hex(4)
        sender = bus.get_unique_name()[1:].replace(".", "_")
        req_path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)

        def on_response(conn, sender_, path, iface, signal, params):
            try:
                code, results = params.unpack()
                bus.signal_unsubscribe(sub)
                if code != 0:                       # 用户取消了
                    return
                uri = results.get("uri") or ""
                p = GLib.filename_from_uri(uri)[0] if uri else ""
                if not p or not os.path.exists(p):
                    self._toast("截图没拿到文件")
                    return
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                try:
                    os.remove(p)                    # portal 存的是临时文件，用完删掉
                except Exception:
                    pass
                self.web.run_javascript(
                    "window.__onShot && window.__onShot('data:image/png;base64,%s')" % b64,
                    None, None, None)
            except Exception:
                pass

        sub = bus.signal_subscribe("org.freedesktop.portal.Desktop",
                                   "org.freedesktop.portal.Request", "Response",
                                   req_path, None, Gio.DBusSignalFlags.NONE, on_response)
        # 注意：a{sv} 这里要传**普通 dict**（值才是 Variant）。
        # 之前先把它包成 GLib.Variant("a{sv}", …) 再塞进 (sa{sv})，PyGObject 会把这个 Variant
        # 当 dict 去迭代 → KeyError(0)，调用根本没发出去 —— 表现就是「点了截图没反应」。
        opts = {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", True),     # 让 GNOME 自己弹区域选择（鼠标/笔都能拖）
        }
        try:
            bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                          "org.freedesktop.portal.Screenshot", "Screenshot",
                          GLib.Variant("(sa{sv})", ("", opts)), None,
                          Gio.DBusCallFlags.NONE, 8000, None)
        except Exception as e:
            bus.signal_unsubscribe(sub)
            self._toast("截图失败：%s" % str(e)[:80])   # 别再静默失败了，出错要说话

    def _toast(self, msg):
        """把错误告诉网页（网页有 toast），不然壳里出问题用户只会看到「点了没反应」。"""
        try:
            self.web.run_javascript(
                "window.toast && window.toast(%s, true)" % json.dumps(msg, ensure_ascii=False),
                None, None, None)
        except Exception:
            pass

    # ---------------- 朗读：三档引擎 ----------------
    # WebKit 里没有 speechSynthesis，只能借系统。espeak 是机械音（难听），所以另装了两个神经语音：
    #   piper —— 离线、快（实测比实时快 10 倍）、无网络依赖，默认用它
    #   edge  —— 微软在线语音，最自然，但每句要联网合成
    def _tts_engines(self):
        e = {}
        p = os.path.expanduser("~/.local/piper/piper/piper")
        m = os.path.expanduser("~/.local/piper/models/zh_CN-huayan-medium.onnx")
        if os.path.isfile(p) and os.path.isfile(m):
            e["piper"] = (p, m)
        ed = os.path.expanduser("~/.local/tts-venv/bin/edge-tts")
        if os.path.isfile(ed):
            e["edge"] = ed
        if shutil.which("spd-say"):
            e["espeak"] = "spd-say"
        return e

    def say(self, text, rate=1.0, engine="", voice="", sid=""):
        self._tts_stop()
        text = (text or "").strip()[:2000]
        if not text:
            self._tts_done(sid)
            return
        # 只放行白名单里的音色，免得把网页传来的字符串直接拼进 shell
        self.tts_voice = voice if voice in EDGE_VOICES else EDGE_VOICES[0]
        eng = self._tts_engines()
        pick = engine if engine in eng else ("piper" if "piper" in eng else
                                             ("edge" if "edge" in eng else "espeak"))
        try:
            if pick == "piper":
                p, m = eng["piper"]
                # piper 出 raw PCM（22050Hz 单声道 16bit）→ 直接喂 aplay，边合成边播，不用等整段
                self._tts = subprocess.Popen(
                    "%s --model %s --output_raw --length_scale %.2f 2>/dev/null | "
                    "aplay -q -r 22050 -f S16_LE -t raw -" % (shlex_quote(p), shlex_quote(m), 1.0 / max(.5, rate)),
                    shell=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
                self._tts.stdin.write((text + "\n").encode("utf-8"))
                self._tts.stdin.close()
            elif pick == "edge":
                # edge-tts 只吐 mp3，系统里没有 mpg123/mpv/ffplay，用 GStreamer 放（gst-launch 是 GTK 自带的）
                pct = int((rate - 1.0) * 100)
                mp3 = os.path.join(GLib.get_user_cache_dir(), "gongkao-assistant",
                                   "tts-%s.mp3" % secrets.token_hex(4))
                self._tts_tmp = mp3
                self._tts = subprocess.Popen(
                    "%s --voice %s --rate=%+d%% --text %s --write-media %s >/dev/null 2>&1 && "
                    "gst-launch-1.0 -q playbin uri=file://%s >/dev/null 2>&1; rm -f %s"
                    % (shlex_quote(eng["edge"]), self.tts_voice, pct, shlex_quote(text),
                       shlex_quote(mp3), shlex_quote(mp3), shlex_quote(mp3)),
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
            else:
                r = int(max(-80, min(80, (rate - 1.0) * 60)))
                self._tts = subprocess.Popen(["spd-say", "-l", "zh", "-r", str(r), "-w", "--", text],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._toast("朗读失败：%s" % str(e)[:60])
            self._tts_done(sid)
            return
        # 网页不知道系统读完没有（原来靠按字数估时长，估短了打断、估长了卡壳）。
        # 这里盯着进程，一退出就回调网页接着读下一句 —— 段间衔接才跟得上。
        self._tts_sid = sid
        proc = self._tts
        GLib.timeout_add(200, lambda: self._tts_poll(proc, sid))

    def _tts_poll(self, proc, sid):
        if proc.poll() is None:
            return True                      # 还在读，继续盯
        if getattr(self, "_tts", None) is proc:
            self._tts_done(sid)              # 只有没被新的一段顶掉时才算「自然读完」
        return False

    def _tts_done(self, sid):
        if not sid:
            return
        self.web.run_javascript(
            "window.__ttsEnd&&window.__ttsEnd(%s)" % json.dumps(sid), None, None, None)

    def _tts_stop(self):
        try:
            subprocess.run(["spd-say", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass
        p = getattr(self, "_tts", None)
        if p and p.poll() is None:
            try:
                # piper/edge 走的是 shell 管道，要连整个进程组一起杀，否则 aplay 还在响
                os.killpg(os.getpgid(p.pid), 15)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass
        t = getattr(self, "_tts_tmp", "")
        if t:                     # 进程被杀，shell 里那句 rm 就跑不到了，这里补一刀
            try:
                os.remove(t)
            except Exception:
                pass
            self._tts_tmp = ""

    def on_download(self, ctx, download):
        download.connect("decide-destination", self._dl_dest)
        download.connect("finished", self._dl_done)

    def _dl_dest(self, download, suggested):
        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or GLib.get_home_dir()
        dest = os.path.join(d, suggested or "download")
        base, ext = os.path.splitext(dest); i = 1
        while os.path.exists(dest):                     # 不覆盖已存在的文件
            dest = "%s(%d)%s" % (base, i, ext); i += 1
        self._last_dl = dest
        download.set_destination(GLib.filename_to_uri(dest, None))
        return True

    def _dl_done(self, download):
        path = getattr(self, "_last_dl", "")
        if not path or not os.path.exists(path):
            return
        js = ("window.__onDownloaded && window.__onDownloaded(%s)"
              % ("'" + path.replace("\\", "\\\\").replace("'", "\\'") + "'"))
        try:
            self.web.run_javascript(js, None, None, None)
        except Exception:
            pass

    def on_decide(self, web, decision, dtype):
        # 跳到「别的网站」的链接 → 交系统浏览器；App 只停在自己的站
        if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            try:
                uri = decision.get_navigation_action().get_request().get_uri()
                host = (urlparse(uri).hostname or "").lower()
                if uri.startswith(("http://", "https://")) and host and host not in APP_HOSTS:
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                    decision.ignore()
                    return True
            except Exception:
                pass
        return False


if __name__ == "__main__":
    Gongkao().run(None)
