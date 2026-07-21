#!/usr/bin/python3
# 公考助手 桌面版（原生 GTK + 系统 WebKit2GTK，不依赖 Chrome）。
# 用系统 python3（自带 gi）运行；一个真·原生窗口加载网页版。
import base64
import json
import os
import secrets
import subprocess
import threading
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
from gi.repository import Gtk, WebKit2, GLib, Gio, Gdk, GdkPixbuf  # noqa: E402

# 系统通知走 libnotify（比 Gio.send_notification 靠谱：不要求 .desktop 文件名和 application_id 对上）
try:
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify  # noqa: E402
    Notify.init("公考助手")
    HAVE_NOTIFY = True
except Exception:
    HAVE_NOTIFY = False
# 托盘小图标（像 QQ/微信最小化后那个）
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
    HAVE_TRAY = True
except Exception:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator  # noqa: E402
        HAVE_TRAY = True
    except Exception:
        HAVE_TRAY = False

APP_ID = "com.gongkao.app"
DESKTOP_VER = "4.9"          # 桌面壳版本；改动壳本身时+1，网页据此判断「需重新下载」
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
        # 点系统通知 → 把窗口调到前台
        try:
            act = Gio.SimpleAction.new("present", None)
            act.connect("activate", lambda *a: self.win and self.win.present())
            self.add_action(act)
        except Exception:
            pass
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
            st = self.web.get_settings()
            st.set_property("enable-developer-extras", False)
            # 视频在 APP 内播放：我们的播放器是「点封面 → 取播放地址 → 再 play()」，
            # 中间隔了一次网络请求，用户手势早过期了 —— 不放开这条就会被当成自动播放拦下。
            # （MSE 默认是开的，hls.js 靠它；这里不用动。）
            st.set_property("media-playback-requires-user-gesture", False)
        except Exception:
            pass
        self.web.connect("decide-policy", self.on_decide)
        self.web.connect("run-file-chooser", self.on_file_chooser)   # 自己弹文件框，见下
        self.web.connect("context-menu", self.on_context_menu)       # 右键菜单加「粘贴图片」
        self.web.connect("script-dialog", self.on_script_dialog)     # 吞掉 pdf.js 的「确定离开？」
        # 桌面消息通知：WebKitGTK 默认不弹网页通知。这里放行通知权限、并把网页的
        # new Notification(...) 接到系统通知栏（Gio.Notification）。网页端 notifyChat 用的就是 Web Notification。
        # （信号名在个别 WebKit 版本可能没有，包 try 防止整壳起不来。）
        try:
            self.web.connect("permission-request", self.on_permission)
            self.web.connect("show-notification", self.on_web_notification)
        except Exception:
            pass

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
        self.win.connect("delete-event", self.on_close)    # 点 ✕ 收进托盘，不退出（后台还收消息）
        self.win.show_all()
        self.setup_tray()

    def setup_tray(self):
        """系统托盘小图标（像 QQ/微信），最小化/关闭后还能看到、点开、退出。"""
        if not HAVE_TRAY:
            return
        try:
            icon = next((p for p in ICONS if os.path.exists(p)), "")
            self.tray = AppIndicator.Indicator.new(
                "com.gongkao.app", "gongkao-assistant",
                AppIndicator.IndicatorCategory.APPLICATION_STATUS)
            self.tray.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self.tray.set_title("公考助手")
            if icon:
                try:
                    self.tray.set_icon_full(icon, "公考助手")
                except Exception:
                    pass
            menu = Gtk.Menu()
            mi = Gtk.MenuItem(label="显示公考助手")
            mi.connect("activate", lambda *a: self.win and self.win.present())
            menu.append(mi)
            mq = Gtk.MenuItem(label="退出")
            mq.connect("activate", lambda *a: self.quit())
            menu.append(mq)
            menu.show_all()
            self.tray.set_menu(menu)
            try:
                self.tray.set_secondary_activate_target(mi)  # 左/中键点图标唤起窗口
            except Exception:
                pass
        except Exception:
            pass

    def on_close(self, *a):
        """✕ 不真退出：藏起窗口留在托盘，SSE 还连着、能收消息弹通知。真退出走托盘菜单「退出」。"""
        if HAVE_TRAY and getattr(self, "tray", None):
            self.win.hide()
            return True     # 拦下默认的销毁
        return False        # 没托盘就照常退出，别把用户困住

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

    # ---------------- 送文件进网页：拖放 / 选文件夹 / 粘贴 共用 ----------------
    # 走 base64 桥的单文件上限。**不是**云盘的 200MB —— 200MB 文件 base64 后是 267MB 的
    # JS 源码，run_javascript 扛不住。更大的文件走网页那个「⬆ 上传」按钮（分片传，不经这座桥）。
    DESK_MAX_FILE = 64 * 1024 * 1024
    DESK_BATCH = 6 * 1024 * 1024             # 一批最多这么多原始字节（base64 还会再涨 1/3）

    def _walk(self, path, out, base=None):
        """把一个路径摊成 [(绝对路径, 相对目录)]。目录就整棵走下去。

        相对目录是给云盘建子目录用的：拖进来 /home/me/文档/公考，就该在云盘里建出
        「公考/…」这棵树，而不是把里面的文件全倒在当前目录。
        """
        if base is None:
            base = os.path.dirname(path.rstrip(os.sep))
        if os.path.isfile(path):
            out.append((path, os.path.relpath(os.path.dirname(path), base).replace(os.sep, "/")))
            return
        if not os.path.isdir(path):
            return
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = os.path.relpath(dirpath, base).replace(os.sep, "/")
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                out.append((os.path.join(dirpath, fn), rel))

    def _send_paths(self, paths, label="", intent=""):
        """收下一串路径 → 后台线程里遍历 + 读盘 + 分批送进网页。

        os.walk 也放进线程里：目录树深/在网络盘上时，遍历本身就是长阻塞，留在主线程
        照样冻界面（README 第 3 条）。主线程这边只负责立刻给个「正在读取」的提示。
        """
        if getattr(self, "_pumping", False):
            self._toast("上一批还在传，等它传完再来")   # 两个 pump 会互相抢 _ack
            return
        self._pumping = True
        self._ack = threading.Event()
        if label:
            self._toast(label)

        def work():
            try:
                out = []
                for p in paths:
                    self._walk(p, out)
                if not out:
                    GLib.idle_add(self._toast, "这里面没有可上传的文件")
                    return
                self._pump(out, intent)
            finally:
                self._pumping = False
        threading.Thread(target=work, daemon=True).start()

    def _pump(self, pairs, intent=""):
        """把 [(路径, 相对目录)] 分批 base64 送进网页。**在后台线程里跑**。

        两件事必须做对，否则真实目录（实测「公考」= 497 个文件 / 816MB）会把壳搞死：

        ① **不能在主线程上读**。读几百 MB + base64 是长阻塞，GTK 主线程一堵界面就冻住
           （README 第 3 条：主线程上一个阻塞调用都不能有）。所以读盘（连同 os.walk）
           都在后台线程，只把 run_javascript 用 idle_add 丢回主线程。
        ② **要有背压**。一口气把 136 批塞进网页，浏览器那边同时开一百多个上传、
           base64 字符串全堆在内存里。所以每批送完等网页回一句 batchdone 再送下一批。
        """
        batch, size, sent, skipped = [], 0, 0, []
        for p, rel in pairs:
            try:
                n = os.path.getsize(p)
                if n > self.DESK_MAX_FILE:
                    skipped.append(os.path.basename(p))
                    continue
                with open(p, "rb") as f:
                    raw = f.read()
            except Exception:
                skipped.append(os.path.basename(p))
                continue
            batch.append({"name": os.path.basename(p), "rel": "" if rel == "." else rel,
                          "data": base64.b64encode(raw).decode()})
            size += n
            sent += 1
            if size >= self.DESK_BATCH:
                self._push(batch, intent)
                batch, size = [], 0
        if batch:
            self._push(batch, intent)
        if skipped:
            # 单个太大的走网页那个「⬆ 上传」按钮更靠谱：那条是分片传的，不经这座 base64 的桥
            GLib.idle_add(self._toast, "%d 个文件太大没传（%s…），用「⬆ 上传」单独传"
                          % (len(skipped), skipped[0][:20]))

    def _push(self, batch, intent=""):
        """送一批，然后等网页说「这批传完了」再回来送下一批。"""
        self._ack.clear()
        GLib.idle_add(self._flush, batch, intent)
        if not self._ack.wait(300):          # 超时就往下走，别把整个上传永远卡住
            GLib.idle_add(self._toast, "有一批等太久，继续传后面的")

    def _flush(self, batch, intent=""):
        # intent 告诉网页这批的来路：'drive' 是点了「传文件夹」（明确要进云盘），
        # 空字符串是拖放/粘贴（按用户当前在哪一页分发 —— 拖进小记就该进小记）
        self._js("window.__onPickedFiles && window.__onPickedFiles(%s, %s)"
                 % (json.dumps(batch, ensure_ascii=False), json.dumps(intent)))
        return False                          # idle_add 只跑一次

    def pick_dir(self):
        """选一个文件夹整个传上去。

        网页那套 <input webkitdirectory> 是 Chromium 的能力，WebKitGTK 不认 —— 在壳里
        点「传文件夹」只会弹出选**文件**的框（这正是用户反馈的现象）。所以桌面版改走
        这条原生路：GTK 开 SELECT_FOLDER，选完在 Python 这边把整棵树摊平送进网页。
        """
        dlg = Gtk.FileChooserDialog(title="选择要上传的文件夹", transient_for=self.win,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("取消", Gtk.ResponseType.CANCEL, "上传这个文件夹", Gtk.ResponseType.ACCEPT)
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.ACCEPT else None
        dlg.destroy()
        if not path:
            return
        self._send_paths([path], "正在读取「%s」…" % os.path.basename(path), intent="drive")

    def paste_files(self):
        """系统剪贴板里复制的**文件**（在文件管理器里 Ctrl+C 的那种）粘贴进来。

        WebKitGTK 的 paste 事件拿不到文件，只能从 GTK 这层读 text/uri-list。
        剪贴板里是图片时走原来的 paste_image。
        """
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        uris = clip.wait_for_uris() or []
        paths = []
        for u in uris:
            try:
                p = GLib.filename_from_uri(u)[0]
            except Exception:
                continue
            if p and os.path.exists(p):
                paths.append(p)
        if not paths:
            return False
        self._send_paths(paths, "正在粘贴…")
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
        """拖进来的既可能是文件、也可能是**整个文件夹** —— 后者要整棵走下去。

        原来这里 `os.path.isfile` 一判，目录直接被跳过，拖文件夹进来什么也不会发生。
        """
        paths = []
        for uri in (data.get_uris() or [])[:50]:
            try:
                p = GLib.filename_from_uri(uri)[0]
            except Exception:
                continue
            if p and os.path.exists(p):
                paths.append(p)
        Gtk.drag_finish(ctx, bool(paths), False, time)
        self._js("window.__onDragLeave && window.__onDragLeave()")
        if not paths:
            self._toast("这些东西读不出文件（只支持本地文件）")
            return
        self._send_paths(paths)

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

    def on_script_dialog(self, web, dialog):
        """吞掉「您确定要离开此页面吗？」。
           那个框是 pdf.js 有笔迹改动时挂的 beforeunload —— 但我们是单页应用，「返回」只是切视图、
           并没有真的卸载页面，pdf.js 的 iframe 被收起时误触发，弹出来纯属打扰（而且笔迹我们自己存）。
           这里对 BEFORE_UNLOAD_CONFIRM 一律「确认离开」且不显示对话框。其它 alert/confirm 照常。"""
        try:
            if dialog.get_dialog_type() == WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM:
                dialog.confirm_set_confirmed(True)
                return True          # 已处理，别再弹默认框
        except Exception:
            pass
        return False

    def on_permission(self, web, request):
        """放行网页的通知权限请求（这样 Notification.requestPermission() 会成功）。"""
        try:
            if isinstance(request, WebKit2.NotificationPermissionRequest):
                request.allow()
                return True
        except Exception:
            pass
        return False           # 其它权限（定位/摄像头等）保持默认

    def on_web_notification(self, web, notification):
        """网页 new Notification(title,{body}) → 系统通知（收到聊天消息就靠它）。用 libnotify。"""
        try:
            title = notification.get_title() or "公考助手"
            body = notification.get_body() or ""
            if HAVE_NOTIFY:
                ic = next((p for p in ICONS if os.path.exists(p)), "")
                n = Notify.Notification.new(title, body, ic or None)
                try:
                    n.add_action("present", "打开", lambda *a: self.win and self.win.present())
                except Exception:
                    pass
                n.show()
            else:                # 兜底：Gio（要求 .desktop 名与 app-id 一致，未必弹）
                gn = Gio.Notification.new(title)
                if body:
                    gn.set_body(body)
                self.send_notification("gk-msg", gn)
            return True          # 已自行处理，WebKit 不用再管
        except Exception:
            return False

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
        elif act == "open":
            self.open_external(d.get("url") or "")
        elif act == "copyimg":
            self.copy_image(d.get("data") or "")
        elif act == "pickdir":
            self.pick_dir()
        elif act == "batchdone":
            # 网页把这一批传完了 → 放行下一批（背压，见 _push）
            ev = getattr(self, "_ack", None)
            if ev:
                ev.set()
        elif act == "pastefiles":
            # 剪贴板里先看有没有文件，没有再当图片粘
            if not self.paste_files() and not self.paste_image():
                self._toast("剪贴板里没有文件或图片")

    def copy_image(self, b64):
        """把网页传来的 PNG（base64）**真的写进系统剪贴板**。
           网页端 navigator.clipboard.write 在 WebKitGTK 里被拒（报 user denied，其实是不支持），
           所以桌面版的「复制图片」改走这条：GTK 这层直接 set_image，粘到微信/文档都行。"""
        try:
            raw = base64.b64decode(b64.split(",")[-1])
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(raw)
            loader.close()
            pb = loader.get_pixbuf()
            clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clip.set_image(pb)
            clip.store()
            self._toast("图片已复制，可以粘贴了")
        except Exception as e:
            self._toast("复制图片失败：" + str(e)[:50])

    def open_external(self, uri):
        """网页请求「用系统浏览器打开这个链接」。

        为什么要有这条路：`target="_blank"` 在 WebKit 里走 NEW_WINDOW_ACTION，
        **实测在真实的壳里根本走不通**（decide-policy 里加了处理也没用，新窗口请求就是被吞掉），
        表现是点了完全没反应。所以不再指望 WebKit 的行为，改由网页**明确**告诉壳要打开什么。"""
        if not uri.startswith(("http://", "https://")):
            self._toast("这个链接打不开：" + uri[:50])
            return
        try:
            ok = Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as e:
            ok = False
            self._toast("打开浏览器失败：" + str(e)[:50])
        if not ok:
            self._toast("没能调起系统浏览器")

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

    # ---------------- 朗读：两档引擎 ----------------
    # WebKit 里没有 speechSynthesis，只能借系统。
    #   piper —— 离线、快（实测比实时快 10 倍）、无网络依赖，默认用它
    #   edge  —— 微软在线语音，最自然，但每句要联网合成
    #
    # ⚠️ 曾经还有第三档「系统默认」= speech-dispatcher（spd-say），已彻底移除：
    #    它的 PulseAudio 输出模块会**段错误**（内核日志实锤：
    #    `speech-dispatch[8338]: segfault at 0 ... in spd_pulse.so`，
    #    蓝牙音频设备连接、默认音频设备切换时踩空指针），是 Ubuntu 自带组件的 bug。
    #    崩了以后它的 socket 还在，spd-say 会一直挂着 —— 谁调谁遭殃。不碰它。
    def _tts_engines(self):
        e = {}
        p = os.path.expanduser("~/.local/piper/piper/piper")
        m = os.path.expanduser("~/.local/piper/models/zh_CN-huayan-medium.onnx")
        if os.path.isfile(p) and os.path.isfile(m):
            e["piper"] = (p, m)
        ed = os.path.expanduser("~/.local/tts-venv/bin/edge-tts")
        if os.path.isfile(ed):
            e["edge"] = ed
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
        if not eng:
            self._toast("没装朗读引擎，跑一下 desktop/install-tts.sh")
            self._tts_done(sid)
            return
        pick = engine if engine in eng else ("piper" if "piper" in eng else "edge")
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
        # ⚠️ 这里绝不能有任何阻塞调用：它跑在 GTK 主线程上，卡一下界面就冻一下。
        # 老代码在这里 subprocess.run(["spd-say","-C"], timeout=2) —— speech-dispatcher 一崩，
        # 每点一次朗读界面就冻 2 秒，看着就像「桌面卡死了」。杀自己的进程组就够了。
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
        # 跳到「别的网站」的链接 → 交系统浏览器；App 只停在自己的站。
        # ⚠️ 必须同时处理 NEW_WINDOW_ACTION：`target="_blank"` 的链接走的是**这一路**，
        #    原来只管 NAVIGATION_ACTION，所以桌面版里所有 _blank 外链（新闻视频、原文来源…）
        #    点了**完全没反应**，连个提示都没有 —— WebKit 默认就把新窗口请求丢掉了。
        if dtype in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                     WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            try:
                uri = decision.get_navigation_action().get_request().get_uri()
                host = (urlparse(uri).hostname or "").lower()
                if uri.startswith(("http://", "https://")) and host and host not in APP_HOSTS:
                    ok = Gio.AppInfo.launch_default_for_uri(uri, None)
                    decision.ignore()
                    if not ok:
                        self._toast("打不开系统浏览器，链接已复制：" + uri[:60])
                    return True
                if dtype == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    # 自己站内的 _blank（比如导出的 PDF 预览）：就在当前窗口打开，别丢掉
                    decision.ignore()
                    self.web.load_uri(uri)
                    return True
            except Exception:
                pass
        return False


if __name__ == "__main__":
    Gongkao().run(None)
