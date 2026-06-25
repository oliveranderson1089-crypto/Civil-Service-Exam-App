# 公考 · 选词填空 成语/词语积累

为公务员考试「言语理解与表达 — 选词填空」准备的成语 / 词语积累工具。

**功能**：输入成语或词语 → 自动标注拼音 + 给出释义（成语还带出处、例句）→ 收录、收藏、写笔记 →
一键导出 **PDF**（学习版 / 默写版）方便复习打印。带**登录**、网页界面、列表**分页**，
可手机、电脑、远程访问，并提供**安卓 APK**。

> 这是整个「公考助手」的第一个功能模块。后续的错题收集等功能可以在此基础上扩展。

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

### 账号：注册 / 登录 / 找回密码

- **首次打开**会进入「创建你的账号」页：设置你自己的 用户名、密码、**找回邮箱**和**邮箱授权码**。
- 之后是登录页，登录状态默认记住 30 天。
- **忘记密码**：登录页点「忘记密码」→ 输入用户名 → 点「发送验证码」→ 邮箱收到 6 位验证码 →
  填验证码 + 新密码即可重置。
- 登录后右上角「设置」可随时改密码、改邮箱 / SMTP、发测试邮件。

> **邮箱授权码** 不是邮箱登录密码：QQ/163 等需先在邮箱网页版开启「SMTP 服务」并生成授权码，
> 填到这里（程序据此给你自己发验证码）。SMTP 服务器一般按邮箱域名自动识别。
>
> 账号、密钥都存在 `config.json`（密码为哈希；授权码因需发信为明文，故该文件已被 git 忽略，
> 不会上传）。忘了密码又没配邮箱时，可在电脑上 `rm config.json && ./run.sh` 重新注册。
> 也可用环境变量直接设定账号：`GONGKAO_USER=名字 GONGKAO_PASSWORD=密码 ./run.sh`。

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
