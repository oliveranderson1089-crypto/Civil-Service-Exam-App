# 公考助手 Civil-Service-Exam-App

公务员考试备考工具。网页 + 安卓 APK，支持多用户、远程访问。

**结构**：登录后首页分 **行测**（常识判断/资料分析/判断推理/数量关系/政治理论/言语理解与表达）
和 **申论**（应用文/议论文）两大板块。

**功能**
- **每个板块**都有「资料库」：上传图片 / PDF / Word·Excel·PPT / 网页(HTML) 等，点击在应用内直接查看
  （Office 文档自动转 PDF 预览）。
- **言语理解与表达** 额外带「成语 / 词语积累」：输入即自动注音 + 释义（成语带出处例句），收录、收藏、
  笔记，一键导出 PDF（学习版 / 默写版）。
- **多用户**：各自注册、数据互相隔离；第一个注册者为管理员。
- **管理后台**：管理员可重置任意用户密码为初始密码 `123456`、设/撤管理员、删除用户。
- **找回密码**：密保问题。
- 安卓 APK、Cloudflare 隧道远程访问见后文。

---

## 一、目录结构

```
gongkao-app/
├─ app.py            # 后端服务（Flask + waitress，含登录鉴权、分页、PDF 导出）
├─ build_db.py       # 词典导入脚本（JSON → SQLite）
├─ app.db            # 数据库：参考词典 + 你的收录（个人数据，已 .gitignore，注意备份）
├─ config.json       # 登录账号与密钥（已 .gitignore，勿上传）
├─ run.sh            # 一键启动脚本
├─ gongkao.service   # systemd 开机自启服务（可选）
├─ requirements.txt  # 依赖
├─ data/             # 原始词典 idiom.json / ci.json
├─ static/           # 网页前端 + PWA（登录页、图标、manifest、离线缓存）
├─ android/          # 安卓 WebView 壳工程 + 构建脚本 build_apk.sh
└─ dist/gongkao.apk  # 构建好的安卓安装包
```

数据来源：开源 [chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua) 词典，
成语 30,895 条、词语 264,346 条，全部离线，查不到的词自动用 pypinyin 注音。

---

## 二、启动

```bash
cd ~/gongkao-app
./run.sh              # 默认 8011 端口；换端口： ./run.sh 9000
```

- **本机**：http://localhost:8011
- **局域网（同一 WiFi 的手机/平板/另一台电脑）**：http://192.168.3.136:8011
  （换网络后用 `hostname -I` 重新查 IP；防火墙挡端口时 `sudo ufw allow 8011/tcp`）

### 账号：注册 / 登录 / 找回密码（多用户）

- **第一次使用**：进入注册页，设置 用户名、密码、**密保问题 + 答案**。**第一个注册的人自动成为管理员。**
- 之后每个人可各自注册账号，**数据互相隔离**；登录状态默认记住 30 天。
- **忘记密码**：登录页「忘记密码」→ 输入用户名 → 回答密保问题 → 设置新密码。
- 登录后右上角「设置」可改密码、改密保问题。
- **管理后台**（仅管理员，右上「后台」）：查看所有用户，**重置任意用户密码为 `123456`**、设/撤管理员、删除用户。

> 账号存在数据库 `app.db`（密码与密保答案均为哈希）。`config.json` 只存会话密钥。
> 管理员忘了密码且无法通过密保找回时，可在电脑上用环境变量临时登录：
> `GONGKAO_USER=名字 GONGKAO_PASSWORD=临时密码 ./run.sh`（登录后再到设置里改回）。

### 数据库与文件
- 用户、收录、资料元数据都在 `app.db`（**备份这个文件**）；上传的文件在 `uploads/`（按用户分目录）。
- 二者都已 `.gitignore`，不会上传到 GitHub。

### 开机自启（可选，systemd 用户服务）

```bash
mkdir -p ~/.config/systemd/user
cp ~/gongkao-app/gongkao.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gongkao.service
loginctl enable-linger $USER
journalctl --user -u gongkao.service -f   # 看日志
```

---

## 三、怎么用

1. 登录后，顶部输入框输入成语或词语，回车 → 显示拼音、释义、出处、例句。
2. 释义/出处/例句/类别都可**当场修改**，可写「笔记」（辨析、易混词、真题出处）。
3. 点「收录」存入；下方列表按 **成语/词语/收藏** 筛选、搜索，**每页 5 条**翻页。
4. 每条可 ☆收藏、✎改笔记、🗑删除。
5. 「导出 PDF」：范围（当前筛选/成语/词语/收藏）+ 版式（学习版含释义 / 默写版留空自测）
   + 勾选出处/例句/笔记，生成后下载打印。

---

## 四、安卓 APK

安装包已构建好：**`dist/gongkao.apk`**（约 17 KB，已签名，支持安卓 5.0 以上）。

**安装与使用**
1. 手机连**同一 WiFi**，浏览器打开 **http://192.168.3.136:8011/apk** 直接下载安装包
   （这个下载地址免登录；也可用微信文件传输助手 / 数据线把 `dist/gongkao.apk` 传过去）。
2. 点击安装（首次需在系统设置里允许「安装未知来源应用」）。
3. 打开「公考积累」，首次会让你填**服务器地址**，默认 `http://192.168.3.136:8011`，
   手机与电脑在同一 WiFi 时直接确定即可。
4. 之后就像 App 一样使用；导出的 PDF 会存到手机「下载」目录。
5. 换了网络 / 电脑 IP 变了：右上角菜单 →「设置服务器地址」改即可。

> APK 本质是个加载你电脑服务的浏览器壳，所以**电脑上的服务要开着**、手机能连到它。
> 想在外面也能用，见第六节「公网访问」。

**重新构建 APK**（改了默认地址或界面后）

```bash
cd ~/gongkao-app/android
# 如需改默认地址：编辑 MainActivity.java 里的 DEF 常量
JAVA_HOME=~/.local/jdk17 ANDROID_SDK_ROOT=~/android-sdk ./build_apk.sh
# 产物：dist/gongkao.apk
```

> 构建依赖本机已装好的便携 JDK17（`~/.local/jdk17`）和 Android SDK（`~/android-sdk`，
> 含 build-tools;34.0.0、platforms;android-34）。脚本用 aapt2/d8/zipalign/apksigner
> 手动打包，不依赖 Android Studio / Gradle。

如果想要应用商店级别的体验（独立图标多分辨率、TWA 等），可用 https://www.pwabuilder.com
或 Capacitor 进一步打包，但当前这个 APK 已能正常安装使用。

---

## 五、用 git 推送到 GitHub

本目录已是一个 git 仓库（首次提交已完成）。推送步骤：

```bash
cd ~/gongkao-app
# 1. 在 GitHub 网页上新建一个空仓库（不要勾 README），拿到地址，例如：
#    https://github.com/你的用户名/gongkao-app.git
# 2. 关联并推送
git remote add origin https://github.com/你的用户名/gongkao-app.git
git push -u origin main
```

推送时 GitHub 要求登录：用户名 + **Personal Access Token**（不是账号密码）。
到 GitHub → Settings → Developer settings → Personal access tokens 生成一个有 `repo`
权限的 token，当密码用。

> `app.db`、`config.json`、`.venv/`、构建中间产物已在 `.gitignore` 中，不会上传，
> 不会泄露你的收录数据和登录密码。`data/` 词典和 `dist/gongkao.apk` 会一并上传，
> 方便别人克隆后直接用；嫌仓库大可把它们也加进 `.gitignore`。

---

## 六、维护 & 进阶

### 公网访问（出门用流量也能用）—— Cloudflare 隧道

已用 **cloudflared**（免 root，单文件在 `~/.local/bin/cloudflared`）把本地服务暴露成公网 https 网址，
无需公网 IP / 不用改路由器。两个 systemd 用户服务已装好并开机自启：

```bash
# 查看状态 / 日志
systemctl --user status gongkao.service gongkao-tunnel.service
# 取当前公网网址（填进手机 APP「设置服务器地址」）
~/gongkao-app/tunnel_url.sh
# 重启隧道（会换一个新网址）
systemctl --user restart gongkao-tunnel.service
```

**用法**：手机用流量打开 APP → 菜单「设置服务器地址」→ 填 `tunnel_url.sh` 显示的网址。

> ⚠️ **免费快速隧道的网址在隧道重启 / 电脑重启后会变**。日常不关机时网址稳定；变了就重新跑
> `tunnel_url.sh` 取新址、在 APP 里更新一次即可。
>
> **想要永久固定网址**：注册免费 Cloudflare 账号 + 绑一个你自己的域名，做「命名隧道」即可固定。
> 有域名了告诉我，我帮你配。
>
> **安全**：程序有登录鉴权，且登录已加防爆破（连续失败 8 次锁 10 分钟）；网址是随机长串不易被猜到。
> 但公网暴露期间请用**强密码**。不想对公网开放时：`systemctl --user stop gongkao-tunnel.service`。

### 其它维护

- **备份数据**：你的收录都在 `app.db`，复制走即可。
- **更新词典**：替换 `data/` 下 JSON 后运行 `.venv/bin/python3 build_db.py`（不动你的收录）。
- **重装依赖**：`uv venv .venv && uv pip install --python .venv/bin/python3 -r requirements.txt`
