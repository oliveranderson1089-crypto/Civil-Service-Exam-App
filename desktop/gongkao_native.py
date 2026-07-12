#!/usr/bin/python3
# 公考助手 桌面版（原生 GTK + 系统 WebKit2GTK，不依赖 Chrome）。
# 用系统 python3（自带 gi）运行；一个真·原生窗口加载网页版。
import os
from urllib.parse import urlparse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, GLib, Gio, Gdk  # noqa: E402

APP_ID = "com.gongkao.app"
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

        self.web = WebKit2.WebView.new_with_context(ctx)
        try:
            self.web.get_settings().set_property("enable-developer-extras", False)
        except Exception:
            pass
        self.web.connect("decide-policy", self.on_decide)
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
