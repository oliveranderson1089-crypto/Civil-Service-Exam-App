package com.gongkao.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.webkit.CookieManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 把服务器上的「消息中心」拉下来，变成手机系统通知栏里的通知。
 * 点通知 → 打开 App 并跳到对应页面（link 由网页端的 ntfGo() 解析）。
 */
public class Notifier {

    static final String CHANNEL = "gongkao_updates";
    static final String PREF = "cfg";
    static final String KEY_ENABLED = "notify_enabled";
    static final String KEY_LAST_ID = "notify_last_id";
    static final String EXTRA_LINK = "notify_link";
    static final int MAX_PER_FETCH = 5;             // 一次最多弹 5 条，免得刷屏

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    static boolean enabled(Context c) {
        return prefs(c).getBoolean(KEY_ENABLED, true);   // 默认开
    }

    static String serverUrl(Context c) {
        return prefs(c).getString("server_url", MainActivity.DEF);
    }

    static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null || nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(
                CHANNEL, "学习提醒", NotificationManager.IMPORTANCE_DEFAULT);
        ch.setDescription("常识/时政更新、今日复习、任务打卡等提醒");
        nm.createNotificationChannel(ch);
    }

    /** 后台线程里调用：拉未读消息 → 逐条弹通知。 */
    static void fetchAndNotify(final Context c, final boolean force) {
        if (!force && !enabled(c)) return;
        new Thread(new Runnable() {
            public void run() {
                try {
                    String base = serverUrl(c);
                    if (base.endsWith("/")) base = base.substring(0, base.length() - 1);
                    String url = base + "/api/notifications";
                    HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie == null || cookie.isEmpty()) return;   // 没登录就别打扰
                    conn.setRequestProperty("Cookie", cookie);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(40000);
                    if (conn.getResponseCode() != 200) return;

                    StringBuilder sb = new StringBuilder();
                    BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), "UTF-8"));
                    String line;
                    while ((line = br.readLine()) != null) sb.append(line);
                    br.close();
                    conn.disconnect();

                    JSONObject root = new JSONObject(sb.toString());
                    JSONArray items = root.optJSONArray("items");
                    if (items == null) return;

                    ensureChannel(c);
                    int lastId = prefs(c).getInt(KEY_LAST_ID, 0);
                    int maxId = lastId;

                    // 先挑出「没弹过且未读」的，再只留最新的几条——
                    // 直接边遍历边弹会因为条数上限把最新的挤掉，而 lastId 又已经推进，那几条就永远看不到了
                    java.util.ArrayList<JSONObject> todo = new java.util.ArrayList<>();
                    for (int i = 0; i < items.length(); i++) {
                        JSONObject it = items.getJSONObject(i);
                        int id = it.optInt("id");
                        if (id > maxId) maxId = id;
                        if (id <= lastId) continue;                 // 弹过了
                        if (it.optInt("read", 0) == 1) continue;    // 已在网页里读过
                        todo.add(it);
                    }
                    // 服务端按 id 倒序返回，todo 里也是新的在前；只留最新的 MAX_PER_FETCH 条
                    while (todo.size() > MAX_PER_FETCH) todo.remove(todo.size() - 1);
                    // 倒着弹，让通知栏里按时间正序堆叠
                    for (int i = todo.size() - 1; i >= 0; i--) {
                        JSONObject it = todo.get(i);
                        show(c, it.optInt("id"), it.optString("title"),
                                it.optString("body"), it.optString("link"));
                    }
                    if (maxId != lastId) prefs(c).edit().putInt(KEY_LAST_ID, maxId).apply();
                } catch (Exception ignored) { }
            }
        }).start();
    }

    static void show(Context c, int id, String title, String body, String link) {
        Intent i = new Intent(c, MainActivity.class);
        i.setAction(Intent.ACTION_VIEW);
        i.setData(Uri.parse("gongkao://notify/" + id));   // 让每条通知的 PendingIntent 互不覆盖
        i.putExtra(EXTRA_LINK, link);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pi = PendingIntent.getActivity(c, id, i, flags);

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(c, CHANNEL);
        } else {
            b = new Notification.Builder(c);
        }
        b.setSmallIcon(R.drawable.ic_notify)   // 纯白剪影，系统会自己上色
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setContentIntent(pi);

        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(id, b.build());
    }

    /** 「发送测试通知」用，不经过服务器。 */
    static void showTest(Context c) {
        ensureChannel(c);
        show(c, 999999, "公考助手 · 测试通知",
                "如果你在通知栏看到这条，说明手机通知已经开好了。点一下会回到 App。", "");
    }
}
