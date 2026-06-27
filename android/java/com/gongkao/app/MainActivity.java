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
    private static final int FILE_REQ = 1001;
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
        // 关键：标记“APP 内”，前端据此用 GET 链接触发系统下载
        ws.setUserAgentString(ws.getUserAgentString() + " GongkaoApp");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);

        web.setWebChromeClient(new WebChromeClient() {
            // 关键：让网页里的「选择文件」能唤起系统文件选择器
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = cb;
                Intent intent;
                try {
                    intent = params.createIntent();
                } catch (Exception e) {
                    intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("*/*");
                }
                try {
                    startActivityForResult(intent, FILE_REQ);
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

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "刷新");
        menu.add(0, 2, 0, "设置服务器地址");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) {
            web.reload();
            return true;
        }
        if (item.getItemId() == 2) {
            promptUrl(false);
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQ) {
            if (filePathCallback != null) {
                Uri[] results = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
