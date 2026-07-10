package com.gongkao.app;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.SystemClock;

/**
 * 定时把服务器的新消息拉下来弹到通知栏。
 * App 没在运行也会被系统唤起（清单里静态注册），开机后自动恢复定时。
 */
public class NotifyReceiver extends BroadcastReceiver {

    static final String ACTION_POLL = "com.gongkao.app.POLL";
    static final long INTERVAL = 30 * 60 * 1000L;   // 半小时一次，用不精确闹钟省电

    @Override
    public void onReceive(Context context, Intent intent) {
        String a = intent == null ? null : intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(a) || "android.intent.action.QUICKBOOT_POWERON".equals(a)) {
            schedule(context);
            return;
        }
        Notifier.fetchAndNotify(context, false);
    }

    static PendingIntent pi(Context c) {
        Intent i = new Intent(c, NotifyReceiver.class).setAction(ACTION_POLL);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getBroadcast(c, 0, i, flags);
    }

    static void schedule(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        am.cancel(pi(c));
        if (!Notifier.enabled(c)) return;
        am.setInexactRepeating(AlarmManager.ELAPSED_REALTIME,
                SystemClock.elapsedRealtime() + INTERVAL, INTERVAL, pi(c));
    }

    static void cancel(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am != null) am.cancel(pi(c));
    }
}
