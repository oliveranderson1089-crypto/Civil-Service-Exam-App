"""kb 模块：文档引用的存储文件收集 _kb_assets_in_content。

kb 改动 1 次、零测试。文档由块的 JSON 数组构成，图片/附件块的 data.stored 是存储层的
文件名。删文档/删块时要靠这个清单去清存储，收漏了就留下孤儿文件、收错了可能误删。
"""
from mods.kb import _kb_assets_in_content


def test_收集块里的stored文件名():
    content = [
        {"type": "text", "data": {}},
        {"type": "image", "data": {"stored": "abc123.png"}},
        {"type": "file", "data": {"stored": "doc456.pdf"}},
    ]
    assert _kb_assets_in_content(content) == ["abc123.png", "doc456.pdf"]


def test_没有data或stored的块跳过_不炸():
    content = [
        {"type": "text"},                       # 没 data
        {"type": "image", "data": {}},          # 有 data 没 stored
        {"type": "file", "data": {"stored": "x.pdf"}},
    ]
    assert _kb_assets_in_content(content) == ["x.pdf"]


def test_空内容返回空列表():
    assert _kb_assets_in_content([]) == []
    assert _kb_assets_in_content(None) == []
