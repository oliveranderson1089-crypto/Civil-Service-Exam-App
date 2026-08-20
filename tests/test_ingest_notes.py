"""扫描件笔记的解析（ingest_basics.parse_notes）。

这个 parser 吃的是 OCR 文本，形状比有文字层的 PDF 脏得多。下面四条是真跑出来的坑，
每一条当时都让整本书的解析结果错得很难看，而节点数照样是个正常数字：

  1. PDF 软换行把一条要点劈成两行，直接切的话后半截会变成一个新考点；
  2. 表格塌成一串空格，按行读就当噪声扔了 —— 而这批笔记的价值一大半在表里；
  3. 章标题不带句末标点，参与重排的话会把正文首段吸进标题；
  4. 页边竖排的「社工实务」被 OCR 一字一行吐出来，不滤就成了考点。
"""
import ingest_basics as IB


def _parse(text, numbered=False):
    return IB.parse_notes([(1, text)], "社会工作", "测试笔记.pdf", numbered=numbered)


def _titles(nodes, level=3):
    return [n["title"] for n in nodes if n["level"] == level]


def _md(blocks, kind=None):
    return [b["md"] for b in blocks if kind is None or b["kind"] == kind]


class Test跨行重排:
    def test_软换行断开的要点接回成一条(self):
        nodes, blocks = _parse(
            "社会工作目标: 服务对象层面的目标 (解救危难; 缓解困难) 、社会层面的目\n"
            "标 (解决社会问题; 促进社会公正)\n")
        assert _titles(nodes) == ["社会工作目标"]        # 不该多出「标 (解决社会问题」
        assert "社会层面的目标 (解决社会问题" in _md(blocks)[0]

    def test_上一行已收尾就不再接(self):
        nodes, _ = _parse("社会工作的特点: 专业助人活动; 注重专业价值;\n"
                          "社会工作目标: 服务对象层面的目标\n")
        assert _titles(nodes) == ["社会工作的特点", "社会工作目标"]


class Test表格:
    def test_多空格分列重建成markdown表(self):
        _nodes, blocks = _parse(
            "家庭的类型\n"
            "核心家庭      一对夫妇及其未婚子女\n"
            "主干家庭      父母与一对已婚的子女共同居住\n")
        tbl = _md(blocks, "table")
        assert len(tbl) == 1
        assert "| 核心家庭 | 一对夫妇及其未婚子女 |" in tbl[0]
        assert "|---|---|" in tbl[0]                    # 没有分隔行前端渲染不出表格

    def test_只有一行的不算表(self):
        """「1.   在公文的分类中…」这种序号后拖一大段缩进，孤零零一行也满足
        「多空格＝换列」。整本公文知识点就这么被切成过几十张单行表。"""
        _nodes, blocks = _parse("1.   在公文的分类中，根据形成和使用的领域不同，可分为通用公文和专用公文。\n")
        assert not _md(blocks, "table")
        assert "在公文的分类中" in _md(blocks, "concept")[0]


class Test章节:
    def test_章标题不吞正文首段(self):
        nodes, _blocks = _parse(
            "第一章，”社会工作的内涵、原则及主要领域\n"
            "社会工作在一定的社会福利制度框架下，根据专业价值观念帮助有困难的人\n")
        assert _titles(nodes, 2) == ["第一章 社会工作的内涵、原则及主要领域"]

    def test_节标题允许行首粘着OCR噪声(self):
        """四色笔记的侧边栏图标被 OCR 认成了字：「川上 第三节 计划」。
        卡死行首的话 117 页只认得出 2 个章节。"""
        nodes, _ = _parse("川上 第三节 ”计划\n")
        assert _titles(nodes, 2) == ["第三节 计划"]

    def test_例题题干里的第X节不算标题(self):
        nodes, _ = _parse("在 第四节 小组活动中，小何带领组员共同制定了小组规范。下列属于文化规范的是\n")
        # 「全书」是没有章的册子自动补的占位，不算认出了章节
        assert [t for t in _titles(nodes, 2) if t != "全书"] == []


class Test噪声:
    def test_页边竖排单字被滤掉(self):
        nodes, blocks = _parse("社\n工\n实\n务\n社会工作的特点: 专业助人活动; 注重专业价值\n")
        assert _titles(nodes) == ["社会工作的特点"]
        assert all("社\n工" not in m for m in _md(blocks))

    def test_页码页眉被滤掉(self):
        _nodes, blocks = _parse("第 1 页 共 36 页\n社会工作的特点: 专业助人活动\n")
        assert all("共 36 页" not in m for m in _md(blocks))

    def test_带数字的短行留着(self):
        """「(1)」这类编号是正文的一部分，不能跟乱码一起滤掉。"""
        _nodes, blocks = _parse("接案的步骤: 了解服务对象的来源\n(1) 主动求助\n")
        assert any("(1) 主动求助" in m for m in _md(blocks))


class Test序号考点:
    def test_开了开关才把序号行当考点(self):
        text = "1.南昌起义\n又称八一起义，1927 年 8 月 1 日举行。\n"
        on_nodes, on_blocks = _parse(text, numbered=True)
        assert _titles(on_nodes) == ["南昌起义"]
        assert "又称八一起义" in _md(on_blocks)[0]       # 正文归正文，不粘进标题
        # 关着的时候这行不是考点行，正文也就跟着落到别处 —— 开关的意义就在这儿，
        # 一本册子是「序号即考点」还是「名冒号值」得按册子定，不能一刀切。
        assert _titles(_parse(text, numbered=False)[0]) != ["南昌起义"]

    def test_序号先剥掉再找冒号(self):
        """「10. 基本路线：领导和团结…」里那个点不是名/值的分界。"""
        nodes, blocks = _parse("10. 基本路线：领导和团结全国各族人民，以经济建设为中心\n",
                               numbered=True)
        assert _titles(nodes) == ["基本路线"]
        assert "以经济建设为中心" in _md(blocks)[0]


class Test剪枝:
    def test_一句话就是全部内容的考点不许剪(self):
        """「明确 30 日的离婚冷静期」这类标题即内容的条目没有正文块，
        第一版剪枝把它们连同真空壳一起剪了 213 个。"""
        nodes = [{"_i": 0, "level": 1, "title": "书", "parent": None},
                 {"_i": 1, "level": 3, "title": "明确 30 日的离婚冷静期", "parent": 0},
                 {"_i": 2, "level": 3, "title": "（三）", "parent": 0}]
        kept, cut = IB.prune_empty(nodes, [])
        assert [n["title"] for n in kept] == ["书", "明确 30 日的离婚冷静期"]
        assert cut == 1


class Test表格垃圾列:
    def test_页边竖排切进表里的单字符列被掐掉(self):
        """`| 机构集体养育服务 | _ | 本 | 本 |` —— 后三列是页边竖排噪声。
        AI 校对救不了：结构闸门不许它删列，只能把垃圾原样抄回来。"""
        _nodes, blocks = _parse(
            "机构集体养育服务      将儿童集中安置在福利机构      本      、\n"
            "模式分析      家庭安置永远是最高追求      本      _\n")
        tbl = _md(blocks, "table")[0]
        rows = [r for r in tbl.splitlines() if not set(r) <= set("|- ")]
        assert all(len(r.strip("|").split("|")) == 2 for r in rows), tbl

    def test_列里只要有一个格是个词就留着(self):
        _nodes, blocks = _parse(
            "核心家庭      一对夫妇及其未婚子女      常见\n"
            "丁克家庭      夫妇双方都有收入而没有孩子      少\n")
        tbl = _md(blocks, "table")[0]
        assert "常见" in tbl                              # 这一列有实词，不能当噪声掐掉
