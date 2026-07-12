package com.gongkao.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * 极简文件提供者：把缓存目录 camera/ 下的文件以 content:// 暴露给相机应用写入，
 * 拍照后再交回 WebView 读取上传。替代 androidx FileProvider（本工程无 androidx 依赖）。
 */
public class CamProvider extends ContentProvider {
    public static final String AUTH = "com.gongkao.app.camprovider";

    private File fileFor(Uri uri) {
        java.util.List<String> seg = uri.getPathSegments();
        String dir = "camera", name;
        if (seg.size() >= 2 && (seg.get(0).equals("camera") || seg.get(0).equals("share"))) {
            dir = seg.get(0); name = seg.get(seg.size() - 1);
        } else {
            name = uri.getLastPathSegment();
        }
        return new File(new File(getContext().getCacheDir(), dir), name);
    }

    @Override
    public boolean onCreate() { return true; }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = fileFor(uri);
        if (f.getParentFile() != null) f.getParentFile().mkdirs();
        int m = "r".equals(mode)
                ? ParcelFileDescriptor.MODE_READ_ONLY
                : ParcelFileDescriptor.MODE_READ_WRITE | ParcelFileDescriptor.MODE_CREATE;
        return ParcelFileDescriptor.open(f, m);
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        File f = fileFor(uri);
        MatrixCursor c = new MatrixCursor(
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, 1);
        c.addRow(new Object[]{f.getName(), f.length()});
        return c;
    }

    @Override
    public String getType(Uri uri) {
        String n = uri.getLastPathSegment();
        if (n == null) return "application/octet-stream";
        n = n.toLowerCase();
        String ext = n.contains(".") ? n.substring(n.lastIndexOf('.') + 1) : "";
        String mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
        if (mime != null) return mime;
        return ext.isEmpty() ? "image/jpeg" : "application/octet-stream";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) { return null; }

    @Override
    public int delete(Uri uri, String s, String[] a) { return 0; }

    @Override
    public int update(Uri uri, ContentValues v, String s, String[] a) { return 0; }
}
