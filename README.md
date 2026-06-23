# 公考 · 选词填空 成语/词语积累

为公务员考试「言语理解与表达 — 选词填空」准备的成语 / 词语积累工具。

**功能**：输入成语或词语 → 自动标注拼音 + 给出释义（成语还带出处、例句）→ 收录、收藏、写笔记 →
一键导出 **PDF**（学习版 / 默写版）方便复习打印。带网页界面，可手机、电脑、远程访问。

> 这是整个「公考助手」的第一个功能模块。后续的错题收集等功能可以在此基础上扩展。

---

## 一、目录结构

```
gongkao-app/
├─ app.py            # 后端服务（Flask + waitress）
├─ build_db.py       # 词典导入脚本（JSON → SQLite）
├─ app.db            # 数据库：参考词典 + 你的收录（你的数据都在这里，注意备份）
├─ run.sh            # 一键启动脚本
├─ gongkao.service   # systemd 开机自启服务（可选）
├─ requirements.txt  # 依赖
├─ data/             # 原始词典 idiom.json / ci.json
└─ static/           # 网页前端 + PWA（图标、manifest、离线缓存）
```

数据来源：开源 [chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua) 词典，
成语 30,895 条、词语 264,346 条，全部离线，查不到的词自动用 pypinyin 注音。

---

## 二、启动

```bash
cd ~/gongkao-app
./run.sh              # 默认 8011 端口；想换端口： ./run.sh 9000
```

看到 `公考积累服务已启动` 后：

- **本机访问**：浏览器打开 http://localhost:8011
- **局域网（同一 WiFi 的手机/平板/另一台电脑）访问**：
  http://192.168.3.136:8011 （这是本机当前内网 IP，换网络后用 `hostname -I` 重新查）

> 若局域网设备打不开，多半是防火墙挡了端口：
> `sudo ufw allow 8011/tcp`

### 开机自启（可选，systemd 用户服务）

```bash
mkdir -p ~/.config/systemd/user
cp ~/gongkao-app/gongkao.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gongkao.service
loginctl enable-linger $USER          # 没登录也保持运行
# 查看状态 / 日志：
systemctl --user status gongkao.service
journalctl --user -u gongkao.service -f
```

---

## 三、怎么用

1. 顶部输入框输入成语或词语，回车（或点「查询」）→ 下方显示拼音、释义、出处、例句。
2. 释义/出处/例句/类别都可**当场修改**，还能写「笔记」（辨析、易混词、真题出处）。
3. 点「收录」存入；下方列表可按 **成语 / 词语 / 收藏** 筛选、搜索。
4. 每条可 ☆收藏、✎改笔记、🗑删除。
5. 点「导出 PDF」：
   - **范围**：当前筛选全部 / 仅成语 / 仅词语 / 仅收藏
   - **版式**：学习版（含释义）或 **默写版**（释义留空，用来自测）
   - 可勾选是否带出处 / 例句 / 笔记
   - 生成后自动下载，可直接打印。

---

## 四、安卓 / 手机使用

本程序做成了 **PWA（渐进式网页应用）**，手机不用装任何东西就能像 App 一样用：

**安卓（Chrome / Edge 等）**
1. 手机连同一 WiFi，浏览器打开 `http://192.168.3.136:8011`
2. 右上角菜单 →「**添加到主屏幕 / 安装应用**」
3. 桌面就会出现「公考积累」图标，点开全屏运行，和 App 一样。

**iPhone（Safari）**：分享按钮 →「添加到主屏幕」。

> 想要真正的 `.apk` 安装包（脱离电脑也能用），见下方「进阶」。

---

## 五、维护

- **备份数据**：你的收录全部在 `app.db`，复制走即可。
- **重建/更新词典**：替换 `data/` 下的 JSON 后运行
  `.venv/bin/python3 build_db.py`（只重建参考词典，不动你的收录）。
- **重装依赖**：`uv venv .venv && uv pip install --python .venv/bin/python3 -r requirements.txt`

---

## 六、进阶：远程（公网）访问 & 打包成 APK

**公网访问**（出门在外也能连家里这台机器），任选其一：
- 内网穿透：`cloudflared` / `frp` / `tailscale`（推荐 tailscale，零配置、加密）
- 有公网 IP / 域名则配 Nginx 反代 + HTTPS

> 注意：当前程序**没有登录密码**，公网暴露前请先加一层访问控制（Nginx Basic Auth
> 或 tailscale 私有网络），否则任何人都能访问你的数据。

**打包成真正的安卓 APK**（可选）。当前这台机器没有安卓 SDK，建议用以下任一方式：
- **PWABuilder**（https://www.pwabuilder.com ）：填入你的公网地址，在线生成 APK，最省事；
- **Bubblewrap / Capacitor**：在装了 Android Studio 的机器上把本 Web 应用包成 APK。

PWA「添加到主屏幕」对绝大多数复习场景已经足够，建议先用 PWA，确有需要再打包 APK。
