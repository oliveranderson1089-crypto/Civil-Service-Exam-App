"""files 模块：OCR 文本清洗 _clean_ocr / _strip_artifacts。

files 改动 1 次、零测试。用户拍照/上传的申论材料走 OCR，识别结果要洗两道：
_clean_ocr 去掉中文字之间被 OCR 误插的空格、压掉多余空行；_strip_artifacts 扔掉
页眉页脚/水印/答题卡行号这些不是正文的行。洗过头会吃正文，洗不干净材料里混进
「优路教育」「第3页」，两头都影响后面 AI 判题。
"""
from mods.files import _clean_ocr, _strip_artifacts


def test_clean_ocr_去掉中文间误插的空格():
    assert _clean_ocr("依法 治国") == "依法治国"
    assert _clean_ocr("建设 法治 政府") == "建设法治政府"
    # 标点与汉字之间的空格也去
    assert _clean_ocr("你好 ， 世界") == "你好，世界"


def test_clean_ocr_不动英文单词间的空格():
    # 英文之间的空格是真分词，不能去
    assert "hello world" in _clean_ocr("hello world")


def test_clean_ocr_压掉三行以上空行为两行():
    assert _clean_ocr("第一段\n\n\n\n第二段") == "第一段\n\n第二段"


def test_strip_artifacts_扔掉水印和页码行():
    text = "正文第一句。\n优路教育\n正文第二句。\n第 3 页 · 共 10 页\n扫码关注公众号"
    out = _strip_artifacts(text)
    assert "正文第一句。" in out
    assert "正文第二句。" in out
    assert "优路教育" not in out, "水印没洗掉，会混进材料喂给 AI"
    assert "第 3 页" not in out, "页码行没洗掉"
    assert "扫码" not in out


def test_strip_artifacts_扔掉答题卡行号():
    # 答题卡行号：100 200 300 …
    assert _strip_artifacts("正文。\n100 200 300 400\n继续。") == "正文。\n继续。"


def test_strip_artifacts_保留正文和空行结构():
    text = "第一段。\n\n第二段。"
    assert _strip_artifacts(text) == text, "把正文或段落空行也洗掉了"


def test_strip_artifacts_空输入不炸():
    assert _strip_artifacts("") == ""
    assert _strip_artifacts(None) == ""
