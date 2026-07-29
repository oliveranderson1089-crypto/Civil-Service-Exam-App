# 公考助手后台管理方案

> 目标：把「这套系统今天还好不好」变成后台一屏能看清、手机上能处置的事。
> 原则：**只读优先、零侵入先行、危险动作留在命令行。**
>
> **状态：P0–P3 已全部上线（2026-07-29）。** 后台从 4 个板块扩到 8 个分栏：
> 产出健康 / AI 用量 / 内容质检 / 备份容量 / 服务 / AI 设置 / 注册入口 / 用户。
> 各阶段的落地情况和与本文设计的出入，记在对应小节里；使用说明在
> `docs/README-full.md`。下面的现状盘点与诊断保留原样，作为「为什么这么做」的存档。

---

## 一、现状盘点

后台入口 `/admin`（`static/admin.html` 443 行 + `mods/admin.py` 83 行 + `mods/ops.py` 250 行），
现有四块：

| 板块 | 能力 | 评价 |
|---|---|---|
| AI 设置 | 接口地址 / 双档模型 / Key / 测连通 / 查模型 | 够用 |
| 注册入口 | 开关 + 邀请码 | 够用 |
| 服务管理 | 17 个 systemd 单元状态、勾选重启、看 journal、操作留痕 | 骨架好，但**只看得见"进程"，看不见"产出"** |
| 用户管理 | 列表 / 重置密码 / 改角色 / 密保 / 删除 | 够用 |

**鉴权现状是干净的**：`app.py` 的 `guard()` 统一拦 `/admin` 与 `/api/admin/*`，
未登录跳登录、非 admin 403。`mods/ops.py` 的单元名白名单（`UNIT_RE` + 只在 discover 集合内筛选，
绝不拼命令行）也写得扎实。这两条是本方案的地基，**不动**。

---

## 二、诊断：五个盲区

按危害排序。这些不是"缺功能"，是**出了事没人知道**。

### 盲区 1：退出码 0 ≠ 有产出（最严重）

13 个定时脚本靠 systemd 判定健康，但 systemd 只认退出码。
上游断供 / 抓取到空 / AI 返回空，脚本照样 exit 0，后台一片绿，
**界面上还会反过来显示「都写齐了」**（素材链路已经真实发生过：
OpenClaw cron 产出写 `~/.openclaw/kaogong-cache`，断供无声）。

现状抽查（2026-07-29 13:40）——今天其实是健康的，但**这个结论只能靠敲 SQL 得到**：

```
sucai_items    2026-07-29        news_items     2026-07-29 12:41
changshi_items 2026-07-29        video_items    2026-07-29 07:22
daily_essays   2026-07-29        exam_notices   2026-07-29 07:40
drill_bank     2026-07-28 16:58   ← 昨天的，是否正常？没人定义过
```

### 盲区 2：AI 零可观测

十几个 `gen_*.py` 全靠 `aiclient.py`，它是**唯一出口**（模型名只准住这一个文件）。
但调用量、token 消耗、失败率、谁在烧钱、哪个调用方在超时——**一条都没记**。
`usage` 字段拿到了却只用于 `budget()` 重试判断，用完即弃。

### 盲区 3：内容质量无入口

真题 7606 题 / 解析 6897 条 / 题库 3565 题 / 原始 11156 条。
命门是**答案对齐**，已经有 `audit_find.py`、`audit_qtype.py`、`mods/align.py` 这些审计能力，
但全在命令行。后台看不到对齐率、缺解析数、缺图数。

### 盲区 4：备份与容量不可见

`backup.sh` 每天 03:30 跑得很好（VACUUM INTO + integrity_check + 14 天滚动），
但后台看不见"最近一次备份是什么时候、校验过没有"。
容量已在悄悄膨胀：

```
app.db 141M   uploads 868M   data 89M   backups 2.7G
项目根还散着 9 个 app.db.bak.*（≈1.3G），无人管理、无保留策略
```

### 盲区 5：全局任务视图缺失

`bg_tasks` 表存在，但只按 `user_id` 索引、只给用户自己看。
管理员看不到"当前有哪些长任务在跑、卡住了没有"。

---

## 三、方案：四层，按优先级交付

### P0 · 产出健康看板 ✅ 已上线（2026-07-29）

落地情况见 `mods/health.py` / `static/js/admin-health.js` / `tests/test_health.py`，
以及 `docs/README-full.md` 的「后台 → 产出健康」。与下面设计的两处出入：

1. **操作按钮对准 `.service` 而不是 `.timer`**——`restart` 一个 timer 只重置计时器，
   任务一次都不会跑。域声明里仍用 timer（判上次触发要它），但「立即补跑」和「看日志」都走 service。
2. **归因看 service 的 `healthy`、优先用它的实际执行时间**：failed 和执行时间都挂在 service 上，
   timer 只负责按点戳它。
3. 顺带把 `/admin` 拆成了五个分栏（产出健康 / 服务 / AI 设置 / 注册入口 / 用户），
   默认落在产出健康，选中的分栏记在 URL hash 里。

上线当天的实测：11 个域全绿；反向验收（删掉新闻近 4 天数据）→ 变红且归因 `silent`，符合预期。



**思路：先做零侵入探针，不改任何脚本。**

每个内容域声明一条**新鲜度契约**（域名、表、时间列、SLA 天数、负责单元），
后台一条 `MAX(时间列)` + 今日新增数就能算出红黄绿。

新增 `mods/health.py`（约 150 行）：

```python
# 契约表：声明式，加一个内容域 = 加一行，不写逻辑
DOMAINS = [
    # key,      表,              时间列,       SLA天, 负责单元
    ("sucai",   "sucai_items",   "date",       1, "gongkao-write.timer"),
    ("news",    "news_items",    "created_at", 1, "gongkao-news.timer"),
    ("changshi","changshi_items","date",       1, "gongkao-changshi.timer"),
    ("essay",   "daily_essays",  "date",       1, "gongkao-essay.timer"),
    ("video",   "video_items",   "created_at", 2, "gongkao-video.timer"),
    ("exam",    "exam_notices",  "created_at", 1, "gongkao-exam.timer"),
    ("drill",   "drill_bank",    "created_at", 2, "gongkao-warmbank.timer"),
    ("quiz",    "quiz_questions","created_at", 7, "gongkao-quiz.timer"),
]
```

接口 `GET /api/admin/health` 返回每域：`最新产出时间 / 逾期天数 / 今日新增 / 存量 / 状态(ok|warn|down) / 负责单元`。

前端一屏卡片：**绿=今天有货，黄=接近 SLA，红=已断供**，红卡直接带「重启该单元」按钮
（复用现成的 `/api/admin/services/restart`）和「看 journal」链接。

> 为什么先做探针而不是改脚本埋点：13 个脚本分散、没人 import、重构易静默断链。
> 探针只读数据库，当天可用、零风险，且**先量再改**——先看清哪些域真的会断，再决定给谁加埋点。

**P0.5（探针跑稳后再做）**：新增 `ops_runs` 表 + `mods/opsrun.py` 提供 `record_run(kind)` 上下文管理器，
脚本收尾写一行「产出 N 条 / 期望 M 条 / 耗时 / 异常」。这样能区分「没跑」和「跑了但没产出」——
探针只能告诉你结果不新鲜，说不出是哪一步断的。

### P1 · AI 用量与故障 ✅ 已上线（2026-07-29）

落地在 `aimeter.py`（记账，零依赖）/ `mods/aistats.py`（报表）/ `static/js/admin-stats.js`
/ `tests/test_aimeter.py`，说明见 `docs/README-full.md` 的「后台 → AI 用量」。
与下面设计的出入：

1. **没有把记账塞进 `aiclient.py`**，另起零依赖的 `aimeter.py`。aiclient 的职责是
   「模型真源」，记账是另一件事；混进去会稀释它的主线（它已经 470 行）。
2. **caller 要跳过 `mods/ai.py` 这层转发**，否则 Web 侧 18 个业务模块全记成 `ai`。
   这是设计时没预料到、读代码才发现的——`_ai_call_or_error` 有 29 处调用方。
3. **记每次尝试而不是每次调用**：重试也烧 token，按调用记会把成本记少。
4. **正文空串（starved）额外记一行纯故障**，token 记 0 不重复计费——
   跟 P0 的 `silent` 是同一个病：HTTP 成功但实际没产出。

上线实测：真实调一次 `/api/ai/chat`，记到
`caller=aichat / fast / deepseek-v4-flash / 进122 出40 推理38 / 1622ms / ok`，
报表四个维度（总计、按调用方、按档位、按天）都读得出来。



在 `aiclient.py` 的 `chat()` / `stream()` 出口各加一处记账（它已经是唯一出口，改一个文件即可）：

新表 `ai_calls`：`ts, caller, tier, model, prompt_tokens, completion_tokens, reasoning_tokens,
elapsed_ms, ok, err_kind`。`caller` 从调用栈自动取（`gen_essays` / `aichat` / `drill` …），
业务侧不用改一行。

接口 `GET /api/admin/ai/stats`，后台展示：

- 今日 / 7 日：调用次数、token 总量、按档位（fast / pro）拆分
- **按调用方排名**——谁在烧钱，一眼看到
- 失败率 + 最近 20 条错误（错误类型分桶：超时 / 截断 / 鉴权 / 上游 5xx）
- `reasoning_tokens` 单列：v4 是推理模型，这块常被低估

保留策略：只留 90 天，定时清理，避免这张表反过来把库撑大。

### P2 · 内容质检 ✅ 已上线（2026-07-29）

落地在 `mods/quality.py` / `static/js/admin-quality.js` / `tests/test_quality.py`，
说明见 `docs/README-full.md` 的「后台 → 内容质检」。与下面设计的出入：

1. **可用率这一项从 `realref.servable()` 借口径**，不自己写第四份——
   这是本项目明写过的教训（三处各写各的，漏一处就「审计数字和线上对不上」）。
2. **「图形题缺图」这一项判据推倒重来**：原设计用 `fighash` 为空判断，
   但那列是图**哈希去重**用的，不是「有没有图」的标志（照它算出来 63.7% 缺图，
   纯属误报）。真正的标志是 `needs_asset=1`（缺图或缺材料、发不出去），改成量它。
3. 破坏性动作按方案要求全部挡在门外，测试里有一条扫源码禁止写操作。

上线实测（生产库 7606 道真题）：7 项正常、2 项留意——
真题缺答案 7.2%、小题库存疑 19.3%（单模型出题一致率约 89%，这个量级正常）；
真题不可用率 4.9%，小题库续航 287 天。



新增 `mods/quality.py`，把已有审计脚本的**只读部分**搬成接口：

| 指标 | 来源 | 意义 |
|---|---|---|
| 真题答案对齐率 | `real_questions` 有效答案占比 | 命门指标 |
| 缺解析题数 | `real_questions` 左连 `real_explains` | 补跑 `gen_real_explain.py` 的依据 |
| 缺图题数 | 题干含图标记但 `real_figs` 无记录 | OCR/切图漏了 |
| 选词填空横线异常 | 题干无 `＿` 的填空题 | 已踩过的坑，做成常驻监控 |
| 题库存量/消耗 | `drill_bank` 存量 vs `drill_log` 近 7 日消耗 | 预警"题不够用" |
| 孤儿数据 | 引用了不存在 paper/user 的行 | 数据完整性 |

**硬约束：后台只读、只报告。** `--reset`、`--reparse`、重跑 OCR 这类破坏性动作**不进后台**，
报告里给出该敲的命令行即可。理由：这些操作动辄改数千行，需要在终端里看着全量新旧对比来做。

### P3 · 备份、容量、任务 ✅ 已上线（2026-07-29）

落地在 `mods/capacity.py` / `static/js/admin-capacity.js` / `tests/test_capacity.py`，
说明见 `docs/README-full.md` 的「后台 → 备份容量」。三块按设计做齐了，另外：

1. **不重复跑 `integrity_check`**——backup.sh 每次备份时已经跑过，快照存在即校验通过。
2. **备份目录口径和 backup.sh 同源**，测试直接读 `backup.sh` 比对，
   防「后台对着空目录说从没备份过」。
3. **手工快照只列不删**（同 P2 的规矩），测试禁止本模块出现任何删除调用。

上线实测：备份 ok（最近 07-29 03:30、16 份、139M）、磁盘 ok（26%、剩 322G）、
无卡死任务；占用构成 = 库 141M + uploads 864M + 词库 89M + 每日备份 1.7G +
备份镜像 864M + 手工快照 1.4G。



**备份卡片**：读 `~/AppStore/backups/gongkao/db/` 最新快照的时间 / 大小 / 份数 / 总占用，
提供「立即备份」按钮（后台调 `systemctl --user start gongkao-backup.service`，走现成通道）。

**容量卡片**：`app.db` / `uploads` / `data` / `backups` 四个数字 + 趋势。
附一条治理建议：项目根 9 个 `app.db.bak.*`（≈1.3G）是历次改造的手工快照，
**方案建议**：保留最近 2 个 + 全部移出项目根到 `backups/manual/`，其余删除。列出来让人点，不自动删。

**全局任务视图**：`GET /api/admin/tasks` 列出 `bg_tasks` 全表近 7 日，
标出 `status='running'` 且 `updated_at` 超过 30 分钟未动的——那是卡死的。

---

## 四、工程约束（新代码必须遵守）

1. **所有后台接口一律挂 `/api/admin/` 前缀**。这是 `guard()` 唯一识别的保护边界，
   走别的前缀 = 自动失去鉴权。新增模块必须在 `app.py` 注册蓝图，`tests/test_wiring.py` 会盯。
2. **`admin.html` 必须拆**。443 行再塞四个板块会失控 →
   改成左侧导航 + 视图切换，JS 拆到 `static/js/admin/{health,ai,quality,ops}.js`，
   走现有 bundle 机制。
3. **不用原生弹窗**，一律 `appConfirm` / `appPrompt`。
4. **移动端优先**：真实使用场景是「AI 挂了、人在手机上」——
   所有卡片单列可读，主操作（重启 / 立即备份 / 看日志）拇指可达。
5. **不依赖 AI**：后台自身的所有判断都是 SQL 和 systemctl，
   AI 本身就可能是坏掉的那一环。
6. **新增表进 `schema.py`**，跟随现有 `init_db()`；`tests/test_schema_drift.py` 会校验。

---

## 五、落地清单

| 阶段 | 新增/改动 | 产物 |
|---|---|---|
| P0 | `mods/health.py`、`static/js/admin/health.js`、admin.html 导航拆分 | 产出健康看板 |
| P0.5 | `schema.py` +`ops_runs`、`mods/opsrun.py`、13 个脚本收尾各加 2 行 | 跑批留痕 |
| P1 | `schema.py` +`ai_calls`、`aiclient.py` 两处记账、`mods/aistats.py` | AI 成本与故障面板 |
| P2 | `mods/quality.py`、`static/js/admin/quality.js` | 内容体检报告 |
| P3 | `mods/ops.py` 扩备份/容量、`mods/admin.py` 扩全局任务 | 运维卡片 |

每阶段配 `tests/test_<模块>.py`，至少覆盖：接口鉴权（非 admin 403）、空库不崩、SLA 判定边界。

---

## 六、验收标准

方案做完后，下面这些问题**都能在手机上 10 秒内答上来**：

- 今天素材/新闻/常识/成文出了没有？没出的话是哪个单元、怎么重启？
- 这周 AI 花了多少 token、失败几次、是谁在烧？
- 真题答案对齐率掉了没有？还有多少题缺解析？
- 最近一次备份是什么时候、校验过没有？磁盘还剩多少？
- 有没有卡死的后台任务？

以及一条反向验收：**故意停掉 `gongkao-news.timer` 一天，后台必须变红。**
这是整套方案唯一真正要证明的事——静默失败不再静默。
