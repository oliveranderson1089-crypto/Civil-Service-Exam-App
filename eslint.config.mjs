// 前端的静态防线，对标后端的 pyflakes：只抓「会真出事」的，不管风格。
//
// app.js 是浏览器全局脚本（<script src="app.js">，非 module），10962 行、317 个顶层函数
// 全在一个作用域里互相调用——正因为没有 import 关系，人眼根本盯不住谁引用了不存在的东西。
// 后端拆分时 pyflakes 抓到的 undefined name（_SL_META、_dtest_to_wrongq…）没有一个是
// 测试能发现的；前端零测试，这道网只会更要紧。
//
// 跑：npx eslint static/app.js static/sw.js
import globals from "globals";

export default [
  {
    files: ["static/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",          // 不是 ES module，就是全局脚本
      globals: {
        ...globals.browser,          // 官方清单，别手写——手写必漏（NodeFilter/addEventListener 就漏了）
        ...globals.serviceworker,
        // app.js 的 `const Ink = {...}`（批注图层）正好撞上浏览器标准的 Ink API。
        // 是有意遮蔽，不是失误——这里放行，免得 no-redeclare 一直叫。
        Ink: "off",

        // 第三方
        Hls: "readonly",
        pdfjsLib: "readonly",

        // ---- app.js 与外壳的契约 ----
        // 这份清单以前不存在于任何地方，是 grep `window.X =` 挖出来的。
        // app.js 是全局脚本，靠 window.X 跨「模块」通信，eslint 认不出这种动态全局，
        // 所以得在这儿声明。反过来这也是唯一一份写下来的边界文档：
        // 改下面任何一个名字，就是在改 app.js 跟安卓/桌面壳之间的协议。

        // 壳 → 网页（外壳注入，app.js 只读）
        GongkaoNative: "readonly",        // 安卓 WebView 注入的原生桥
        __desktop: "readonly",            // 桌面壳（WebKit2GTK）在不在
        __desktopShot: "readonly",
        __desktopTTS: "readonly",
        __desktopVer: "readonly",

        // 网页 → 壳（app.js 挂出去给外壳回调）
        appBack: "writable",              // 安卓返回键：能退则退
        __onDropFiles: "writable",        // 桌面壳的拖放（WebKit 里 dataTransfer.files 是空的）
        __onDragOver: "writable",
        __onDragLeave: "writable",
        __onPasteImage: "writable",
        __onNotePasteImage: "writable",
        __onShot: "writable",
        __onDownloaded: "writable",
        __onSysTheme: "writable",
        __sysDark: "writable",
        __ttsEvent: "writable",
        __ttsEnd: "writable",
        __hwNative: "writable",
        __padTheme: "writable",
        __padView: "writable",
        __bmView: "writable",

        // 只用 `window.X = ...` 创建、文件里没有对应声明的——eslint 认不出来，得在这儿说明。
        // （toast / checkUpdate / Ink 不在此列：它们有 function/const 定义，只是顺手也挂了 window。）
        Reader: "writable",
        fabClose: "writable",
        _selT: "writable",
        __t0: "writable",
      },
    },
    linterOptions: { reportUnusedDisableDirectives: true },
    rules: {
      // 这条对标 pyflakes 的 undefined name —— 全局脚本里最容易出的错
      "no-undef": "error",
      // 拼错变量名、删函数漏删调用，都会被这两条兜住
      "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_",
                          caughtErrorsIgnorePattern: "^_" }],   // catch (_) 是本项目惯例
      "no-redeclare": "error",
      "no-dupe-keys": "error",
      "no-dupe-args": "error",
      "no-dupe-else-if": "error",
      "no-duplicate-case": "error",
      "no-unreachable": "error",
      "no-cond-assign": "error",
      "no-self-assign": "error",
      "no-constant-condition": ["error", { checkLoops: false }],
      // 本轮的正题：空 catch 就是「静默失败」本身
      "no-empty": ["warn", { allowEmptyCatch: false }],
      "no-fallthrough": "error",
      "use-isnan": "error",
      "valid-typeof": "error",
    },
  },
];
