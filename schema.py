"""建表 + 迁移：全部 77 张表的 schema 都在这儿。

原先埋在 app.py 中间（还被「AI 工具调用」的区段标题盖住了 —— 那个标题下面
其实跟着 792 行 init_db）。schema 是独立关注点：改表结构不该翻业务代码，
读业务代码也不该被 792 行建表刷屏。

同一张表在 crawl_news.py / import_teacher.py 等脚本里也有定义，靠
tests/test_schema_drift.py 盯着别漂——changkao_items.freq 和 news_items.board
就是这么漏掉、让新库上 5 个接口直接 500 的。
"""
import json
import os
import sqlite3

from core import CONFIG, DB, log


# 应用文上位词起步词库：把口语/具体写法归纳为公文规范上位提法
# (场景, 规范上位表述, 适用文种, 用法说明, 例句)
_GONGWEN_SEED = [
    ("开头·缘由（依据）", "为深入贯彻…、为进一步…、为切实…、根据…精神、按照…部署、结合…实际",
     "通知/通报/报告/意见", "开头交代行文缘由，先亮依据再讲目的，不要直接铺陈内容。",
     "为深入贯彻绿色发展理念、进一步改善城乡人居环境，结合我市实际，现就开展垃圾分类工作通知如下。"),
    ("开头·目的", "旨在…、以…为目标、着力…、致力于…、力争…",
     "通知/意见/倡议书", "承接缘由，点明要达到的效果，动词开头更有力。",
     "旨在形成全社会共同参与的良好氛围，着力提升基层治理效能。"),
    ("过渡·引出事项", "现将有关事项通知如下、现提出如下意见、具体安排如下、现将有关情况报告如下",
     "通知/意见/报告", "缘由与正文之间的固定过渡句，一句收束、引出下文分条。",
     "现将有关事项通知如下："),
    ("主体·工作举措", "健全…机制、完善…制度、创新…方式、强化…保障、压实…责任、凝聚…合力",
     "工作方案/意见/讲话", "写对策/举措时的动宾规范搭配，避免“搞好、弄好”这类口语。",
     "健全联防联控机制，压实属地管理责任，凝聚多方参与合力。"),
    ("主体·工作成效", "取得显著成效、实现新突破、迈上新台阶、亮点纷呈、由…向…转变、提质增效",
     "总结/报告/推荐材料", "写成绩时的上位概括词，配数据更有说服力。",
     "各项工作取得显著成效，群众满意度实现新突破。"),
    ("主体·存在问题", "仍存在短板、有待加强、亟需破解、还不够…、尚未根本扭转、存在…的问题",
     "报告/分析/自查", "客观指出不足的委婉规范说法，先肯定再指出。",
     "个别环节衔接仍存在短板，长效机制有待进一步加强。"),
    ("主体·分条领起", "一是…二是…三是…、其一…其二…、首先…其次…再次…、坚持…、突出…、注重…",
     "意见/方案/讲话", "分条作答的领起词，同一份材料内保持句式一致。",
     "一是加强组织领导，二是细化任务分工，三是强化督导考核。"),
    ("结尾·号召（倡议）", "让我们…、携手…、共同…、从我做起、从现在做起、以实际行动…",
     "倡议书/演讲稿", "倡议、演讲类的结尾动员语，有感染力、有画面感。",
     "让我们携手行动起来，从点滴做起，共建美丽家园。"),
    ("结尾·要求（通知）", "请…遵照执行、请…抓好落实、请…及时…、务必…、确保…",
     "通知/通报", "布置类文书的结尾要求语，对象明确、要求具体。",
     "请各单位高度重视，结合实际抓好落实，确保各项任务落到实处。"),
    ("结尾·收束（报告/请示）", "特此报告、特此通知、特此函告、以上意见妥否，请批示、当否，请示",
     "报告/请示/函", "上行/平行文的固定收束语，用错文种是硬伤。",
     "以上报告妥否，请批示。"),
    ("称谓·抬头落款", "各…、全体…、尊敬的…、此致敬礼、特此、（落款：单位+日期）",
     "通知/倡议书/书信", "格式要素，抬头顶格、落款右对齐、日期写全。",
     "各县（区）人民政府，市政府各部门："),
    ("态度·重视强调", "高度重视、充分认识…的重要性、切实增强…的自觉、深刻领会、扛牢…责任",
     "讲话/意见/通知", "强调重要性时的规范表述，避免“很重要、要注意”。",
     "各级各部门要充分认识此项工作的重要性和紧迫性。"),
    ("数据·概括表述", "同比增长…、覆盖率达…、惠及…群众、办结…件、压缩…时间、下降…个百分点",
     "总结/报告/推荐材料", "用数据说话时的规范句式，动词+数据，别堆形容词。",
     "累计惠及群众12万人次，平均办理时限压缩60%。"),
    ("分析·原因归纳", "根本原因在于…、既有…也有…、主观上…客观上…、深层次…、既受…影响，又…",
     "综合分析/报告", "综合分析题挖原因的规范框架，分层次、分主客观。",
     "问题的根源，既有制度设计上的不完善，也有执行环节的不到位。"),
    ("影响·意义表述", "有利于…、为…提供…、对…具有重要意义、是…的必然要求、是…的重要举措",
     "综合分析/讲话", "谈意义、影响时的上位句式，正向排比更饱满。",
     "此举有利于优化营商环境，为高质量发展提供有力支撑。"),
    ("对策·落实保障", "加强组织领导、明确责任分工、加大投入力度、强化督导考核、注重宣传引导、建立长效机制",
     "对策题/方案/意见", "提对策的“万能”保障维度，按“人财物、督宣制”展开。",
     "要加强组织领导，明确责任分工，建立常态化督导考核机制。"),
]


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            sec_question TEXT,
            sec_answer_hash TEXT,
            email TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            word TEXT NOT NULL, pinyin TEXT, category TEXT,
            explanation TEXT, derivation TEXT, example TEXT,
            note TEXT, source TEXT, starred INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS materials(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            section TEXT, board TEXT,
            title TEXT, orig_name TEXT, stored_name TEXT,
            ext TEXT, mime TEXT, size INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_mat_user ON materials(user_id, board);
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            board TEXT,
            content TEXT,
            images TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, board);
        CREATE TABLE IF NOT EXISTS notebooks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            intro TEXT,
            cover INTEGER DEFAULT 0,
            sort INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_nb_user ON notebooks(user_id);
        CREATE TABLE IF NOT EXISTS kb_nodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notebook_id INTEGER NOT NULL,
            parent_id INTEGER,
            type TEXT NOT NULL,            -- 'group' 分组 | 'doc' 文档
            title TEXT,
            content TEXT,                 -- 文档块 JSON（doc 才有）
            sort INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_kbn_book ON kb_nodes(user_id, notebook_id, parent_id);
        CREATE TABLE IF NOT EXISTS classics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT, title TEXT, author TEXT, dynasty TEXT, content TEXT, sub TEXT,
            translation TEXT, appreciation TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_classics_cat ON classics(category);
        CREATE TABLE IF NOT EXISTS classic_stars(
            user_id INTEGER NOT NULL,
            classic_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, classic_id)
        );
        -- AI 讲解全局缓存（同一首诗只算一次，省钱）
        CREATE TABLE IF NOT EXISTS classic_ai(
            classic_id INTEGER PRIMARY KEY,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 错题本
        CREATE TABLE IF NOT EXISTS wrong_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            board TEXT, question TEXT, image TEXT, answer TEXT,
            qtype TEXT, points TEXT, method TEXT, skill TEXT, steps TEXT,
            note TEXT, starred INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_wq_user ON wrong_questions(user_id, board);
        -- 各板块基础知识点：AI 生成的概览(全局共享缓存) + 用户补充(按人)
        CREATE TABLE IF NOT EXISTS board_kb(
            board TEXT PRIMARY KEY, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS board_points(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, board TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bp_user ON board_points(user_id, board);
        -- 党建理论学习词典（爬自共产党员网 12371.cn，全局共享）
        CREATE TABLE IF NOT EXISTS party_dict(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat TEXT, term TEXT, content TEXT, url TEXT, ord INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_pd_cat ON party_dict(cat);
        -- 只读参考词典（chinese-xinhua）。数据由 build_db.py 从 idiom.json / ci.json 灌进来，
        -- 但**表本身必须在这儿建**：core.lookup() 无条件查这两张表，而 build_db.py 是手工跑的
        -- 构建脚本——没跑过它的新库，一查成语就 no such table: ref_idiom 直接崩。
        -- 建成空表则优雅降级：lookup 查不到，返回 found=False，功能照常。
        CREATE TABLE IF NOT EXISTS ref_idiom(
            word TEXT PRIMARY KEY, pinyin TEXT, explanation TEXT,
            derivation TEXT, example TEXT
        );
        CREATE TABLE IF NOT EXISTS ref_ci(word TEXT PRIMARY KEY, explanation TEXT);
        -- 词典未收录的词/成语：AI 解释后全局缓存，lookup 也会命中（生成一次全站可查）
        CREATE TABLE IF NOT EXISTS ci_ai(
            word TEXT PRIMARY KEY, pinyin TEXT, category TEXT, explanation TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日时政：爬虫抓取 + AI 处理（全局共享，定时后台跑，省 token）
        CREATE TABLE IF NOT EXISTS news_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, url TEXT UNIQUE, source TEXT, pub_date TEXT,
            content TEXT, ai_summary TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 时政要文库：重要文件全文 + AI 政策解读（全局共享）
        CREATE TABLE IF NOT EXISTS policy_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, category TEXT, source_url TEXT,
            content TEXT, interpretation TEXT, ord INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日时政收藏（按人）
        CREATE TABLE IF NOT EXISTS news_stars(
            user_id INTEGER NOT NULL, news_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, news_id)
        );
        -- 每日写作素材（人物事例/具体事例/理论论据/衔接表达）：与微信 08:00 推送共用
        -- 同一份生成结果（~/.openclaw/kaogong-cache/*.txt），App 端解析入库展示
        CREATE TABLE IF NOT EXISTS sucai_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, kind TEXT, topic TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(date, kind, content)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_date ON sucai_items(date);
        -- 专项练：资料分析/判断推理/数量关系这三块靠**练**提分（有固定题型、有秒杀技巧、要计时），
        -- 不像常识靠背。每做一题记一条，用来算「哪个题型最弱、平均要花多久」，弱的排前面。
        CREATE TABLE IF NOT EXISTS drill_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, board TEXT, qtype TEXT,
            correct INTEGER DEFAULT 0, seconds REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_dr_u ON drill_log(user_id, board, qtype);
        -- 每日新闻视频：抓 → AI 按公考价值筛 → 只留最值得看的几条。
        -- 信源只用白名单里的官方媒体（央视网 / 川观新闻）—— 没法自动确认「某个博主是不是真的」，
        -- 所以不接受任意来源，那等于把把关的活儿丢给用户自己。
        CREATE TABLE IF NOT EXISTS video_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT,              -- 国内 / 国际 / 四川
            column_name TEXT,        -- 栏目（新闻联播 / 今日关注 / 川观新闻…）
            source TEXT,             -- 信源（央视网 · CCTV-1 …）
            title TEXT, url TEXT, cover TEXT, duration TEXT,
            pub_date TEXT,
            brief TEXT,              -- 本期内容提要（央视网自带，是筛选的依据）
            why TEXT,                -- AI 说的「为什么值得看」（考点在哪）
            tags TEXT, score INTEGER DEFAULT 5,
            guid TEXT UNIQUE,        -- 同一条视频不重复收
            pick_date TEXT,          -- 哪天选中的
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_vid ON video_items(pick_date DESC, board);
        CREATE TABLE IF NOT EXISTS video_stars(
            user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, video_id)
        );
        -- 人民时评·申论范文：每天从人民日报评论版（paper.people.com.cn）抓「人民时评」那篇。
        -- 它是标准的申论大作文范本 —— 提出问题、分析问题、给对策，还有可直接借鉴的过渡句和金句。
        -- pullquote=报纸上那段highlight的提要；analysis=AI 拆的结构/亮点/可仿写表达（生成一次全局缓存）。
        CREATE TABLE IF NOT EXISTS essay_models(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pub_date TEXT,                   -- 见报日期 YYYY-MM-DD
            column_name TEXT,                -- 栏目（人民时评）
            title TEXT, author TEXT,
            source_url TEXT UNIQUE,          -- 同一篇不重复收
            pullquote TEXT,                  -- 报纸上那段提要
            content TEXT,                    -- 正文全文
            analysis TEXT,                   -- AI 拆解（结构/亮点/可仿写表达），按需生成后缓存
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS essay_model_stars(
            user_id INTEGER NOT NULL, model_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, model_id)
        );
        -- ============ 好友 / 聊天 / 云盘（QQ·微信式）============
        -- 好友：请求 + 关系（关系存双向两条，查「我的好友」直接一句）
        CREATE TABLE IF NOT EXISTS friend_reqs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER, msg TEXT,
            status TEXT DEFAULT 'pending',        -- pending/accepted/rejected
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS friends(
            user_id INTEGER, friend_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, friend_id)
        );
        -- 云盘文件（任意格式）。聊天「发文件」也存这张表（一份存储两处用）：
        --   owner_id 是属主；is_dir=1 是文件夹（stored_name 空）；folder 是所在文件夹路径。
        CREATE TABLE IF NOT EXISTS drive_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            folder TEXT DEFAULT '',               -- '' / '安装包' / '文档/公考'
            name TEXT, stored_name TEXT,
            ext TEXT, mime TEXT, size INTEGER DEFAULT 0,
            is_dir INTEGER DEFAULT 0,
            source TEXT DEFAULT 'drive',          -- drive=用户上传 / chat=聊天收到的文件
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drive ON drive_files(owner_id, folder);
        -- 分享链接：**全站唯一不需要登录就能取到东西的入口**，所以 token 必须够长够随机
        -- （secrets.token_urlsafe，192 位），且每次取用都要复查有没有过期、文件还在不在。
        CREATE TABLE IF NOT EXISTS drive_shares(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            file_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            expires_at TEXT,                      -- NULL = 不过期
            hits INTEGER DEFAULT 0,               -- 被下载过几次
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_share_tok ON drive_shares(token);
        CREATE INDEX IF NOT EXISTS idx_share_own ON drive_shares(owner_id, file_id);
        -- 一对一聊天消息。文件类消息引用 drive_files.id（收到的文件也会进对方云盘的「聊天文件」夹）
        CREATE TABLE IF NOT EXISTS chat_msgs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER,
            kind TEXT DEFAULT 'text',             -- text / file / image
            body TEXT,                            -- 文本内容
            file_id INTEGER, file_name TEXT, file_size INTEGER, file_mime TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            read_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_chat ON chat_msgs(from_uid, to_uid, id);
        CREATE INDEX IF NOT EXISTS idx_chat2 ON chat_msgs(to_uid, from_uid, id);
        -- 专项练题库：常识/政治理论/言语这三块出不了程序化题（考的是知识，不是构造），
        -- 只能让 AI 出。但每次现出要等 20 秒 —— 所以**攒进题库**，用的时候直接取，
        -- 不够了再后台补。按 (板块, 题型, 难度) 分桶。
        CREATE TABLE IF NOT EXISTS drill_bank(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, qtype TEXT, level TEXT,
            q TEXT, options TEXT, answer TEXT, explain TEXT, tip TEXT, source TEXT,
            sig TEXT UNIQUE,                 -- 题干指纹，防止重复题
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bank ON drill_bank(board, qtype, level);
        -- 一次专项练的完整记录（题目 + 我的作答 + 用时），不做完就丢
        CREATE TABLE IF NOT EXISTS drill_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            board TEXT, qtype TEXT, level TEXT, mode TEXT,
            total INTEGER, correct INTEGER, seconds REAL,
            items TEXT, answers TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drrec ON drill_records(user_id, id DESC);
        -- 真题作答流水：**每做一次留一条，绝不覆盖**。
        -- 真题就那么几千道、刷完不会再有新的，所以「第二遍第三遍做得怎么样」才是重点；
        -- 只存「最近一次对不对」的话，一道题从错到对的过程就丢了，也排不出该先刷哪些。
        -- 排程本身复用全站的 review_state（kind='realq'），不另起一套遗忘曲线。
        CREATE TABLE IF NOT EXISTS real_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            qid INTEGER NOT NULL, choice TEXT, correct INTEGER, seconds REAL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_rat_user ON real_attempts(user_id, qid);
        -- 真题库三张表。**必须建在这儿**，哪怕内容全靠 ingest_real.py 灌：
        -- /api/real/* 会直接查它们，没跑过导入脚本的新库上就是 500
        -- （schema.py 开头那段警告说的 changkao_items.freq / news_items.board 就是这么崩的）。
        CREATE TABLE IF NOT EXISTS real_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER UNIQUE,
            name TEXT, folder TEXT, ext TEXT,
            exam TEXT, year INTEGER, season TEXT, paper TEXT, kind TEXT,
            pkey TEXT,                        -- 卷子身份（规范化文件名+卷别令牌）
            role TEXT, n_item INTEGER DEFAULT 0,
            answers_ok INTEGER DEFAULT 1,     -- 0 = 答案被判定错位，出题时屏蔽
            status TEXT, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS real_raw(
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER, seq INTEGER,
            module TEXT, stem TEXT, options TEXT, answer TEXT, explain TEXT,
            qhash TEXT, ohash TEXT, fighash TEXT DEFAULT '', qid INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_raw_paper ON real_raw(paper_id);
        CREATE INDEX IF NOT EXISTS idx_raw_hash ON real_raw(qhash);
        CREATE INDEX IF NOT EXISTS idx_raw_ohash ON real_raw(ohash);
        -- 去重后的真题。qid 上**没有 UNIQUE**：图形推理那种通用题干天然会有很多条
        -- 题干一模一样、内容却不同的题，判重靠 (qhash, ohash) 两个一起。
        CREATE TABLE IF NOT EXISTS real_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT, qtype TEXT,
            stem TEXT, options TEXT, answer TEXT, explain TEXT,
            qhash TEXT, ohash TEXT, fighash TEXT DEFAULT '', dkey TEXT,
            material TEXT,                    -- 资料分析的给定资料
            sources TEXT, n_src INTEGER DEFAULT 1,
            year_min INTEGER, year_max INTEGER,
            has_answer INTEGER DEFAULT 0, needs_asset INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_rq_mod ON real_questions(module, qtype);
        CREATE INDEX IF NOT EXISTS idx_rq_year ON real_questions(year_max);
        CREATE INDEX IF NOT EXISTS idx_rq_hash ON real_questions(qhash, ohash);
        -- AI 补的答案与**结构化**解析（关键/步骤/错项/举一反三，前端按固定版式排）
        CREATE TABLE IF NOT EXISTS real_explains(
            qid INTEGER PRIMARY KEY, answer TEXT, src TEXT,
            module TEXT DEFAULT '', qtype TEXT,
            keypoint TEXT, steps TEXT, wrong TEXT, tip TEXT, model TEXT,
            audit_ans TEXT DEFAULT '',
            agree INTEGER DEFAULT 1,      -- 0 = 双模型答案不一致，不发给人做
            flaw TEXT DEFAULT 'ok',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_rex_agree ON real_explains(agree);
        -- 真题里的图（图形推理的图就是题本身）。/api/real/quiz 会查它，
        -- 只由 ingest_figs.py 建的话，没跑过提图脚本的新库上就查不到表。
        CREATE TABLE IF NOT EXISTS real_figs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL, ord INTEGER DEFAULT 0,
            sha TEXT NOT NULL, ext TEXT,
            big INTEGER DEFAULT 0,     -- 1 = 单张大图，多半是整题画在一起
            -- kind='mat' = 资料分析的材料图（经过材料归属那条路挂上来的）；
            -- 空 = 按段落邻近挂给单题的图。两者不能混：材料齐不齐只能看前者。
            kind TEXT DEFAULT '',
            UNIQUE(qid, sha)
        );
        CREATE INDEX IF NOT EXISTS idx_rfig_q ON real_figs(qid);
        -- 扫描件 OCR 的结果。**独立成表、按云盘文件 id 挂**：real_papers 会被
        -- ingest_real.py 整表重建，挂在那上面一重建就没了，而视觉模型跑一遍要几小时。
        CREATE TABLE IF NOT EXISTS real_ocr(
            file_id INTEGER PRIMARY KEY, name TEXT,
            -- synth=1：题号是按解析块出现顺序编的，不是卷子上印的。用之前必须核对
            -- 「块数 == 本卷最大题号」，中间吞一块就整卷错位一格，比没答案还糟。
            synth INTEGER DEFAULT 0,
            -- **识别原文照原样存下来**：OCR 是整条链上最贵的一步（一份 A0 大卷 4 分钟），
            -- 而 parse_answers 认的排版一直在加。不存原文的话，每补一种排版就得把
            -- 几十页大图重扫一遍。存了就能 --reparse 秒级重跑。
            ocr_text TEXT,
            n_item INTEGER DEFAULT 0, ans_json TEXT, model TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 小题训练（找点 + 写点）：归纳概括/综合分析/提出对策的共同难点都是「从材料里找要点」。
        -- 要能判「找漏了/找错了/找重了」，就必须存下**采分点 ↔ 材料原文的逐字依据**：
        -- points = [{point:概括后的要点, evidence:逐字来自材料的原句, score:分值}]
        -- 没有 evidence 就只能凭感觉批，那等于没批。
        CREATE TABLE IF NOT EXISTS find_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            qtype TEXT, type_name TEXT, stem TEXT, requirement TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER,
            material TEXT, points TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS find_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            paper_id INTEGER NOT NULL,
            marks TEXT,          -- 我勾画的句子下标
            find_result TEXT,    -- 找点判定结果
            answer TEXT,         -- 我写的点子
            grade TEXT,          -- 写点批改结果
            score REAL, full INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 常考收藏：六个小模块的数据来自三张不同的表（changkao_items / hyper_items / classics），
        -- 所以这里按 (board, item_id) 存，并把标题正文快照下来 —— 收藏列表要能直接显示，
        -- 不用回头去三张表里各查一遍。
        CREATE TABLE IF NOT EXISTS ck_stars(
            user_id INTEGER NOT NULL, board TEXT NOT NULL, item_id INTEGER NOT NULL,
            title TEXT, content TEXT, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, board, item_id)
        );
        -- 成文：把散落的素材真正写成一篇大作文（不然素材背了也不会用）
        --   mode=daily    按「素材日期」成文，一天一篇，用当天更新的那批素材
        --   mode=compose  综合应用，AI 自己选题，跨全部素材库挑最合适的
        --   mode=yingyong 应用文，导航位先占着，生成逻辑待定
        CREATE TABLE IF NOT EXISTS daily_essays(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL, date TEXT NOT NULL,
            topic TEXT, title TEXT, outline TEXT, content TEXT,
            words INTEGER DEFAULT 0,
            used TEXT,            -- JSON：真正用进文章的素材（服务端逐条核对过）
            note TEXT,            -- AI 的选材说明
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(mode, date)
        );
        -- 常识积累（7板块×专题，条目由 AI 生成/每日更新/新法跟踪，全局共享）
        CREATE TABLE IF NOT EXISTS changshi_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, topic TEXT, title TEXT, content TEXT,
            date TEXT, source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, topic, title)
        );
        CREATE INDEX IF NOT EXISTS idx_cs_bt ON changshi_items(board, topic);
        -- 题库（四川省考卷面结构，每周自动更新两次）
        CREATE TABLE IF NOT EXISTS quiz_sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, kind TEXT DEFAULT '行测',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS quiz_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, set_id INTEGER, seq INTEGER,
            module TEXT, qtype TEXT, material TEXT, question TEXT,
            options TEXT, answer TEXT, explanation TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_qq_set ON quiz_questions(set_id, seq);
        -- 共享待办（两账号互相监督，全局共享）
        CREATE TABLE IF NOT EXISTS shared_todos(
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT,
            created_by TEXT, done INTEGER DEFAULT 0, done_by TEXT, done_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日任务模板（用户自定义，每天生成当日任务）
        CREATE TABLE IF NOT EXISTS task_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            text TEXT, sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 每日任务完成记录（按天）
        CREATE TABLE IF NOT EXISTS task_done(
            user_id INTEGER NOT NULL, tpl_id INTEGER NOT NULL, date TEXT NOT NULL,
            done_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, tpl_id, date)
        );
        -- 古诗文每日推荐（全局，按日期）
        CREATE TABLE IF NOT EXISTS classic_daily(
            date TEXT PRIMARY KEY, classic_id INTEGER, apply TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS quiz_answers(
            user_id INTEGER NOT NULL, set_id INTEGER, qid INTEGER NOT NULL,
            choice TEXT, correct INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, qid)
        );
        -- 习语金句（学习强国风格：每日从习近平讲话数据库真实原文提炼，分八类）
        CREATE TABLE IF NOT EXISTS xiyu_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, category TEXT, quote TEXT, note TEXT, source_url TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(quote)
        );
        -- 经典著作（毛泽东选集等）：全文 + AI 解读缓存
        CREATE TABLE IF NOT EXISTS works(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book TEXT, ord INTEGER, title TEXT, content TEXT, interpretation TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 全局 AI 会话中心（仿 Claude：项目 / 会话 / 消息）
        CREATE TABLE IF NOT EXISTS ai_projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT, instructions TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            project_id INTEGER, title TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ai_msgs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            role TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_aim_chat ON ai_msgs(chat_id);
        -- 遗忘曲线复习进度（艾宾浩斯间隔：1/2/4/7/15/30/60 天）
        CREATE TABLE IF NOT EXISTS review_state(
            user_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id INTEGER NOT NULL,
            stage INTEGER DEFAULT 0, next_due TEXT, last_done TEXT,
            PRIMARY KEY(user_id, kind, item_id)
        );
        -- 申论概括句积累：每日由当天时政素材生成（全局共享，按日期查看）
        CREATE TABLE IF NOT EXISTS gaikuo_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, topic TEXT, raw TEXT, sentence TEXT, tip TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_gk_date ON gaikuo_items(date);
        -- 标注（手写批注/高亮/笔记）。存服务器＝换设备不丢、多端同步、能进复习/搜索。
        -- 锚（anchor）决定这条标注"贴在哪"，三种：
        --   text  ：{quote,prefix,suffix,start} 按文本定位。字号/字体/宽度/设备随便变都贴着那句话。
        --           （同 AI 划重点的做法，见 app.js mkWrapOne；也就是 W3C Web Annotation 的
        --            TextQuoteSelector。）文本类内容一律走这条。
        --   pdf   ：{page,x,y} 归一化到页内 —— PDF 是固定版式，但缩放会变像素，所以按页归一化。
        --   pixel ：{} 兜底（图片等固定内容，或画在空白处锚不住文本时）＝老的视口坐标行为。
        -- data 存这条标注自己的内容：手写＝笔迹点（相对锚，不是相对屏幕）；笔记＝文字。
        CREATE TABLE IF NOT EXISTS annotations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target TEXT NOT NULL,          -- 标注挂在哪份内容上（mat:<id> / view:<视图>:<id>）
            anchor_type TEXT NOT NULL,     -- text | pdf | pixel
            anchor TEXT NOT NULL,          -- JSON，按 anchor_type 解释
            kind TEXT NOT NULL,            -- ink 手写 | hl 高亮 | note 文字
            data TEXT,                     -- JSON，见上
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_ann_target ON annotations(user_id, target);
        """
    )
    con.executescript("""
        -- 互监待办：每人独立打勾（旧 shared_todos.done 保留兼容）
        CREATE TABLE IF NOT EXISTS shared_todo_done(
            todo_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT,
            done_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(todo_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS todo_members(
            user_id INTEGER PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 组队（互监）：邀请制，一个用户同一时间只在一个队里
        CREATE TABLE IF NOT EXISTS teams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS team_members(
            team_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            joined_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(team_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS team_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uid INTEGER, to_uid INTEGER, kind TEXT,   -- join 组队 / disband 解散
            team_id INTEGER, status TEXT DEFAULT 'pending', -- pending/accepted/rejected/cancelled
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_treq ON team_requests(to_uid, status);
        -- 常考（高频考点合集）
        CREATE TABLE IF NOT EXISTS changkao_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, title TEXT, content TEXT, note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, title)
        );
        CREATE INDEX IF NOT EXISTS idx_ck_board ON changkao_items(board);
        -- 上位词积累（逻辑填空「概括词/上位词」提示）
        CREATE TABLE IF NOT EXISTS hyper_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hyper TEXT UNIQUE, subs TEXT, note TEXT, example TEXT,
            source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 应用文上位词（公文规范上位表述：口语/具体表述 → 规范提法，按场景归类）
        CREATE TABLE IF NOT EXISTS gongwen_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene TEXT UNIQUE, phrases TEXT, doctype TEXT, note TEXT, example TEXT,
            source TEXT DEFAULT 'seed',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 理论基础（马原/毛中特/习思想…）
        CREATE TABLE IF NOT EXISTS theory_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT, topic TEXT, title TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(board, title)
        );
        CREATE INDEX IF NOT EXISTS idx_th_board ON theory_items(board, topic);
        -- 申论 AI 逐点批改记录
        CREATE TABLE IF NOT EXISTS shenlun_grade(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            qtype TEXT, type_name TEXT, question TEXT, material TEXT, answer TEXT,
            score REAL, full INTEGER, result TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_sl_user ON shenlun_grade(user_id, id DESC);
        -- 上传的申论真题卷（材料 + 各小题）
        CREATE TABLE IF NOT EXISTS shenlun_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT, material TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS shenlun_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
            seq INTEGER, qtype TEXT, type_name TEXT, stem TEXT, requirement TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_slq_paper ON shenlun_questions(paper_id, seq);
        -- 站内消息：内容库有更新、复习/任务到点，都在这里提醒，点开直达
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT, dkey TEXT, title TEXT, body TEXT, link TEXT,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, kind, dkey)
        );
        CREATE INDEX IF NOT EXISTS idx_ntf_user ON notifications(user_id, read, id DESC);
        -- 后台长任务（文档识题解析、范文生成）：前端轮询进度
        CREATE TABLE IF NOT EXISTS bg_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT, title TEXT, status TEXT DEFAULT 'running',
            progress INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
            message TEXT, result_id INTEGER, extra TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_bg_user ON bg_tasks(user_id, id DESC);
        -- 范文推荐：一套仿真卷（材料按真题字数规格） + 各题完整参考答案
        CREATE TABLE IF NOT EXISTS essay_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT UNIQUE, spec TEXT, title TEXT, material TEXT, words INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS essays(
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
            seq INTEGER, qtype TEXT, type_name TEXT, stem TEXT,
            full INTEGER, word_min INTEGER, word_max INTEGER,
            answer TEXT, answer_words INTEGER, outline TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_essay_paper ON essays(paper_id, seq);
        -- 文档识题：从讲义/资料里抽出的例题 + AI 答案解析
        CREATE TABLE IF NOT EXISTS doc_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            page INTEGER, seq INTEGER, stem TEXT, options TEXT,
            answer TEXT, explain TEXT, qtype TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dq_task ON doc_questions(task_id, page, seq);
        -- 备考规划：一份个人档案 + 每天一份 AI 排的学习计划
        CREATE TABLE IF NOT EXISTS plan_profile(
            user_id INTEGER PRIMARY KEY,
            exam TEXT, exam_date TEXT, minutes INTEGER DEFAULT 120,
            weak TEXT, note TEXT,
            summary TEXT, summary_date TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS plan_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT NOT NULL, seq INTEGER, title TEXT, module TEXT,
            minutes INTEGER, reason TEXT, link TEXT,
            done INTEGER DEFAULT 0, done_at TEXT, source TEXT DEFAULT 'ai',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_plan_user ON plan_items(user_id, date, seq);
        -- 每日计划快照：重排/换天前把旧计划存一份，方便回看和被覆盖后还能找回
        CREATE TABLE IF NOT EXISTS plan_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')),
            summary TEXT, minutes_total INTEGER, done_n INTEGER, total INTEGER,
            items_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_plan_log ON plan_log(user_id, date DESC, id DESC);
        -- 每日巩固测试：按当天学的内容出一份小测，按 用户+日期 缓存
        CREATE TABLE IF NOT EXISTS daily_quiz(
            user_id INTEGER NOT NULL, date TEXT NOT NULL,
            questions_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(user_id, date)
        );
        -- 巩固测试记录：每交一次卷存一条，可回看
        CREATE TABLE IF NOT EXISTS dtest_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            date TEXT, score INTEGER, total INTEGER, detail_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_dtrec ON dtest_records(user_id, id DESC);
        -- 学习天数：完成备考规划/互监待办的当天记一笔，用来算连续与累计
        CREATE TABLE IF NOT EXISTS study_days(
            user_id INTEGER NOT NULL, date TEXT NOT NULL,
            PRIMARY KEY(user_id, date)
        );
        -- 资料库共享：把某份资料共享给指定的人（队友），对方在资料库看得到「共享给我的」
        CREATE TABLE IF NOT EXISTS material_shares(
            material_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, to_user INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(material_id, to_user)
        );
        CREATE INDEX IF NOT EXISTS idx_mshare_to ON material_shares(to_user);
        -- 通用「划重点」缓存：按内容哈希存，同一段内容全局只算一次（哪个模块打开都直接命中）
        CREATE TABLE IF NOT EXISTS marks_cache(
            ref TEXT PRIMARY KEY, scope TEXT, data_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 书签：看到哪了（阅读类页面自动记位置，也可手动打点）
        CREATE TABLE IF NOT EXISTS bookmarks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT NOT NULL, ref TEXT NOT NULL, title TEXT, pos REAL DEFAULT 0, note TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, kind, ref)
        );
        -- 40 天冲刺路线图：阶段/每日定额/正确率目标，规划助手每天照它排任务
        CREATE TABLE IF NOT EXISTS plan_roadmap(
            user_id INTEGER PRIMARY KEY, start_date TEXT, days INTEGER DEFAULT 40,
            data_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 草稿本（错题本里，平时打草稿用）：笔迹按向量存，不做识别
        CREATE TABLE IF NOT EXISTS drafts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT, data_json TEXT, pages INTEGER DEFAULT 1, thumb TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_drafts ON drafts(user_id, updated_at DESC);
    """)
    # ↓↓ 到这里为止所有表都建好了，下面才开始「补列」（ALTER）。
    # 顺序很要紧：changkao_items / hyper_items / xiyu_items 的建表在上面第二个 executescript 里，
    # 而它们的 ALTER 原本排在那之前 —— 全新空库上 _cols() 对不存在的表返回空集合，
    # 于是 "col not in set()" 成立、直接 ALTER 一张还没有的表 → init_db() 必崩。
    # 生产库因为表早就在所以从没暴露，换机/新部署就会炸。
    # entries 老表可能缺 user_id 列（先补列，再建索引）
    if "user_id" not in _cols(con, "entries"):
        con.execute("ALTER TABLE entries ADD COLUMN user_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_entries_user ON entries(user_id)")
    # ai_chats 补 starred（置顶）
    if "starred" not in _cols(con, "ai_chats"):
        con.execute("ALTER TABLE ai_chats ADD COLUMN starred INTEGER DEFAULT 0")
    # 应用文比大作文多一层：得先有「文种 + 发文场景 + 我是谁 + 写给谁」才谈得上选素材
    if "spec" not in _cols(con, "daily_essays"):
        con.execute("ALTER TABLE daily_essays ADD COLUMN spec TEXT")
    # 每日复习量：一天能背多少是因人而异的，原来写死 120 条（只能改环境变量），堆起来就不想背了
    if "rv_limits" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN rv_limits TEXT")
    # 专项练加了难度档，统计要按难度分开（不然入门刷出来的高正确率会盖住真实水平）
    if "level" not in _cols(con, "drill_log"):
        con.execute("ALTER TABLE drill_log ADD COLUMN level TEXT DEFAULT 'mid'")
    # AI 出的题要过**第二个模型的独立核验**才能发给人做（实测抽检：单模型出题一致率只有 89%，
    # 也就是每 9 道就有 1 道值得怀疑；而且真抓到过事实错误 —— 「山水林田湖草沙」那道就是错的）。
    for col, dflt in (("checked", "0"), ("agree", "0"), ("audit_ans", "''"),
                      ("audit_note", "''"), ("flaw", "''")):
        if col not in _cols(con, "drill_bank"):
            con.execute("ALTER TABLE drill_bank ADD COLUMN %s TEXT DEFAULT %s" % (col, dflt))
    # 成语/实词的例句：光有释义记不住怎么用。**先从真实官方语料里找**（人民日报时政、时政要文、
    # 习语金句都是真文本），找到就是真出处；找不到才让 AI 仿写，并**明说是仿写**。
    for col in ("example", "example_src", "confuse"):
        if col not in _cols(con, "changkao_items"):
            con.execute("ALTER TABLE changkao_items ADD COLUMN %s TEXT" % col)
    # freq/source 原先只由 import_teacher.py 建，可 app.py 自己要查 freq（复习轮按考频排序）。
    # 没导过讲义的新库 → /api/changkao/items、/api/review/today 全 500。schema 得在这儿自洽。
    for col, decl in (("freq", "INTEGER DEFAULT 0"), ("source", "TEXT")):
        if col not in _cols(con, "changkao_items"):
            con.execute("ALTER TABLE changkao_items ADD COLUMN %s %s" % (col, decl))
    # 高频实词的词义：原来只有 content=常用搭配（履行→责任/职责/使命…），没有这个词本身是啥意思。
    # 加一列 meaning，由 build_ck_meaning.py 先查内置词典、查不到用 AI 补齐。
    if "meaning" not in _cols(con, "changkao_items"):
        con.execute("ALTER TABLE changkao_items ADD COLUMN meaning TEXT")
    # 人民时评范文的「逐段批注」（对照精读）：analysis 是整篇拆解，看着和正文割裂；
    # annotations 是 JSON {段号: 这段在做什么/好在哪/可仿写点}，渲染时跟在对应段落后面。
    if "annotations" not in _cols(con, "essay_models"):
        con.execute("ALTER TABLE essay_models ADD COLUMN annotations TEXT")
    # 资料库的自定义分类（原来只存在前端内存里，从已有资料反推 → 新建了但还没传东西的分类，重启就没了）
    if "mat_boards" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN mat_boards TEXT")
    # 云盘按内容去重：同一个人传同一份内容（同 sha256）只在磁盘上留一份，多行共用一个
    # stored_name。**所以删文件必须先数还有没有别的行在引用它**，见 _drop_blob。
    if "sha256" not in _cols(con, "drive_files"):
        con.execute("ALTER TABLE drive_files ADD COLUMN sha256 TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_drive_hash ON drive_files(owner_id, sha256)")
    # 回收站：删除只打这个时间戳（软删），过 N 天或手动清空才真从磁盘上抹掉。
    # 所以**凡是列文件的地方都要带 deleted_at IS NULL**，漏一处回收站里的东西就漏回列表里。
    if "deleted_at" not in _cols(con, "drive_files"):
        con.execute("ALTER TABLE drive_files ADD COLUMN deleted_at TEXT")
    # 每次删除给一个批次号：恢复文件夹时只捞「跟它一起删的那批」。
    # 别拿 deleted_at 当批次认 —— 它只精确到秒，同一秒里删两次就会串批，
    # 表现是「恢复一个文件夹，把早先单独删掉的东西也一并捞了回来」。
    if "del_batch" not in _cols(con, "drive_files"):
        con.execute("ALTER TABLE drive_files ADD COLUMN del_batch TEXT")
    # 分享链接可以加访问密码（存 hash，绝不存明文 —— 这张表里的东西是给外人用的）；
    # is_dir 记下分享的是文件还是文件夹，文件夹走打包下载。
    for col, decl in (("pw_hash", "TEXT"), ("is_dir", "INTEGER DEFAULT 0")):
        if col not in _cols(con, "drive_shares"):
            con.execute("ALTER TABLE drive_shares ADD COLUMN %s %s" % (col, decl))
    con.execute("CREATE INDEX IF NOT EXISTS idx_drive_del ON drive_files(owner_id, deleted_at)")
    # 外观定制：头像 / 应用内壁纸 / 登录页壁纸（存文件名，图片放 uploads/skin/<uid>/）
    for col in ("avatar", "wall_app", "wall_login"):
        if col not in _cols(con, "users"):
            con.execute("ALTER TABLE users ADD COLUMN %s TEXT" % col)
    # ci_ai 结构化：补 出处/例句 列
    for col in ("derivation", "example"):
        if col not in _cols(con, "ci_ai"):
            con.execute("ALTER TABLE ci_ai ADD COLUMN %s TEXT" % col)
    # 视频要能在 APP 里直接播（原来点播放键是往外跳浏览器 —— 桌面版还跳不动）。
    #   kind: 决定用哪种播法 —— cctv=自己拿 mp4 分段放；bili=嵌官方播放器；sc=川观（抓到直链才能放）
    #   play: 抓取时就把播放地址算好存下来，用户点播放时不用现去请求人家的接口（快，也不容易失败）
    for col in ("kind", "play"):
        if col not in _cols(con, "video_items"):
            con.execute("ALTER TABLE video_items ADD COLUMN %s TEXT" % col)
    # 老数据没有 kind：按 guid 的长相反推（BV 开头是 B 站，32 位十六进制是央视，剩下的是川观）
    con.execute("UPDATE video_items SET kind = CASE "
                "WHEN guid LIKE 'BV%' THEN 'bili' "
                "WHEN guid GLOB '[0-9a-f]*' AND length(guid)=32 THEN 'cctv' "
                "ELSE 'sc' END WHERE kind IS NULL OR kind=''")
    # 习语金句：补 关键词/申论运用 列
    for col in ("keyword", "apply"):
        if col not in _cols(con, "xiyu_items"):
            con.execute("ALTER TABLE xiyu_items ADD COLUMN %s TEXT" % col)
    # 上位词：补「典故/来源」列（AI 讲一次就缓存，像古诗文赏析那样点开即看）
    if "story" not in _cols(con, "hyper_items"):
        con.execute("ALTER TABLE hyper_items ADD COLUMN story TEXT")
    # 常考成语/实词：补「典故」列（看懂来历自然就记住了，不用死背）
    if "story" not in _cols(con, "changkao_items"):
        con.execute("ALTER TABLE changkao_items ADD COLUMN story TEXT")
    # 每日时政：补「重点标注」列（在原文里划出考点，不用通读全文）
    if "marks" not in _cols(con, "news_items"):
        con.execute("ALTER TABLE news_items ADD COLUMN marks TEXT")
    # board 同理原先只由 crawl_news.py 建，没跑过爬虫的新库进 /api/news 就 500
    if "board" not in _cols(con, "news_items"):
        con.execute("ALTER TABLE news_items ADD COLUMN board TEXT DEFAULT '国内'")
    # 古诗文考频排序
    if "freq" not in _cols(con, "classics"):
        con.execute("ALTER TABLE classics ADD COLUMN freq INTEGER DEFAULT 0")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cls_freq ON classics(freq)")
    # 衔接表达例句
    if "example" not in _cols(con, "sucai_items"):
        con.execute("ALTER TABLE sucai_items ADD COLUMN example TEXT")
    # 每日一诗：常识判断考点
    if "common" not in _cols(con, "classic_daily"):
        con.execute("ALTER TABLE classic_daily ADD COLUMN common TEXT")
    # 首页卡片自定义排序（拖拽保存，JSON 数组）
    if "home_order" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN home_order TEXT")
    # 各功能页卡片排序（JSON 对象：网格键→顺序数组）
    if "ui_orders" not in _cols(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN ui_orders TEXT")
    # 备考规划：把 AI 给出的今日重点存下来，刷新后还能看到
    for col in ("summary", "summary_date"):
        if col not in _cols(con, "plan_profile"):
            con.execute("ALTER TABLE plan_profile ADD COLUMN %s TEXT" % col)
    # 批改记录挂到真题卷上，并记下字数与题目要求的字数区间
    for col, typ in (("paper_id", "INTEGER"), ("question_id", "INTEGER"),
                     ("words", "INTEGER"), ("word_min", "INTEGER"), ("word_max", "INTEGER"),
                     ("requirement", "TEXT")):
        if col not in _cols(con, "shenlun_grade"):
            con.execute("ALTER TABLE shenlun_grade ADD COLUMN %s %s" % (col, typ))
    # 互监待办：交叉确认——记录这个勾是谁打的（只能由搭档打）
    for col, typ in (("by_user", "INTEGER"), ("by_name", "TEXT")):
        if col not in _cols(con, "shared_todo_done"):
            con.execute("ALTER TABLE shared_todo_done ADD COLUMN %s %s" % (col, typ))
    # 互监待办：来源标记——把「备考规划」的今日计划同步进来给搭档监督
    for col, typ in (("source", "TEXT"), ("src_uid", "INTEGER"), ("plan_date", "TEXT"),
                     ("team_id", "INTEGER")):
        if col not in _cols(con, "shared_todos"):
            con.execute("ALTER TABLE shared_todos ADD COLUMN %s %s" % (col, typ))
    # 学习天数回填：从历史完成记录补一次（备考规划完成 + 互监任务被确认）
    try:
        if not con.execute("SELECT COUNT(*) FROM study_days").fetchone()[0]:
            con.execute("INSERT OR IGNORE INTO study_days(user_id,date) "
                        "SELECT user_id, date(done_at) FROM plan_items "
                        "WHERE done=1 AND done_at IS NOT NULL")
            con.execute("INSERT OR IGNORE INTO study_days(user_id,date) "
                        "SELECT user_id, date(done_at) FROM shared_todo_done "
                        "WHERE user_id IS NOT NULL AND done_at IS NOT NULL")
    except Exception:
        log.exception("study_days 回填迁移失败：学习天数统计可能不全")
    # 老数据迁移：把已有的 todo_members 成员组成一个队，现有待办归到这个队
    try:
        if not con.execute("SELECT COUNT(*) FROM teams").fetchone()[0]:
            old = [r[0] for r in con.execute("SELECT user_id FROM todo_members ORDER BY user_id LIMIT 2")]
            if len(old) >= 2:
                tid = con.execute("INSERT INTO teams DEFAULT VALUES").lastrowid
                for u in old:
                    con.execute("INSERT OR IGNORE INTO team_members(team_id,user_id) VALUES(?,?)", (tid, u))
                con.execute("UPDATE shared_todos SET team_id=? WHERE team_id IS NULL", (tid,))
    except Exception:
        log.exception("teams 迁移失败：旧的组队数据可能没并过来")
    # 老数据迁移：shared_todos.done=1 → 记到完成人名下
    try:
        if not con.execute("SELECT COUNT(*) FROM shared_todo_done").fetchone()[0]:
            for r in con.execute("SELECT id, done_by, done_at FROM shared_todos WHERE done=1").fetchall():
                u = con.execute("SELECT id FROM users WHERE username=?", (r[1],)).fetchone()
                if u:
                    con.execute("INSERT OR IGNORE INTO shared_todo_done(todo_id,user_id,username,done_at) "
                                "VALUES(?,?,?,?)", (r[0], u[0], r[1], r[2]))
    except Exception:
        log.exception("shared_todo_done 迁移失败：互监完成记录可能没并过来")
    # notes 表补充字段：标签 / 附件 / 待办清单
    for col in ("tags", "attachments", "todos"):
        if col not in _cols(con, "notes"):
            con.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT")
    # classics 表补充字段：译文 / 赏析
    if "classics" in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
        for col in ("translation", "appreciation"):
            if col not in _cols(con, "classics"):
                con.execute(f"ALTER TABLE classics ADD COLUMN {col} TEXT")

    # 迁移：把旧的单账号(config.json)迁入 users 表，并把无主收录归给它
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        old = {}
        if os.path.exists(CONFIG):
            try:
                old = json.load(open(CONFIG, encoding="utf-8"))
            except Exception:
                old = {}
        if old.get("registered") and old.get("username") and old.get("password_hash"):
            con.execute(
                "INSERT INTO users(username,password_hash,role,email) VALUES(?,?,?,?)",
                (old["username"], old["password_hash"], "admin", old.get("email", "")),
            )
            uid = con.execute("SELECT id FROM users WHERE username=?",
                              (old["username"],)).fetchone()[0]
            con.execute("UPDATE entries SET user_id=? WHERE user_id IS NULL", (uid,))

    # 应用文上位词起步词库：口语/具体表述 → 公文规范上位提法，按场景归类
    if con.execute("SELECT COUNT(*) FROM gongwen_items").fetchone()[0] == 0:
        for scene, phrases, doctype, note, example in _GONGWEN_SEED:
            con.execute("INSERT OR IGNORE INTO gongwen_items(scene,phrases,doctype,note,example,source) "
                        "VALUES(?,?,?,?,?,'seed')", (scene, phrases, doctype, note, example))
    con.commit()
    con.close()
