# 公考助手 Civil-Service-Exam-App

一个公务员考试备考工具：**网页 + 安卓 APK**，多用户、可远程访问、可离线缓存（PWA）。
从「成语词语积累」起步，现已扩展成集**笔记、知识库、资料管理、古诗文速查、全文搜索、OCR**于一体的备考工作台。

> 在线体验（作者自部署）：**https://gk.gongkaopei2026.click**

---

## 功能总览

登录后首页是卡片式入口：**行测 / 申论 / 小记 / 知识库 / 资料库**，顶部带**全文搜索**。

| 模块 | 说明 |
|------|------|
| **行测 / 申论** | 行测含 6 个板块（常识判断 / 资料分析 / 判断推理 / 数量关系 / 政治理论 / 言语理解与表达），申论含 应用文 / 议论文。 |
| **成语词语积累** | 在「言语理解与表达」下。输入即自动注音 + 释义（成语带出处、例句），可收录 / 收藏 / 写笔记，一键导出 PDF（学习版 / 默写版）。 |
| **古诗文·名句速查** | 在「议论文」下。**唐诗三百首 / 宋词三百首 / 诗经 / 论语 / 孟子 / 大学 / 中庸 共 2208 条**，按类别筛选、搜全文、★收藏，方便申论引用。 |
| **小记** | 仿语雀的随手记：手机端为统一信息流（用标签区分），底部悬浮「搜索 / + / AI」；网页端为侧边栏 + 编辑器。支持图片 / 拍照 / 附件 / 待办清单 / 标签 / OCR识图。 |
| **知识库** | 笔记本系统：每个知识库下可建**分组 / 文档**并任意嵌套；内置**块编辑器**（标题、文本、待办、引用、高亮块、代码块、表格、图片、附件、分割线、状态等），自动保存 + 撤销重做。 |
| **资料库** | 上传图片 / PDF / Word·Excel·PPT / HTML / Markdown 等，应用内直接查看（Office 自动转 PDF，**Markdown 渲染 + 阅读模式**）。支持多选上传、拍照上传、重命名、复制一份、删除。 |
| **全文搜索** | 一次搜遍 **小记 / 资料库（文本类含正文）/ 知识库文档**，结果高亮、分类筛选、点按跳转。 |
| **OCR 识图** | 小记「+ → OCR识图」选图，服务端 tesseract 识别中文+英文，结果填入编辑器可改后发布。 |
| **阅读模式** | 查看 .md / .txt 时渲染为排版文档，支持字号 A-/A+、宋体⇄黑体、护眼背景、复制全文。 |
| **多用户 / 后台** | 各自注册、数据隔离；第一个注册者为管理员。管理后台可重置密码为 `123456`、设/撤管理员、设密保、删用户（至少保留 1 名管理员）。 |
| **找回密码** | 密保问题（注册时设置，答案哈希存储）。 |

> **网页端与手机端 UI 分离**：手机端（安卓 App / 窄屏）小记为语雀式信息流、禁双指缩放、各处针对触屏优化；网页端保留侧边栏式布局。

---

## 一、目录结构

```
gongkao-app/
├─ app.py              # 后端（Flask + waitress：鉴权、分页、PDF 导出、搜索、OCR、各模块 API）
├─ build_db.py         # 成语/词语词典导入（JSON → SQLite）
├─ build_classics.py   # 古诗文导入（data/classics.json → SQLite 的 classics 表）
├─ app.db              # 数据库：参考词典 + 古诗文 + 用户数据（已 .gitignore，注意备份）
├─ config.json         # 会话密钥（已 .gitignore，勿上传）
├─ run.sh              # 一键启动
├─ gongkao.service     # 应用 systemd 用户服务
├─ gongkao-tunnel.service  # Cloudflare 隧道 systemd 用户服务
├─ requirements.txt    # Python 依赖
├─ data/               # idiom.json / ci.json（成语词语）、classics.json（古诗文，已转简体）
├─ static/             # 网页前端 + PWA（SPA、登录页、pdf.js、Service Worker 离线缓存）
├─ android/            # 安卓 WebView 壳工程 + 构建脚本 build_apk.sh
└─ dist/gongkao.apk    # 构建好的安卓安装包
```

**数据来源**
- 成语词语：开源 [chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua)，成语 30,895 条 / 词语 264,346 条，全离线；查不到的词用 pypinyin 注音。
- 古诗文：开源 [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry) 精选集，繁体经 OpenCC 转简体，共 2208 条。

---

## 二、启动

```bash
cd ~/gongkao-app
./run.sh              # 默认 8011 端口；换端口： ./run.sh 9000
```

- **本机**：http://localhost:8011
- **局域网**（同一 WiFi 的手机/平板/另一台电脑）：http://192.168.3.136:8011
  （换网络后用 `hostname -I` 重查 IP；防火墙挡端口时 `sudo ufw allow 8011/tcp`）

**依赖**（首次或换机时）
```bash
uv venv .venv && uv pip install --python .venv/bin/python3 -r requirements.txt
# OCR 需要系统级 tesseract（中文包）：
sudo apt install tesseract-ocr tesseract-ocr-chi-sim
# 仅在重建古诗文数据时需要：sudo apt install opencc
```
PDF 中文渲染依赖系统字体 **AR PL UMing CN**（`fonts-arphic-uming`）。

### 账号：注册 / 登录 / 找回密码（多用户）

- **第一次使用**：进入注册页，设置 用户名、密码、**密保问题 + 答案**。**第一个注册的人自动成为管理员。**
- 之后每人可各自注册，**数据互相隔离**；登录默认记住 30 天。
- **忘记密码**：登录页「忘记密码」→ 输入用户名 → 回答密保 → 设新密码。
- 登录后右上「设置」可改密码、改密保（App 内还可刷新页面 / 切换服务器地址）。
- **管理后台**（仅管理员，右上「后台」）：查看所有用户，**重置密码为 `123456`**、设/撤管理员、设密保、删用户。

> 账号存在 `app.db`（密码与密保答案均哈希）。`config.json` 只存会话密钥。
> 管理员忘密码且无法密保找回时，可临时环境变量登录：
> `GONGKAO_USER=名字 GONGKAO_PASSWORD=临时密码 ./run.sh`（登录后到设置里改回）。

### 数据库与文件
- 用户、收录、古诗文收藏、小记、知识库、资料元数据都在 `app.db`（**备份这个文件**）；上传文件在 `uploads/`（按用户分目录）。
- 二者都已 `.gitignore`，不上传到 GitHub。
- **古诗文数据**：克隆后首次运行需 `.venv/bin/python3 build_classics.py` 导入（数据在 `data/classics.json`，已随仓库提供）。

### 开机自启（可选，systemd 用户服务）

```bash
mkdir -p ~/.config/systemd/user
cp ~/gongkao-app/gongkao.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gongkao.service
loginctl enable-linger $USER
journalctl --user -u gongkao.service -f   # 看日志
```

> 改了后端代码后：`systemctl --user restart gongkao.service`。改前端（static/）刷新即可，无需重启。

---

## 三、各模块怎么用

**成语词语**：顶部输入成语/词语 → 回车显示拼音、释义、出处、例句 → 可当场修改、写笔记 → 「收录」入库；下方按 成语/词语/收藏 筛选、搜索、翻页（每页 5 条）；「导出 PDF」选范围 + 版式（学习版 / 默写版）生成打印。

**古诗文**：申论 → 议论文 → 古诗文·名句速查 → 搜诗文/作者/名句，或按类别浏览，★收藏到「收藏」页。

**小记**：手机端点底部「+」→ 选 空白小记 / 拍摄 / 图片 / OCR识图 / 待办 / 附件 → 写完「完成」发布；卡片可双击编辑；用标签区分、可按标签筛选与搜索。

**知识库**：新建知识库 → 进去点「+」建 文档/分组 → 打开文档进块编辑器（底部工具条插入各种块，右上完成保存）。

**资料库**：上传（可多选）/ 拍照上传 → 列表里每条可 重命名 ✎ / 复制 ⧉ / 下载 ⬇ / 删除 🗑；点开在应用内查看（Markdown 走阅读模式）。

**全文搜索**：首页顶部搜索框 → 输入关键词 → 跨小记/资料/知识库展示结果并跳转。

---

## 四、安卓 APK

安装包已构建：**`dist/gongkao.apk`**（已签名，支持安卓 5.0+，当前 **v1.8**）。

**安装与使用**
1. 手机浏览器打开 **https://gk.gongkaopei2026.click/apk** 直接下载（此地址免登录）。
2. 安装（首次需在系统设置允许「安装未知来源应用」）。
3. 打开后默认连固定公网地址 `https://gk.gongkaopei2026.click`，直接用即可；在家想更快可在「设置 → 切换服务器地址」改成局域网 IP。
4. 导出的 PDF 存到手机「下载」目录。

**特性**：禁双指缩放（像原生 App）；拍照 / 选图 / 选附件（附件支持同时多选）；边缘侧滑 / 返回键退回上一级（不跳登录页），首页再返回退到后台。

> APK 是加载服务的 WebView 壳；纯网页/服务端的改动**刷新即可**，只有涉及原生能力（缩放、相机、文件选择）的改动才需要换新 APK。

**重新构建**
```bash
cd ~/gongkao-app/android
# 改默认地址：编辑 MainActivity.java 的 DEF 常量；改版本号：AndroidManifest.xml
JAVA_HOME=~/.local/jdk17 ANDROID_SDK_ROOT=~/android-sdk ./build_apk.sh
# 产物：dist/gongkao.apk
```
> 依赖便携 JDK17（`~/.local/jdk17`）+ Android SDK（`~/android-sdk`，build-tools;34.0.0、platforms;android-34），用 aapt2/d8/zipalign/apksigner 手动打包，不依赖 Android Studio / Gradle。

---

## 五、公网访问 —— Cloudflare 命名隧道（固定网址）

固定公网网址：**https://gk.gongkaopei2026.click**（**重启不变**）。

- 域名 `gongkaopei2026.click`（NameSilo 注册）→ nameserver 指向 Cloudflare（免费账号）。
- **cloudflared 命名隧道**（免 root，`~/.local/bin/cloudflared`）：隧道名 `gongkao`，配置 `~/.cloudflared/config.yml`（http2），凭证在 `~/.cloudflared/`。
- 两个 systemd 用户服务开机自启：`gongkao.service`（:8011）+ `gongkao-tunnel.service`（`cloudflared tunnel run gongkao`）。

```bash
systemctl --user status gongkao.service gongkao-tunnel.service   # 状态
~/gongkao-app/tunnel_url.sh                                       # 打印固定网址
systemctl --user restart gongkao-tunnel.service                  # 重启隧道(网址不变)
```

> 安全：登录鉴权 + 防爆破（连错 8 次锁 10 分钟）；HTTPS 由 Cloudflare 提供。
> 不想对公网开放：`systemctl --user stop gongkao-tunnel.service`。

---

## 六、技术栈

- **后端**：Python · Flask · waitress · SQLite；pypinyin（注音）、reportlab（PDF）、LibreOffice（Office→PDF）、tesseract（OCR）、OpenCC（繁简转换）。
- **前端**：原生 HTML/CSS/JS 单页应用 + PWA（Service Worker 网络优先缓存）；pdf.js 应用内预览；自带轻量 Markdown 渲染。
- **安卓**：WebView 壳 + 自定义 ContentProvider（相机）+ JS 桥接；手动构建（无 Gradle）。
- **部署**：systemd 用户服务 + Cloudflare 命名隧道。

---

## 七、维护

- **备份**：复制 `app.db` + `uploads/` 即可。
- **更新成语词典**：替换 `data/` 下 JSON 后 `.venv/bin/python3 build_db.py`（不动收录）。
- **更新/导入古诗文**：`.venv/bin/python3 build_classics.py`（重建 classics 表，不动收藏）。
- **重装依赖**：`uv pip install --python .venv/bin/python3 -r requirements.txt`。
