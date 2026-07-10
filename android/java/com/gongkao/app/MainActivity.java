package com.gongkao.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.Toast;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.HashMap;
import android.database.Cursor;
import android.provider.OpenableColumns;
import java.util.Locale;

/**
 * 公考积累 安卓壳：一个全屏 WebView，加载电脑上运行的服务地址。
 * - 首次启动 / 连接失败时弹窗让用户填服务器地址（默认局域网 IP）。
 * - 顶部菜单可“刷新”“设置服务器地址”。
 * - 导出 PDF 时交给系统下载器（带上登录 Cookie），存到“下载”目录。
 */
public class MainActivity extends Activity {

    private WebView web;
    private SharedPreferences prefs;
    private TextToSpeech tts;                 // 朗读引擎（供网页 speechSynthesis 桥接）
    private volatile boolean ttsReady = false;
    private ValueCallback<Uri[]> filePathCallback;   // 网页文件选择回调
    private Uri cameraUri;                            // 拍照输出 URI
    private static final int FILE_REQ = 1001;
    private static final int CAMERA_REQ = 1002;
    private static final String KEY = "server_url";
    private static final int NOTIFY_PERM_REQ = 1003;
    private volatile boolean pageReady = false;      // 网页加载完才能执行 ntfGo()
    private String pendingNotifyLink = null;         // 通知点进来时要跳转的位置
    // 默认地址：固定公网网址（命名隧道，重启不变）；在家也可在 APP 内改成局域网 IP 提速
    static final String DEF = "https://gk.gongkaopei2026.click";

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("cfg", MODE_PRIVATE);

        web = new WebView(this);
        setContentView(web);

        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        // 禁止双指/双击缩放：让网页像原生 App，不会缩放错位
        ws.setSupportZoom(false);
        ws.setBuiltInZoomControls(false);
        ws.setDisplayZoomControls(false);
        // 关键：标记“APP 内”，前端据此用 GET 链接触发系统下载
        ws.setUserAgentString(ws.getUserAgentString() + " GongkaoApp");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);

        // 原生桥接：网页「设置」里可调用，改服务器地址 / 刷新 / 朗读(TTS)
        web.addJavascriptInterface(new Bridge(), "GongkaoNative");

        // 朗读引擎：让网页里的 window.speechSynthesis（后端注入的 polyfill）真正发声
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                try { tts.setLanguage(Locale.CHINESE); } catch (Exception ignore) {}
                ttsReady = true;
            }
        });
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) {}
            @Override public void onDone(String id) { fireTtsEnd(id); }
            @Override public void onError(String id) { fireTtsEnd(id); }
        });

        web.setWebChromeClient(new WebChromeClient() {
            // 关键：让网页里的「选择文件」能唤起系统文件选择器
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = cb;
                // 网页 input 带 capture 且接受图片 → 直接唤起相机
                boolean wantCam = false;
                try { wantCam = params.isCaptureEnabled(); } catch (Exception ignore) {}
                if (wantCam && acceptsImage(params.getAcceptTypes()) && launchCamera()) {
                    return true;
                }
                // 手动构造意图：尊重 accept 类型 + 支持多选
                String[] types = params.getAcceptTypes();
                String primary = "*/*";
                if (types != null && types.length > 0 && types[0] != null && !types[0].isEmpty()) {
                    primary = types[0];
                }
                boolean imageOnly = primary.startsWith("image");
                boolean multiple = false;
                try { multiple = params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE; } catch (Exception ignore) {}
                // 图片走相册(ACTION_GET_CONTENT)；其它文件走系统文档界面(ACTION_OPEN_DOCUMENT)——能可靠多选
                Intent intent = new Intent(imageOnly ? Intent.ACTION_GET_CONTENT : Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType(primary);
                if (types != null && types.length > 1) {
                    java.util.ArrayList<String> mt = new java.util.ArrayList<>();
                    for (String t : types) if (t != null && !t.isEmpty()) mt.add(t);
                    if (!mt.isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, mt.toArray(new String[0]));
                }
                if (multiple) intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                try {
                    // ACTION_OPEN_DOCUMENT 是系统活动，不用 createChooser；GET_CONTENT 用 chooser 方便选相册
                    startActivityForResult(imageOnly ? Intent.createChooser(intent, "选择图片") : intent, FILE_REQ);
                } catch (ActivityNotFoundException e) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, "没有可用的文件选择器", Toast.LENGTH_LONG).show();
                    return false;
                }
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, int code, String desc, String url) {
                if (url != null && url.equals(web.getUrl())) {
                    promptUrl(true);  // 主页面加载失败才提示改地址
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                // 外站链接（原文来源等）交给系统浏览器打开，APP 停在原页可正常返回
                try {
                    Uri target = Uri.parse(url);
                    String scheme = target.getScheme() == null ? "" : target.getScheme();
                    if (!scheme.equals("http") && !scheme.equals("https")) return false;
                    String cur = v.getUrl();
                    String curHost = cur == null ? null : Uri.parse(cur).getHost();
                    if (curHost != null && !curHost.equals(target.getHost())) {
                        startActivity(new Intent(Intent.ACTION_VIEW, target));
                        return true;
                    }
                } catch (Exception ignored) { }
                return false;
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                pushSysTheme();   // WebView 的 prefers-color-scheme 不跟随系统，由原生告知网页
                pageReady = true;
                consumeNotifyLink();
            }
        });

        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String ua, String cd, String mime, long len) {
                try {
                    DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) req.addRequestHeader("Cookie", cookie);
                    String name = URLUtil.guessFileName(url, cd, mime);
                    req.setMimeType(mime);
                    req.allowScanningByMediaScanner();
                    req.setNotificationVisibility(
                            DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                    DownloadManager dm =
                            (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                    dm.enqueue(req);
                    Toast.makeText(MainActivity.this, "正在下载：" + name, Toast.LENGTH_SHORT).show();
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "下载失败：" + e.getMessage(),
                            Toast.LENGTH_LONG).show();
                }
            }
        });

        handleShareIntent(getIntent());  // 冷启动即处理「分享到公考助手」

        Notifier.ensureChannel(this);
        askNotifyPermission();
        NotifyReceiver.schedule(this);           // 定时把服务器的新消息弹到通知栏
        Notifier.fetchAndNotify(this, false);    // 打开时也顺便查一次
        takeNotifyLink(getIntent());

        String url = prefs.getString(KEY, "");
        if (url.isEmpty()) {
            promptUrl(false);
        } else {
            web.loadUrl(url);
        }
    }

    private void promptUrl(boolean isError) {
        String cur = prefs.getString(KEY, "");
        final EditText in = new EditText(this);
        in.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        in.setText(cur.isEmpty() ? DEF : cur);

        new AlertDialog.Builder(this)
                .setTitle(isError ? "无法连接，请检查服务器地址" : "设置服务器地址")
                .setMessage("填写电脑上运行的服务地址，例如：\n" + DEF)
                .setView(in)
                .setCancelable(false)
                .setPositiveButton("确定", (d, w) -> {
                    String u = in.getText().toString().trim();
                    if (!u.startsWith("http")) u = "http://" + u;
                    prefs.edit().putString(KEY, u).apply();
                    web.loadUrl(u);
                })
                .setNegativeButton("退出", (d, w) -> finish())
                .show();
    }

    /** 暴露给网页的原生方法（网页「设置」里调用）。 */
    /** TTS 播完/出错时回调网页顶层的 __ttsEvent（资料页在 iframe，回调走 window.top 中转）。 */
    private void fireTtsEnd(String id) {
        if (id == null) return;
        runOnUiThread(() -> {
            if (web != null) web.evaluateJavascript(
                "window.__ttsEvent&&window.__ttsEvent('" + id + "','end')", null);
        });
    }

    /** Android 13+ 需要运行时申请通知权限，否则弹了也看不见。 */
    private void askNotifyPermission() {
        if (android.os.Build.VERSION.SDK_INT < 33) return;
        try {
            if (checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, NOTIFY_PERM_REQ);
            }
        } catch (Exception ignored) { }
    }

    /** 从通知的 Intent 里取出要跳转的位置，等网页就绪后再执行。 */
    private void takeNotifyLink(Intent intent) {
        if (intent == null) return;
        String link = intent.getStringExtra(Notifier.EXTRA_LINK);
        if (link == null || link.isEmpty()) return;
        pendingNotifyLink = link;
        consumeNotifyLink();
    }

    private void consumeNotifyLink() {
        if (!pageReady || pendingNotifyLink == null || web == null) return;
        final String link = pendingNotifyLink;
        pendingNotifyLink = null;
        runOnUiThread(() -> web.evaluateJavascript(
                "window.ntfGo && ntfGo('" + link.replace("'", "\\'") + "')", null));
    }

    /** 系统当前是否深色模式。 */
    private boolean sysDarkNow() {
        int mode = getResources().getConfiguration().uiMode
                & android.content.res.Configuration.UI_MODE_NIGHT_MASK;
        return mode == android.content.res.Configuration.UI_MODE_NIGHT_YES;
    }

    /** 把系统深色状态写进网页的 window.__sysDark，并触发主题重算。 */
    private void pushSysTheme() {
        final boolean dark = sysDarkNow();
        runOnUiThread(() -> {
            if (web == null) return;
            web.evaluateJavascript("window.__sysDark=" + dark
                    + ";window.__onSysTheme&&window.__onSysTheme(" + dark + ")", null);
        });
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration cfg) {
        super.onConfigurationChanged(cfg);
        pushSysTheme();   // 系统在 19:00 切到夜间时，App 立刻跟着变
    }

    /** 沉浸式全屏：隐藏状态栏/导航栏（PDF 全屏阅读）。 */
    private void setFullscreenUi(boolean on) {
        android.view.View d = getWindow().getDecorView();
        if (on) {
            d.setSystemUiVisibility(
                    android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
                            | android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        } else {
            d.setSystemUiVisibility(android.view.View.SYSTEM_UI_FLAG_VISIBLE);
        }
    }

    public class Bridge {
        /** 手机通知栏推送：是否已开启。 */
        @android.webkit.JavascriptInterface
        public boolean notifyEnabled() { return Notifier.enabled(MainActivity.this); }

        /** 打开/关闭手机通知栏推送（同时启停定时拉取）。 */
        @android.webkit.JavascriptInterface
        public void setNotify(boolean on) {
            Notifier.prefs(MainActivity.this).edit().putBoolean(Notifier.KEY_ENABLED, on).apply();
            if (on) {
                runOnUiThread(MainActivity.this::askNotifyPermission);
                NotifyReceiver.schedule(MainActivity.this);
                Notifier.fetchAndNotify(MainActivity.this, false);
            } else {
                NotifyReceiver.cancel(MainActivity.this);
            }
        }

        /** 立刻去服务器拉一次新消息（网页里「立即检查」用）。 */
        @android.webkit.JavascriptInterface
        public void notifyCheck() { Notifier.fetchAndNotify(MainActivity.this, true); }

        /** 发一条测试通知，验证通知权限有没有被系统挡掉。 */
        @android.webkit.JavascriptInterface
        public void notifyTest() { Notifier.showTest(MainActivity.this); }

        @android.webkit.JavascriptInterface
        public boolean sysDark() { return sysDarkNow(); }

        @android.webkit.JavascriptInterface
        public void fullscreen(boolean on) { runOnUiThread(() -> setFullscreenUi(on)); }

        @android.webkit.JavascriptInterface
        public void changeServer() { runOnUiThread(() -> promptUrl(false)); }

        @android.webkit.JavascriptInterface
        public void reload() { runOnUiThread(() -> web.reload()); }

        @android.webkit.JavascriptInterface
        public void ttsSpeak(String id, String text, float rate) {
            runOnUiThread(() -> {
                if (!ttsReady || tts == null) { fireTtsEnd(id); return; }
                try {
                    tts.setSpeechRate(rate > 0 ? rate : 1f);
                    HashMap<String, String> p = new HashMap<>();
                    p.put(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, id);
                    tts.speak(text, TextToSpeech.QUEUE_FLUSH, p);
                } catch (Exception e) { fireTtsEnd(id); }
            });
        }

        @android.webkit.JavascriptInterface
        public void ttsCancel() { runOnUiThread(() -> { if (tts != null) tts.stop(); }); }

        @android.webkit.JavascriptInterface
        public void share(String text) {
            runOnUiThread(() -> {
                try {
                    Intent i = new Intent(Intent.ACTION_SEND);
                    i.setType("text/plain");
                    i.putExtra(Intent.EXTRA_TEXT, text);
                    startActivity(Intent.createChooser(i, "分享到"));
                } catch (Exception ignored) { }
            });
        }

        /** 当前安装包的 versionCode，网页据此判断有没有新版。 */
        @android.webkit.JavascriptInterface
        public int appVersion() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
            } catch (Exception e) {
                return 0;
            }
        }

        /** 下载新版 APK 并唤起系统安装界面（不用再去浏览器点链接）。 */
        @android.webkit.JavascriptInterface
        public void updateApp(String url) {
            new Thread(() -> {
                try {
                    runOnUiThread(() -> Toast.makeText(MainActivity.this,
                            "正在下载新版…", Toast.LENGTH_SHORT).show());
                    File dir = new File(getCacheDir(), "share");   // CamProvider 已开放这个目录
                    dir.mkdirs();
                    File out = new File(dir, "gongkao-update.apk");
                    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(300000);
                    InputStream in = conn.getInputStream();
                    java.io.FileOutputStream fo = new java.io.FileOutputStream(out);
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) > 0) fo.write(buf, 0, n);
                    fo.close(); in.close(); conn.disconnect();
                    if (out.length() < 10000) throw new Exception("下载不完整");
                    final Uri apk = Uri.parse("content://" + CamProvider.AUTH + "/share/gongkao-update.apk");
                    runOnUiThread(() -> {
                        Intent i = new Intent(Intent.ACTION_VIEW);
                        i.setDataAndType(apk, "application/vnd.android.package-archive");
                        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                        try {
                            startActivity(i);
                        } catch (Exception e) {
                            Toast.makeText(MainActivity.this,
                                    "请在系统设置里允许「公考助手」安装应用", Toast.LENGTH_LONG).show();
                        }
                    });
                } catch (Exception e) {
                    runOnUiThread(() -> Toast.makeText(MainActivity.this,
                            "更新失败：" + e.getMessage(), Toast.LENGTH_LONG).show());
                }
            }).start();
        }

        @android.webkit.JavascriptInterface
        public void shareFile(String url, String name) {
            new Thread(() -> {
                try {
                    File dir = new File(getCacheDir(), "share");
                    dir.mkdirs();
                    String safe = name == null || name.trim().isEmpty()
                            ? ("file_" + System.currentTimeMillis())
                            : name.replaceAll("[/\\\\:*?\"<>|]", "_");
                    File out = new File(dir, safe);
                    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(120000);
                    InputStream in = conn.getInputStream();
                    java.io.FileOutputStream fo = new java.io.FileOutputStream(out);
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) > 0) fo.write(buf, 0, n);
                    fo.close(); in.close(); conn.disconnect();
                    final Uri cu = Uri.parse("content://" + CamProvider.AUTH + "/share/" + Uri.encode(safe));
                    final String mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(
                            safe.contains(".") ? safe.substring(safe.lastIndexOf('.') + 1).toLowerCase() : "");
                    runOnUiThread(() -> {
                        Intent i = new Intent(Intent.ACTION_SEND);
                        i.setType(mime != null ? mime : "application/octet-stream");
                        i.putExtra(Intent.EXTRA_STREAM, cu);
                        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        startActivity(Intent.createChooser(i, "分享文件"));
                    });
                } catch (Exception e) {
                    runOnUiThread(() -> Toast.makeText(MainActivity.this,
                            "分享失败：" + e.getMessage(), Toast.LENGTH_LONG).show());
                }
            }).start();
        }

        @android.webkit.JavascriptInterface
        public void openUrl(String url) {
            runOnUiThread(() -> {
                try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
                catch (Exception ignored) { }
            });
        }
    }

    private boolean acceptsImage(String[] types) {
        if (types == null) return false;
        for (String t : types) {
            if (t != null && (t.contains("image") || t.equals("*/*") || t.isEmpty())) return true;
        }
        return false;
    }

    private boolean launchCamera() {
        try {
            File dir = new File(getCacheDir(), "camera");
            dir.mkdirs();
            File photo = new File(dir, "cam_" + System.currentTimeMillis() + ".jpg");
            cameraUri = Uri.parse("content://" + CamProvider.AUTH + "/" + photo.getName());
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                    | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            if (intent.resolveActivity(getPackageManager()) == null) {
                cameraUri = null;
                return false;
            }
            startActivityForResult(intent, CAMERA_REQ);
            return true;
        } catch (Exception e) {
            cameraUri = null;
            return false;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == CAMERA_REQ) {
            if (filePathCallback != null) {
                Uri[] r = (resultCode == RESULT_OK && cameraUri != null)
                        ? new Uri[]{cameraUri} : null;
                filePathCallback.onReceiveValue(r);
                filePathCallback = null;
            }
            cameraUri = null;
            return;
        }
        if (requestCode == FILE_REQ) {
            if (filePathCallback != null) {
                Uri[] results = null;
                if (resultCode == RESULT_OK && data != null) {
                    results = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
                    if (results == null) {   // 部分机型 parseResult 返回 null，手动兜底
                        if (data.getClipData() != null) {
                            int n = data.getClipData().getItemCount();
                            results = new Uri[n];
                            for (int i = 0; i < n; i++) {
                                results[i] = data.getClipData().getItemAt(i).getUri();
                            }
                        } else if (data.getData() != null) {
                            results = new Uri[]{ data.getData() };
                        }
                    }
                }
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        takeNotifyLink(intent);
        super.onNewIntent(intent);
        setIntent(intent);
        handleShareIntent(intent);
    }

    /** 其他应用「分享到公考助手」：文件直接上传到资料库；纯文本先存成 .txt 再上传 */
    private void handleShareIntent(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        final ArrayList<Uri> uris = new ArrayList<>();
        String text = null;
        if (Intent.ACTION_SEND.equals(action)) {
            Uri u = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) uris.add(u);
            else text = intent.getStringExtra(Intent.EXTRA_TEXT);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> us = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (us != null) uris.addAll(us);
        } else {
            return;
        }
        intent.setAction(Intent.ACTION_MAIN);  // 防旋转等重复处理
        if (uris.isEmpty() && (text == null || text.trim().isEmpty())) return;
        final String server = prefs.getString(KEY, "");
        if (server.isEmpty()) {
            Toast.makeText(this, "请先在 APP 里登录一次再分享", Toast.LENGTH_LONG).show();
            return;
        }
        final String sharedText = text;
        Toast.makeText(this, "正在上传到资料库…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            int ok = 0;
            if (sharedText != null && !sharedText.trim().isEmpty()) {
                String name = sharedText.trim();
                name = (name.length() > 12 ? name.substring(0, 12) : name) + ".txt";
                if (uploadBytes(server, name, sharedText.getBytes())) ok++;
            }
            for (Uri u : uris) {
                try {
                    String name = displayName(u);
                    InputStream in = getContentResolver().openInputStream(u);
                    java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
                    in.close();
                    if (uploadBytes(server, name, bo.toByteArray())) ok++;
                } catch (Exception ignored) { }
            }
            final int done = ok;
            runOnUiThread(() -> {
                Toast.makeText(this, done > 0 ? ("已上传 " + done + " 个到资料库") : "上传失败，请确认已登录", Toast.LENGTH_LONG).show();
                if (done > 0 && web != null)
                    web.evaluateJavascript("window.loadMaterials && loadMaterials()", null);
            });
        }).start();
    }

    private String displayName(Uri u) {
        try (Cursor c = getContentResolver().query(u, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (i >= 0 && c.getString(i) != null) return c.getString(i);
            }
        } catch (Exception ignored) { }
        String p = u.getLastPathSegment();
        return p != null ? p : ("share_" + System.currentTimeMillis());
    }

    /** 原生 multipart 上传，带 WebView 的登录 Cookie */
    private boolean uploadBytes(String server, String filename, byte[] data) {
        try {
            String boundary = "----gk" + System.currentTimeMillis();
            URL url = new URL(server.replaceAll("/+$", "") + "/api/materials");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(60000);
            String cookie = CookieManager.getInstance().getCookie(server);
            if (cookie != null) conn.setRequestProperty("Cookie", cookie);
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            OutputStream out = conn.getOutputStream();
            String head = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"board\"\r\n\r\n\r\n"
                    + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"section\"\r\n\r\n\r\n"
                    + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n\r\n"
                    + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" + filename.replace("\"", "") + "\"\r\n"
                    + "Content-Type: application/octet-stream\r\n\r\n";
            out.write(head.getBytes("UTF-8"));
            out.write(data);
            out.write(("\r\n--" + boundary + "--\r\n").getBytes("UTF-8"));
            out.flush(); out.close();
            int code = conn.getResponseCode();
            conn.disconnect();
            return code >= 200 && code < 300;
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public void onBackPressed() {
        // 边缘侧滑 / 返回键：先交给网页 SPA 退上一级；网页已在首页才退到后台
        if (web == null) { super.onBackPressed(); return; }
        if (web.canGoBack()) {
            // 兜底：若 WebView 被外站页面占据（无 appBack 可用），先回退历史
            String cur = web.getUrl();
            if (cur != null && !cur.contains("/static/") && web.getOriginalUrl() != null
                    && !Uri.parse(cur).getHost().equals(Uri.parse(web.getOriginalUrl()).getHost())) {
                web.goBack();
                return;
            }
        }
        web.evaluateJavascript("(window.appBack && window.appBack()) ? true : false",
            value -> {
                if (!"true".equals(value)) {
                    moveTaskToBack(true);   // 不杀进程，避免回来要重新登录
                }
            });
    }

    @Override
    protected void onDestroy() {
        if (tts != null) {
            try { tts.stop(); tts.shutdown(); } catch (Exception ignore) {}
            tts = null;
        }
        super.onDestroy();
    }
}
