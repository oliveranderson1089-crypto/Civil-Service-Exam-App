package com.gongkao.app;

import com.google.mlkit.common.model.DownloadConditions;
import com.google.mlkit.common.model.RemoteModelManager;
import com.google.mlkit.vision.digitalink.DigitalInkRecognition;
import com.google.mlkit.vision.digitalink.DigitalInkRecognitionModel;
import com.google.mlkit.vision.digitalink.DigitalInkRecognitionModelIdentifier;
import com.google.mlkit.vision.digitalink.DigitalInkRecognizer;
import com.google.mlkit.vision.digitalink.DigitalInkRecognizerOptions;
import com.google.mlkit.vision.digitalink.Ink;
import com.google.mlkit.vision.digitalink.RecognitionCandidate;
import com.google.mlkit.vision.digitalink.RecognitionContext;
import com.google.mlkit.vision.digitalink.RecognitionResult;
import com.google.mlkit.vision.digitalink.WritingArea;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 端上离线手写识别（ML Kit Digital Ink，中文 zh-Hani）。
 * 首次要联网下载一次中文模型（几 MB），之后完全离线、瞬时。
 * 结果统一以 JSON 字符串回调：{"ok":true,"candidates":[...]} 或 {"ok":false,"reason":".."}。
 */
public class Handwrite {
    public interface Cb { void done(String json); }

    private static Handwrite inst;
    private DigitalInkRecognitionModel model;
    private DigitalInkRecognizer recognizer;
    private volatile boolean modelReady = false;
    private volatile boolean downloading = false;

    public static synchronized Handwrite get() {
        if (inst == null) inst = new Handwrite();
        return inst;
    }

    private Handwrite() {
        try {
            DigitalInkRecognitionModelIdentifier id =
                    DigitalInkRecognitionModelIdentifier.fromLanguageTag("zh-Hani");
            model = DigitalInkRecognitionModel.builder(id).build();
            recognizer = DigitalInkRecognition.getClient(
                    DigitalInkRecognizerOptions.builder(model).build());
        } catch (Throwable t) {
            recognizer = null;
        }
    }

    public boolean available() { return recognizer != null; }

    /** 确保模型就绪：已下载则标记就绪，否则触发下载。cb 可空。 */
    public void ensureModel(final Cb cb) {
        if (recognizer == null) { if (cb != null) cb.done("{\"ok\":false,\"reason\":\"init\"}"); return; }
        if (modelReady) { if (cb != null) cb.done("{\"ok\":true}"); return; }
        RemoteModelManager.getInstance().isModelDownloaded(model)
                .addOnSuccessListener(dl -> {
                    if (Boolean.TRUE.equals(dl)) { modelReady = true; if (cb != null) cb.done("{\"ok\":true}"); }
                    else download(cb);
                })
                .addOnFailureListener(e -> { if (cb != null) cb.done("{\"ok\":false,\"reason\":\"check\"}"); });
    }

    private void download(final Cb cb) {
        if (downloading) { if (cb != null) cb.done("{\"ok\":false,\"reason\":\"downloading\"}"); return; }
        downloading = true;
        RemoteModelManager.getInstance()
                .download(model, new DownloadConditions.Builder().build())
                .addOnSuccessListener(v -> { modelReady = true; downloading = false; if (cb != null) cb.done("{\"ok\":true}"); })
                .addOnFailureListener(e -> { downloading = false; if (cb != null) cb.done("{\"ok\":false,\"reason\":\"download\"}"); });
    }

    /** 识别一段笔迹。inkJson = {"w":..,"h":..,"ink":[[[xs],[ys],[ts]], ...]} */
    public void recognize(final String inkJson, final Cb cb) {
        if (recognizer == null) { cb.done("{\"ok\":false,\"reason\":\"init\"}"); return; }
        if (!modelReady) { ensureModel(null); cb.done("{\"ok\":false,\"reason\":\"model\"}"); return; }
        final Ink ink;
        final RecognitionContext ctx;
        try {
            JSONObject o = new JSONObject(inkJson);
            int w = o.optInt("w", 400), h = o.optInt("h", 400);
            ink = buildInk(o.getJSONArray("ink"));
            ctx = RecognitionContext.builder().setWritingArea(new WritingArea(w, h)).setPreContext("").build();
        } catch (Throwable t) { cb.done("{\"ok\":false,\"reason\":\"ink\"}"); return; }
        try {
            recognizer.recognize(ink, ctx)
                    .addOnSuccessListener(result -> cb.done(candsJson(result)))
                    .addOnFailureListener(e -> cb.done("{\"ok\":false,\"reason\":\"recog\"}"));
        } catch (Throwable t) { cb.done("{\"ok\":false,\"reason\":\"recog\"}"); }
    }

    private Ink buildInk(JSONArray strokes) throws Exception {
        Ink.Builder ib = Ink.builder();
        for (int s = 0; s < strokes.length(); s++) {
            JSONArray st = strokes.getJSONArray(s);
            JSONArray xs = st.getJSONArray(0), ys = st.getJSONArray(1), ts = st.getJSONArray(2);
            Ink.Stroke.Builder sb = Ink.Stroke.builder();
            int n = Math.min(xs.length(), Math.min(ys.length(), ts.length()));
            for (int i = 0; i < n; i++) {
                sb.addPoint(Ink.Point.create(
                        (float) xs.getDouble(i), (float) ys.getDouble(i), (long) ts.getLong(i)));
            }
            ib.addStroke(sb.build());
        }
        return ib.build();
    }

    private String candsJson(RecognitionResult result) {
        JSONArray arr = new JSONArray();
        try {
            for (RecognitionCandidate c : result.getCandidates()) arr.put(c.getText());
        } catch (Throwable ignored) {}
        JSONObject o = new JSONObject();
        try { o.put("ok", true); o.put("candidates", arr); } catch (Throwable ignored) {}
        return o.toString();
    }
}
