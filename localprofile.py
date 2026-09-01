#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地考区的那几个字符串：县名、云盘根目录、本地题的判定词。

**为什么单独拿出来一个文件**：这个仓库是公开的，而这几个值合起来就能定位到具体
的人（在哪个县考、报的哪个岗、资料放在哪个目录）。所以源码里一个都不写死 ——
真值全部住在 `local_meta.json`（.gitignore 忽略，模板见 `local_meta.example.json`），
这里只留一套中性缺省，让**没有那份文件的人也能把仓库跑起来**，不至于一 import 就炸。

缺省值是能跑但不匹配任何真实数据的：`drive_root()` 指向一个大概率不存在的目录，
入库脚本会如实报「云盘里没找到卷子」，而不是默默按错目录扫一遍。
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
META = os.environ.get("GONGKAO_LOCAL_META", os.path.join(BASE, "local_meta.json"))

REGION_FALLBACK = "本县"
DRIVE_ROOT_FALLBACK = "社区备考资料"

_cache = {"mtime": -1, "data": {}}


def meta():
    """读 local_meta.json。按 mtime 缓存；文件不在就返回 {}（不是报错）。"""
    try:
        mt = os.path.getmtime(META)
    except OSError:
        _cache["mtime"], _cache["data"] = -1, {}
        return {}
    if mt != _cache["mtime"]:
        try:
            with open(META, encoding="utf-8") as f:
                _cache["data"] = json.load(f)
        except (ValueError, OSError):
            _cache["data"] = {}
        _cache["mtime"] = mt
    return _cache["data"]


def region():
    """县名，用在题干和 sq_papers.region 上。"""
    return meta().get("region") or REGION_FALLBACK


def drive_root():
    """云盘里放社区备考资料的那个根目录名。入库脚本按它扫。"""
    return meta().get("drive_root") or DRIVE_ROOT_FALLBACK


def local_keywords():
    """判定「这是一道本地题」的词。

    县名、市名、下辖的镇名（从 posts 里取，公告有多少镇就有多少个）都算，
    外加一个通用的「县情」。**顺序无所谓，命中一个就算**。
    """
    m = meta()
    ks = []

    def add(v, tails):
        """带通名的地名，连它的短写一起收 —— 卷子标题里写的往往是短写：
           出现的是「XX 社区招聘」，不是「XX 县」。"""
        if not v:
            return
        ks.append(v)
        short = v.rstrip(tails)
        if short and short != v:
            ks.append(short)

    add(m.get("region"), "县市区旗")
    full = m.get("region_full") or ""
    add(full, "县市区旗")
    # 「X 市 Y 县」这种带上级市的，把市名也拆出来单收：有些出处（人事考试网之类）
    # 只出现市名、不带县名，不收就漏判。
    for sep in ("市", "州", "盟"):
        if sep in full:
            head = full.split(sep, 1)[0]
            if head:
                ks += [head + sep, head]
            break
    # 镇名**只收全称**，不脱「镇」字。脱了以后「公民镇」剩下「公民」、「太平镇」剩下
    # 「太平」—— 这一档在 QTYPE_RULES 里排最前，一道「公民的基本权利」会被判成本地题，
    # 直接污染考点分布。宁可漏判，不可错判。
    for p in m.get("posts") or []:
        t = p.get("town")
        if t:
            ks.append(t)
    ks.append("县情")
    return tuple(k for k in dict.fromkeys(ks) if len(k) >= 2)
