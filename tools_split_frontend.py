#!/usr/bin/env python3
"""把 static/app.js 按它自己的区段边界切成多个文件。

铁律：**顺序不能变**。app.js 有 377 条顶层执行语句（415 个事件绑定），
它们依赖 DOM 已就绪、也依赖彼此的先后。切分后按原顺序用多个 <script> 引入，
执行序与原来逐字节一致 —— 这是「行为不变」的全部依据。

每个文件顶部生成 /* global ... */：列出它用到、但定义在别处的符号。
eslint 靠它继续抓 no-undef（否则拆完 no-undef 就废了，等于拿防线换文件变小），
同时这行注释本身就是这个模块的依赖清单 —— 将来若转 ES modules，它就是 import 表。
"""
import re, os, sys, json

SRC = 'static/app.js'
OUT = 'static/js'

# (文件名, 起始行(1-based), 说明) —— 边界取自 app.js 自己的 /* ==== 区段 ==== */ 标记
PLAN = [
    ('core',      1,     '地基：DOM 选择器 / api / toast / 转义 / 本地存储 / 图标 / 环境判断 / 板块配置'),
    ('shell',     157,   '外壳：导航栈 / 初始化 / 首页卡片 / 应用内弹窗 / 卡片拖拽排序'),
    ('notes',     539,   '小记（仿语雀）：随手记 / 图片附件 / 标签 / 动态流'),
    ('materials', 1278,  '资料库 + 幻灯片播放（逐页出图）'),
    ('entries',   1717,  '成语 / 词语积累'),
    ('kb',        1905,  '知识库：笔记本 + 文档块编辑器'),
    ('study',     2439,  '古诗文速查 / AI 助手 / 全文搜索 / 错题本 / 板块基础知识点 / 顶栏'),
    ('news',      3312,  '每日新闻视频 + APP 内播放器 + 每日时政 + 概括句 + 应用文上位词'),
    ('write',     4030,  '手写输入板 / 小题训练 / 专项练 / 成文 / 素材 / 任务 / 40 天路线 / 巩固测试'),
    ('figures',   5673,  '资料分析的材料：表格 / 柱状图 / 折线图 / 饼图（内联 SVG）'),
    ('exam',      6040,  '申论 / 常考 / 理论基础 / 今日复习 / 题库 / 经典著作 / 常识 / 要文库 / 人民时评'),
    ('social',    7320,  '云盘 / 聊天 / 党建词典 / 逐条朗读 / 账户'),
    ('sync',      8054,  '多端自动同步 / 主题 / 应用内更新 / 消息中心 / 范文推荐 / 题库解析 / 通知'),
    ('ink',       8872,  '草稿纸 / 文本锚 / 通用手写批注层 / 通用停靠'),
    ('tools',     10116, '草稿本 / 外观 / 侧边翻页 / 给定资料面板 / AI 截图 / 书签 / 桌面拖放 / 划重点'),
]

lines = open(SRC, encoding='utf-8').read().split('\n')

# 全部顶层符号 → 定义行
defs = {}
for i, l in enumerate(lines):
    m = re.match(r'(?:async )?function ([\w$]+)\s*\(', l)
    if m:
        defs.setdefault(m.group(1), i); continue
    # 一行可以声明多个：let ME = null, SECTIONS = [], ALL_BOARDS = [];
    # 只认第一个的话，后面那些就成了「谁都没定义过」的幽灵（41 行是这种写法）
    m = re.match(r'(?:const|let|var)\s+(.+)$', l)
    if m:
        for n in re.findall(r'(?:^|,)\s*([A-Za-z_$][\w$]*)\s*=', m.group(1)):
            defs.setdefault(n, i)
names = set(defs)

# 切片
parts = []
for k, (name, start, desc) in enumerate(PLAN):
    end = PLAN[k+1][1] - 1 if k+1 < len(PLAN) else len(lines)
    parts.append((name, start-1, end, desc))     # 0-based [start, end)

# 每片拥有的符号
owned = {}
for name, s, e, _ in parts:
    owned[name] = {n for n, ln in defs.items() if s <= ln < e}

# eslint 的浏览器/契约全局，不必写进 /* global */
KNOWN = set(json.load(open(os.path.join(os.path.dirname(__file__), 'known_globals.json'), encoding='utf-8'))) \
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'known_globals.json')) else set()

os.makedirs(OUT, exist_ok=True)
report = []
for name, s, e, desc in parts:
    body = '\n'.join(lines[s:e]).strip('\n')
    used = set(re.findall(r'(?<![\w$])([a-zA-Z_$][\w$]*)', body))
    need = sorted(n for n in used if n in names and n not in owned[name] and n not in KNOWN)
    head = f'/* {desc}\n *\n'
    head += f' * 由 app.js 按它原有的区段边界切出（原 L{s+1}-{e}）。顺序即原顺序 —— index.html 里\n'
    head += f' * 按同样次序引入，执行序与拆分前逐字节一致。\n'
    if need:
        head += ' *\n * 下面 /* global *​/ 是这个模块的依赖清单：它用到、但定义在别处的符号。\n'
        head += ' * eslint 靠它继续抓 no-undef；将来若转 ES modules，这就是现成的 import 表。\n'
    head += ' */\n'
    if need:
        # 每行 4 个，别拉成一条长龙
        rows = [', '.join(need[i:i+6]) for i in range(0, len(need), 6)]
        head += '/* global ' + ',\n   '.join(rows) + ' */\n'
    open(f'{OUT}/{name}.js', 'w', encoding='utf-8').write(head + '\n' + body + '\n')
    report.append((name, e-s, len(owned[name]), len(need)))

print(f'{"文件":12s} {"行数":>6} {"自有符号":>7} {"外部依赖":>7}')
for n, ln, own, need in report:
    print(f'{n+".js":12s} {ln:6d} {own:7d} {need:7d}')
print(f'\n合计 {sum(r[1] for r in report)} 行（原 {len(lines)}）')
