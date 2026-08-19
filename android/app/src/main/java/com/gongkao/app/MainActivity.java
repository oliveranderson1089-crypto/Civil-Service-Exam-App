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
import android.webkit.PermissionRequest;
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
    // 视频全屏：WebView 里点全屏（HTML5 全屏 API 或 <video> 原生全屏）都会走 onShowCustomView，
    // 壳不接这个回调的话，全屏就点了没反应 —— 这些字段用来托管那个全屏视图。
    private android.view.View fsView;
    private WebChromeClient.CustomViewCallback fsCallback;
    private int fsSavedOrientation;
    private static final int FILE_REQ = 1001;
    private static final int CAMERA_REQ = 1002;
    private static final String KEY = "server_url";
    private static final int NOTIFY_PERM_REQ = 1003;
    private static final int MIC_PERM_REQ = 1004;
    private PermissionRequest pendingMic = null;     // 等系统权限批下来再放行的那次网页请求
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
            /* 网页要用麦克风（聊天发语音、语音转文字）。WebView 默认一律拒绝，
               不接这个回调的话，网页那边只会收到一句「没拿到麦克风权限」。
               两层权限要分清：这里是**网页向 WebView 要**，系统那层还得单独申请。 */
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        boolean wantMic = false;
                        for (String r : request.getResources()) {
                            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) wantMic = true;
                        }
                        if (!wantMic) { request.deny(); return; }   // 只放麦克风，别的一概不给
                        try {
                            if (android.os.Build.VERSION.SDK_INT >= 23
                                    && checkSelfPermission("android.permission.RECORD_AUDIO")
                                       != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                                pendingMic = request;               // 批下来之后在回调里再 grant
                                requestPermissions(new String[]{"android.permission.RECORD_AUDIO"},
                                                   MIC_PERM_REQ);
                                return;
                            }
                            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                        } catch (Exception e) { request.deny(); }
                    }
                });
            }

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

                // accept 里可能写的是扩展名（.pdf）而不是 MIME。扩展名塞进 setType()
                // 会让系统挑选器退化成「只能选最近的图片」，所以先统一转成 MIME。
                String[] types = params.getAcceptTypes();
                java.util.ArrayList<String> mimes = new java.util.ArrayList<>();
                boolean unresolved = false, allImage = true;
                if (types != null) {
                    for (String t : types) {
                        if (t == null || t.trim().isEmpty()) continue;
                        String m = toMime(t);
                        if (m == null) { unresolved = true; continue; }
                        if (!mimes.contains(m)) mimes.add(m);
                        if (!m.startsWith("image/")) allImage = false;
                    }
                }
                if (mimes.isEmpty()) allImage = false;

                boolean multiple = false;
                try { multiple = params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE; } catch (Exception ignore) {}

                Intent intent;
                boolean chooser;
                if (allImage && !unresolved) {
                    // 纯图片：走相册，体验最好
                    intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.setType("image/*");
                    chooser = true;
                } else {
                    // 含 PDF/Word/PPT 或混合类型：走系统文档界面，能浏览文件夹、可靠多选
                    intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                    intent.setType("*/*");
                    // 只有全部 accept 都能解析成 MIME 才加过滤，否则宁可全都显示出来
                    if (!mimes.isEmpty() && !unresolved) {
                        intent.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
                    }
                    chooser = false;
                }
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                if (multiple) intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);

                try {
                    startActivityForResult(chooser ? Intent.createChooser(intent, "选择图片") : intent, FILE_REQ);
                } catch (ActivityNotFoundException e) {
                    try {   // 个别机型没有 DocumentsUI，退回 GET_CONTENT
                        Intent fb = new Intent(Intent.ACTION_GET_CONTENT);
                        fb.addCategory(Intent.CATEGORY_OPENABLE);
                        fb.setType("*/*");
                        if (multiple) fb.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                        startActivityForResult(Intent.createChooser(fb, "选择文件"), FILE_REQ);
                    } catch (Exception e2) {
                        filePathCallback = null;
                        Toast.makeText(MainActivity.this, "没有可用的文件选择器", Toast.LENGTH_LONG).show();
                        return false;
                    }
                }
                return true;
            }

            // 视频全屏：网页请求全屏时，WebView 把那个「铺满的视图」交到这里。
            // 我们把它盖到根视图上、把 WebView 藏起来，就成了真全屏。不接这个回调 = 点全屏没反应。
            @Override
            public void onShowCustomView(android.view.View view, CustomViewCallback cb) {
                if (fsView != null) {                 // 已经有一个全屏视图了，别叠
                    cb.onCustomViewHidden();
                    return;
                }
                fsView = view;
                fsCallback = cb;
                fsSavedOrientation = getRequestedOrientation();
                android.widget.FrameLayout decor = (android.widget.FrameLayout) getWindow().getDecorView();
                decor.addView(fsView, new android.widget.FrameLayout.LayoutParams(
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT));
                web.setVisibility(android.view.View.GONE);
                setFullscreenUi(true);               // 顺手把状态栏/导航栏也藏掉，沉浸式
            }

            @Override
            public void onHideCustomView() {
                if (fsView == null) return;
                android.widget.FrameLayout decor = (android.widget.FrameLayout) getWindow().getDecorView();
                decor.removeView(fsView);
                fsView = null;
                web.setVisibility(android.view.View.VISIBLE);
                if (fsCallback != null) { fsCallback.onCustomViewHidden(); fsCallback = null; }
                setFullscreenUi(false);
                setRequestedOrientation(fsSavedOrientation);
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
        // 轮询改成「前台不轮询、退后台才轮询」（见 onResume/onStop）——前台有 SSE 秒推，
        // 省得每台设备开着 App 还每 5 分钟空敲一次服务器。
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

    /** 系统麦克风权限的结果回来了：批了就把网页那次请求放行，拒了就明确拒掉
     *  —— 挂着不回应的话，网页那边的录音会一直卡在「等权限」。 */
    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        super.onRequestPermissionsResult(req, perms, results);
        if (req != MIC_PERM_REQ || pendingMic == null) return;
        PermissionRequest r = pendingMic;
        pendingMic = null;
        boolean ok = results != null && results.length > 0
                && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED;
        try {
            if (ok) r.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else r.deny();
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

    /** 分享进度回网页：0~100 是百分比，100 表示可以弹分享面板了，-1 表示失败。 */
    private void shareProgress(int pct) {
        final String js = "window.__shareProgress && window.__shareProgress(" + pct + ")";
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    /** 更新包下载进度回网页：0~100 是百分比，-1 表示失败（壳自己会弹 Toast + 通知）。 */
    private void updProgress(int pct) {
        final String js = "window.__updProgress && window.__updProgress(" + pct + ")";
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    /** 聊天文件下载的进度/结果回传给网页（网页把它画在那条消息自己的卡片上）。 */
    private void chatDlJs(String fn, String tag, String arg2, long a, long b, long c) {
        final String t = tag == null ? "" : tag.replaceAll("[^0-9A-Za-z_]", "");
        final String js;
        if ("__chatDl".equals(fn)) {
            js = "window.__chatDl && window.__chatDl('" + t + "'," + a + "," + b + "," + c + ")";
        } else {
            String q = arg2 == null ? "" : arg2.replace("\\", "\\\\").replace("'", "\\'")
                    .replace("\n", " ").replace("\r", " ");
            js = "window." + fn + " && window." + fn + "('" + t + "','" + q + "')";
        }
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    /** 取消标记：网页点了「取消」就往这里放一个，下载线程读到就收手。 */
    private final java.util.Set<String> dlCancelled =
            java.util.Collections.synchronizedSet(new java.util.HashSet<String>());

    /**
     * 聊天文件下载：自己拉 HTTP、自己报进度，落进系统「下载」目录。
     *
     * 为什么不继续用 DownloadManager：它的进度只在系统通知栏，应用里一点动静没有 ——
     * 人看不见反馈就会反复点，同一份文件下三四遍。这条路和更新包那套是同一个写法
     * （见 updateApp），区别只是把百分比回调给网页而不是通知栏。
     * 安卓 10 以下没有 MediaStore.Downloads，写公共目录要另外申请权限，不值当，
     * 那种老机器仍旧交给 DownloadManager（通知栏里有进度）。
     */
    @android.annotation.TargetApi(29)      // 调用方按 SDK_INT 分流，见 Bridge.downloadFile
    private void chatDownload(String url, String name, String tag) {
        String safe = (name == null || name.trim().isEmpty())
                ? ("文件_" + System.currentTimeMillis())
                : name.replaceAll("[/\\\\:*?\"<>|]", "_");
        dlCancelled.remove(tag);
        HttpURLConnection conn = null;
        InputStream in = null;
        OutputStream out = null;
        Uri target = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) conn.setRequestProperty("Cookie", cookie);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(300000);
            int code = conn.getResponseCode();
            if (code / 100 != 2) throw new java.io.IOException("HTTP " + code);
            long total = conn.getContentLength();          // 没有就是 -1，网页画来回跑的条
            String mime = conn.getContentType();
            if (mime != null && mime.contains(";")) mime = mime.substring(0, mime.indexOf(';')).trim();
            android.content.ContentValues cv = new android.content.ContentValues();
            cv.put(MediaStore.Downloads.DISPLAY_NAME, safe);
            if (mime != null && !mime.isEmpty()) cv.put(MediaStore.Downloads.MIME_TYPE, mime);
            cv.put(MediaStore.Downloads.IS_PENDING, 1);
            target = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
            if (target == null) throw new java.io.IOException("写不进「下载」文件夹");
            out = getContentResolver().openOutputStream(target);
            if (out == null) throw new java.io.IOException("写不进「下载」文件夹");
            in = conn.getInputStream();
            byte[] buf = new byte[65536];
            long got = 0, lastAt = 0;
            int n, last = -2;
            while ((n = in.read(buf)) > 0) {
                if (dlCancelled.contains(tag)) throw new InterruptedException("已取消");
                out.write(buf, 0, n);
                got += n;
                int pct = total > 0 ? (int) (got * 100 / total) : -1;
                long now = System.currentTimeMillis();
                if ((pct != last || pct < 0) && now - lastAt >= 200) {
                    last = pct; lastAt = now;
                    chatDlJs("__chatDl", tag, null, pct, got, total);
                }
            }
            out.flush();
            out.close(); out = null;
            in.close(); in = null;
            android.content.ContentValues fin = new android.content.ContentValues();
            fin.put(MediaStore.Downloads.IS_PENDING, 0);
            getContentResolver().update(target, fin, null, null);
            chatDlJs("__chatDlDone", tag, target.toString(), 0, 0, 0);
        } catch (InterruptedException cancel) {
            // 网页那边已经把这张卡恢复原样了，这里只负责别留下半个文件
            closeQuietly(out); closeQuietly(in);
            out = null; in = null;
            if (target != null) {
                try { getContentResolver().delete(target, null, null); } catch (Exception ignore) { }
            }
        } catch (Exception e) {
            closeQuietly(out); closeQuietly(in);
            out = null; in = null;
            if (target != null) {
                try { getContentResolver().delete(target, null, null); } catch (Exception ignore) { }
            }
            chatDlJs("__chatDlFail", tag, String.valueOf(e.getMessage()), 0, 0, 0);
        } finally {
            closeQuietly(out); closeQuietly(in);
            if (conn != null) conn.disconnect();
            dlCancelled.remove(tag);
        }
    }

    private static void closeQuietly(java.io.Closeable c) {
        if (c != null) { try { c.close(); } catch (Exception ignore) { } }
    }

    /** 老老实实交给系统下载器（安卓 9 及以下，或 MediaStore 那条路走不通时）。 */
    private void chatDownloadBySystem(String url, String name, String tag) {
        try {
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) req.addRequestHeader("Cookie", cookie);
            String fn = (name == null || name.trim().isEmpty()) ? "下载的文件" : name;
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fn);
            ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(req);
            chatDlJs("__chatDlSys", tag, "", 0, 0, 0);
        } catch (Exception e) {
            chatDlJs("__chatDlFail", tag, String.valueOf(e.getMessage()), 0, 0, 0);
        }
    }

    /** 读一个很小的伴随文件（ETag / Last-Modified）；没有或读不了都当没有。 */
    private static String readSmall(File f) {
        try (java.io.FileInputStream in = new java.io.FileInputStream(f)) {
            byte[] b = new byte[512];
            int n = in.read(b);
            return n > 0 ? new String(b, 0, n, "UTF-8").trim() : null;
        } catch (Exception e) { return null; }
    }

    private static void writeSmall(File f, String s) {
        if (s == null || s.isEmpty()) { f.delete(); return; }
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(f)) {
            o.write(s.getBytes("UTF-8"));
        } catch (Exception ignored) { }
    }

    /** 把离线手写识别结果（JSON 字符串）安全地回调给网页的 window.__hwNative。 */
    private void deliverHw(int reqId, String json) {
        final String js = "window.__hwNative && window.__hwNative(" + reqId + ",'" + jsEsc(json) + "')";
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(js, null); });
    }

    private static String jsEsc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' || c == '\'') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c == '\r') b.append("\\r");
            else b.append(c);
        }
        return b.toString();
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

        /** 跳到本应用的系统设置页。

         *  麦克风被拒过（尤其勾了「不再询问」）之后，再怎么 requestPermissions 系统都直接
         *  回拒——只能人去设置里改。网页那边弹一句「去设置吗」，点确定就走这条，
         *  省得用户自己在设置里翻应用列表。 */
        @android.webkit.JavascriptInterface
        public void openAppSettings() {
            runOnUiThread(() -> {
                try {
                    Intent i = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                          Uri.fromParts("package", getPackageName(), null));
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(i);
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "打不开设置页，请手动到「设置 → 应用 → 公考助手 → 权限」里开麦克风",
                                   Toast.LENGTH_LONG).show();
                }
            });
        }

        /** 真去开一次麦克风，看看到底卡在哪。

         *  网页那边只能拿到一个笼统的 NotReadableError（「设备打不开」），到底是别的应用
         *  占着、还是权限没真给、还是 WebView 自己的事，全靠猜。这里绕开 WebView 直接用
         *  AudioRecord 试一下，把区别测出来：
         *    ok     系统这层能录 → 那就是 WebView 那层的问题（重启应用往往就好）
         *    busy   设备真被别人占着（通话、录音机、语音助手…）
         *    denied 系统权限其实没给
         *  只在**网页录音已经失败之后**调，那时 WebView 没有占着麦克风，不会互相打架。 */
        @android.webkit.JavascriptInterface
        public String micProbe() {
            android.media.AudioRecord ar = null;
            try {
                if (android.os.Build.VERSION.SDK_INT >= 23
                        && checkSelfPermission("android.permission.RECORD_AUDIO")
                           != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    return "denied";
                }
                int min = android.media.AudioRecord.getMinBufferSize(
                        16000, android.media.AudioFormat.CHANNEL_IN_MONO,
                        android.media.AudioFormat.ENCODING_PCM_16BIT);
                if (min <= 0) min = 4096;
                ar = new android.media.AudioRecord(
                        android.media.MediaRecorder.AudioSource.MIC, 16000,
                        android.media.AudioFormat.CHANNEL_IN_MONO,
                        android.media.AudioFormat.ENCODING_PCM_16BIT, min * 2);
                if (ar.getState() != android.media.AudioRecord.STATE_INITIALIZED) return "denied";
                ar.startRecording();
                boolean going = ar.getRecordingState()
                                == android.media.AudioRecord.RECORDSTATE_RECORDING;
                ar.stop();
                return going ? "ok" : "busy";
            } catch (Exception e) {
                return "err:" + e.getClass().getSimpleName();
            } finally {
                if (ar != null) { try { ar.release(); } catch (Exception ignored) {} }
            }
        }

        /** 立刻去服务器拉一次新消息（网页里「立即检查」用）。 */
        @android.webkit.JavascriptInterface
        public void notifyCheck() { Notifier.fetchAndNotify(MainActivity.this, true); }

        /** 发一条测试通知，验证通知权限有没有被系统挡掉。 */
        @android.webkit.JavascriptInterface
        public void notifyTest() { Notifier.showTest(MainActivity.this); }

        /** 前台（App 开着）收到聊天消息时，网页调这个直接弹一条系统通知——秒推，不用等轮询。
         *  tag 形如 "chat:<好友id>"；点通知打开对应会话。 */
        @android.webkit.JavascriptInterface
        public void notify(final String title, final String body, final String tag) {
            if (!Notifier.enabled(MainActivity.this)) return;
            runOnUiThread(() -> {
                try {
                    Notifier.ensureChannel(MainActivity.this);
                    String t = tag == null ? "" : tag;
                    int id = 700000 + Math.abs(t.hashCode() % 90000);        // 同一会话覆盖更新，不刷屏
                    String link = t.startsWith("chat:") ? ("chatroom:" + t.substring(5)) : "";
                    Notifier.show(MainActivity.this, id, title == null ? "新消息" : title,
                                  body == null ? "" : body, link);
                } catch (Exception ignored) {}
            });
        }

        /** 网页请求通知权限（Android 13+ 需要）。 */
        @android.webkit.JavascriptInterface
        public void requestNotifyPerm() { runOnUiThread(MainActivity.this::askNotifyPermission); }

        @android.webkit.JavascriptInterface
        public boolean sysDark() { return sysDarkNow(); }

        @android.webkit.JavascriptInterface
        public void fullscreen(boolean on) { runOnUiThread(() -> setFullscreenUi(on)); }

        @android.webkit.JavascriptInterface
        public void changeServer() { runOnUiThread(() -> promptUrl(false)); }

        @android.webkit.JavascriptInterface
        public void reload() { runOnUiThread(() -> web.reload()); }

        /** 端上离线手写：是否可用（在 APK 里即可用）。 */
        @android.webkit.JavascriptInterface
        public boolean hwAvailable() { return Handwrite.get().available(); }

        /** 预下载中文手写模型（首次联网一次，之后离线）。 */
        @android.webkit.JavascriptInterface
        public void hwPrepare() { Handwrite.get().ensureModel(null); }

        /** 识别一段笔迹；结果异步经 window.__hwNative(reqId, jsonStr) 回调。 */
        @android.webkit.JavascriptInterface
        public void hwRecognize(final int reqId, final String inkJson) {
            Handwrite.get().recognize(inkJson, json -> deliverHw(reqId, json));
        }

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

        /** 下载新版 APK 并唤起系统安装界面（不用再去浏览器点链接）。
         *
         *  下载少则十几秒、多则几分钟，期间用户多半已经切走了 —— 所以进度得走通知栏：
         *  一条常驻通知带进度条，下好了变成「点这里安装」。App 还在前台时照旧直接弹安装界面，
         *  但后台时系统会拦掉 startActivity，那条通知就是唯一的入口。 */
        @android.webkit.JavascriptInterface
        public void updateApp(String url) { updateApp(url, ""); }

        @android.webkit.JavascriptInterface
        public void updateApp(String url, String ver) {
            new Thread(() -> {
                try {
                    runOnUiThread(() -> Toast.makeText(MainActivity.this,
                            "正在下载新版…", Toast.LENGTH_SHORT).show());
                    Notifier.downloading(MainActivity.this, -1, 0, 0);
                    File dir = new File(getCacheDir(), "share");   // CamProvider 已开放这个目录
                    dir.mkdirs();
                    File out = new File(dir, "gongkao-update.apk");
                    // 先下到 .part 再改名：中途断网/杀进程也不会在缓存里留下半份 APK，
                    // 半份 APK 交给安装器只会得到一句「解析软件包时出现问题」。
                    File tmp = new File(dir, "gongkao-update.apk.part");
                    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(300000);
                    int code = conn.getResponseCode();
                    if (code / 100 != 2) throw new java.io.IOException("HTTP " + code);
                    long total = conn.getContentLength();          // 没有就是 -1，画无限进度条
                    InputStream in = conn.getInputStream();
                    java.io.FileOutputStream fo = new java.io.FileOutputStream(tmp);
                    byte[] buf = new byte[65536];
                    long got = 0, lastAt = 0;
                    int n, last = -2;
                    while ((n = in.read(buf)) > 0) {
                        fo.write(buf, 0, n);
                        got += n;
                        int pct = total > 0 ? (int) (got * 100 / total) : -1;
                        long now = System.currentTimeMillis();
                        // 通知栏刷太密会被系统限流（每秒十几条就开始丢），400ms 一次足够顺滑
                        if ((pct != last || pct < 0) && now - lastAt >= 400) {
                            last = pct; lastAt = now;
                            Notifier.downloading(MainActivity.this, pct, got, total);
                            updProgress(pct);
                        }
                    }
                    fo.close(); in.close(); conn.disconnect();
                    if (tmp.length() < 10000) throw new Exception("下载不完整");
                    if (out.exists() && !out.delete()) throw new Exception("旧安装包删不掉");
                    if (!tmp.renameTo(out)) throw new Exception("保存失败");
                    final Uri apk = Uri.parse("content://" + CamProvider.AUTH + "/share/gongkao-update.apk");
                    Notifier.downloadDone(MainActivity.this, apk, ver);
                    updProgress(100);
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
                    Notifier.downloadFailed(MainActivity.this, e.getMessage());
                    updProgress(-1);
                    runOnUiThread(() -> Toast.makeText(MainActivity.this,
                            "更新失败：" + e.getMessage(), Toast.LENGTH_LONG).show());
                }
            }).start();
        }

        /**
         * 分享资料库里的一个文件：得先把它从服务器整份拉到本地（安卓只能分享本地 Uri），
         * 再弹系统分享面板。慢就慢在这一步——一份 6.7 MB 的讲义每分享一次就重下一次。
         *
         * 两件事让它别再慢：
         *   · **带条件的 GET**：缓存里有上次那份就带 If-None-Match / If-Modified-Since，
         *     服务端（Flask send_file）回 304 就直接用本地那份，一个字节都不用传。
         *   · **报进度**：真要下的时候把百分比回调给网页，让它显示在 toast 上。
         *     原来只有一句「正在准备分享…」，几十秒里看不出是在跑还是卡死了。
         */
        /** 下载聊天里的文件，进度回调给网页（网页画在那条消息的卡片上）。 */
        @android.webkit.JavascriptInterface
        public void downloadFile(final String url, final String name, final String tag) {
            if (url == null || url.isEmpty()) return;
            if (android.os.Build.VERSION.SDK_INT < 29) {   // 老机器没有 MediaStore.Downloads
                new Thread(() -> chatDownloadBySystem(url, name, tag)).start();
                return;
            }
            new Thread(() -> chatDownload(url, name, tag)).start();
        }

        @android.webkit.JavascriptInterface
        public void cancelDownload(String tag) { if (tag != null) dlCancelled.add(tag); }

        /** 打开刚下好的那份文件（网页点卡片上的「打开」）。 */
        @android.webkit.JavascriptInterface
        public void openDownload(final String uri) {
            if (uri == null || uri.isEmpty()) return;
            runOnUiThread(() -> {
                try {
                    Uri u = Uri.parse(uri);
                    Intent i = new Intent(Intent.ACTION_VIEW);
                    String mime = getContentResolver().getType(u);
                    i.setDataAndType(u, mime == null ? "*/*" : mime);
                    i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(i);
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "没有能打开它的应用", Toast.LENGTH_SHORT).show();
                }
            });
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
                    File meta = new File(dir, safe + ".etag");

                    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(120000);
                    // 缓存命中的前提是本地那份确实还在；只剩 .etag 没剩文件时别发条件请求，
                    // 否则服务端回 304、我们却没有可分享的文件。
                    String tag = out.exists() ? readSmall(meta) : null;
                    if (tag != null && !tag.isEmpty()) {
                        if (tag.startsWith("W/") || tag.startsWith("\"")) conn.setRequestProperty("If-None-Match", tag);
                        else conn.setRequestProperty("If-Modified-Since", tag);
                    }

                    int code = conn.getResponseCode();
                    if (code != HttpURLConnection.HTTP_NOT_MODIFIED) {
                        if (code / 100 != 2) throw new java.io.IOException("HTTP " + code);
                        // 用 int 版：getContentLengthLong() 要 API 24，这个 APK 的 minSdk 是 21。
                        // 资料库里没有 2 GB 以上的文件，够用。
                        long total = conn.getContentLength();
                        InputStream in = conn.getInputStream();
                        // 下到临时文件再改名：中途断网/杀进程也不会在缓存里留下半份文件，
                        // 而半份文件配上还在的 .etag 会让下一次条件请求拿 304 —— 分享出去是坏文件。
                        File tmp = new File(dir, safe + ".part");
                        java.io.FileOutputStream fo = new java.io.FileOutputStream(tmp);
                        byte[] buf = new byte[65536];
                        long got = 0;
                        int n, last = -1;
                        while ((n = in.read(buf)) > 0) {
                            fo.write(buf, 0, n);
                            got += n;
                            if (total > 0) {
                                int pct = (int) (got * 100 / total);
                                if (pct != last && pct % 5 == 0) { last = pct; shareProgress(pct); }
                            }
                        }
                        fo.close(); in.close();
                        if (out.exists()) out.delete();
                        if (!tmp.renameTo(out)) throw new java.io.IOException("写缓存失败");
                        String et = conn.getHeaderField("ETag");
                        if (et == null) et = conn.getHeaderField("Last-Modified");
                        writeSmall(meta, et);
                    }
                    conn.disconnect();
                    if (!out.exists()) throw new java.io.IOException("缓存里没有这个文件");

                    shareProgress(100);
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
                    shareProgress(-1);
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

    /** accept 里可能是 "image/*" 也可能是 ".pdf"，统一转成 MIME；转不出来返回 null。 */
    private static String toMime(String t) {
        if (t == null) return null;
        t = t.trim();
        if (t.isEmpty()) return null;
        if (t.contains("/")) return t;                      // 本来就是 MIME
        String ext = (t.startsWith(".") ? t.substring(1) : t).toLowerCase(Locale.US);
        // MimeTypeMap 在部分机型上认不出 docx/pptx，这里先兜住常用的
        if (ext.equals("pdf")) return "application/pdf";
        if (ext.equals("doc")) return "application/msword";
        if (ext.equals("docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (ext.equals("ppt")) return "application/vnd.ms-powerpoint";
        if (ext.equals("pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        if (ext.equals("xls")) return "application/vnd.ms-excel";
        if (ext.equals("xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        if (ext.equals("txt") || ext.equals("md")) return "text/plain";
        return android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
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
    protected void onResume() {
        super.onResume();
        // 回到前台：SSE 秒推接管 → 停掉定时轮询（省服务器/省电）；顺手拉一次补上后台漏的
        NotifyReceiver.cancel(this);
        if (Notifier.enabled(this)) Notifier.fetchAndNotify(this, false);
    }

    @Override
    protected void onStop() {
        super.onStop();
        // 退到后台/锁屏：前台 SSE 断了 → 起 5 分钟定时轮询兜底
        NotifyReceiver.schedule(this);
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
        // 视频全屏时，返回键先退出全屏（否则会直接退到上一页/后台，很突兀）
        if (fsView != null) {
            web.evaluateJavascript(
                "document.exitFullscreen ? document.exitFullscreen() : "
                + "(document.webkitExitFullscreen && document.webkitExitFullscreen())", null);
            return;
        }
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
