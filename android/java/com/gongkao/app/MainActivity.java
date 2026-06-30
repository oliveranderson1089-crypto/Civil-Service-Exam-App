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

import java.io.File;

/**
 * 公考积累 安卓壳：一个全屏 WebView，加载电脑上运行的服务地址。
 * - 首次启动 / 连接失败时弹窗让用户填服务器地址（默认局域网 IP）。
 * - 顶部菜单可“刷新”“设置服务器地址”。
 * - 导出 PDF 时交给系统下载器（带上登录 Cookie），存到“下载”目录。
 */
public class MainActivity extends Activity {

    private WebView web;
    private SharedPreferences prefs;
    private ValueCallback<Uri[]> filePathCallback;   // 网页文件选择回调
    private Uri cameraUri;                            // 拍照输出 URI
    private static final int FILE_REQ = 1001;
    private static final int CAMERA_REQ = 1002;
    private static final String KEY = "server_url";
    // 默认地址：固定公网网址（命名隧道，重启不变）；在家也可在 APP 内改成局域网 IP 提速
    private static final String DEF = "https://gk.gongkaopei2026.click";

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

        // 原生桥接：网页「设置」里可调用，改服务器地址 / 刷新
        web.addJavascriptInterface(new Bridge(), "GongkaoNative");

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
    public class Bridge {
        @android.webkit.JavascriptInterface
        public void changeServer() { runOnUiThread(() -> promptUrl(false)); }

        @android.webkit.JavascriptInterface
        public void reload() { runOnUiThread(() -> web.reload()); }
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
    public void onBackPressed() {
        // 边缘侧滑 / 返回键：先交给网页 SPA 退上一级；网页已在首页才退到后台
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript("(window.appBack && window.appBack()) ? true : false",
            value -> {
                if (!"true".equals(value)) {
                    moveTaskToBack(true);   // 不杀进程，避免回来要重新登录
                }
            });
    }
}
