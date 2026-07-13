#!/usr/bin/python3
# 公考助手 桌面版（原生 GTK + 系统 WebKit2GTK，不依赖 Chrome）。
# 用系统 python3（自带 gi）运行；一个真·原生窗口加载网页版。
import os
import shutil
import subprocess
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
DESKTOP_VER = "3.4"          # 桌面壳版本；改动壳本身时+1，网页据此判断「需重新下载」
TUNNEL = "https://gk.gongkaopei2026.click"
APP_HOSTS = {"gk.gongkaopei2026.click", "127.0.0.1", "localhost"}
ICONS = ["/usr/share/icons/hicolor/512x512/apps/gongkao-assistant.png",
         "/usr/share/icons/hicolor/256x256/apps/gongkao-assistant.png"]


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
        self.tts_ok = bool(shutil.which("spd-say"))     # WebKit 没有 speechSynthesis，只能借系统 TTS
        try:
            ucm.add_script(WebKit2.UserScript.new(
                "window.__desktop=true;window.__desktopVer='%s';window.__desktopTTS=%s;"
                % (DESKTOP_VER, "true" if self.tts_ok else "false"),
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

    def on_msg(self, ucm, result):
        """网页调 window.webkit.messageHandlers.gk.postMessage(JSON) → 这里执行。
           目前用于朗读：WebKit 里没有 speechSynthesis，借系统的 speech-dispatcher 发声。"""
        try:
            import json
            d = json.loads(result.get_js_value().to_string())
        except Exception:
            return
        act = d.get("a")
        if act == "tts":
            self._tts_stop()
            text = (d.get("text") or "")[:4000]
            if not text:
                return
            rate = int(max(-80, min(80, (float(d.get("rate") or 1.0) - 1.0) * 60)))   # 1.0 → 0
            try:
                self._tts = subprocess.Popen(["spd-say", "-l", "zh", "-r", str(rate), "-w", "--", text],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        elif act == "tts_stop":
            self._tts_stop()

    def _tts_stop(self):
        try:
            subprocess.run(["spd-say", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass
        p = getattr(self, "_tts", None)
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

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
