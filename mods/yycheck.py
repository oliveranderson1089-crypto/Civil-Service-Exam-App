"""应用文格式检查器：既是**出稿的闸门**，也是**错例素材的产线**。

设计文档里那条纪律——「每条检查失败即产出一条错例，闸门和素材生产是同一件事」。
所以这里的每个检查器返回的不是布尔值，而是一条**成对的错例**
（错在哪 / 该怎么写 / 为什么扣分 / 出在哪个部件），可以直接进 yy_items。

判据来自哪里，逐条标注：
  · 分条方式    —— 36 份真题参考答案实测：汉字序号 21 次占压倒多数；
                   用「一是…二是…」的只有 1 场考试，而它是**讲话稿**（口语文种，合法）
  · 落款单独成行 —— 真题答案里落款和日期各自成行，混在正文里是格式错
  · 语气合身份   —— 面向群众的文种（倡议书/公开信/宣传稿）靠感染力，
                   用「请遵照执行」这种命令口气是错的
  · 必需部件缺失 —— parts_of() 里标 required 的那些

`has_*` 这几个字面探测器是**这个项目里唯一一份**——docs/data/yy_parts_from_real.py
从这里 import 过去。norm_part 那次写了两份实现、改一边忘一边，不能再犯。
"""
import re

from mods.gongwen import GW_MAP, GW_SPOKEN, parts_of

# ---------- 字面探测器（只认字面特征，不猜语义） ----------


def lines(text):
    return [x.strip() for x in re.split(r"[\n\r]+", text or "") if x.strip()]


def has_title(text):
    """标题：开头有一行短句、不带句末标点、不是称谓也不是分条项。"""
    for ln in lines(text)[:2]:
        s = re.sub(r"\s", "", ln)
        if not (4 <= len(s) <= 34):
            continue
        if s.endswith(("：", ":", "。", "；", "!", "！", "?", "？")):
            continue
        if re.match(r"^[一二三四五六（(]", s):
            continue
        return True
    return False


_CALL = re.compile(r"^(尊敬的|各位|全体|亲爱的|同志们|市民朋友|广大|亲爱|"
                   r"[^\s，。]{0,10}(?:朋友们|同志|居民|市民|网友|读者|同学|家长))"
                   r"[^\n]{0,16}[：:]$")
_TO = re.compile(r"^(各|全体|[^\s，。]{2,18}(?:局|厅|委|办|部|处|科|乡|镇|街道|"
                 r"县|市|区|政府|单位|公司|学校))[^\n]{0,12}[：:]$")
_SIGN = re.compile(r"(××|XX|ＸＸ|某某|[^\s，。]{2,16}(?:局|厅|委|办|部|处|科|"
                   r"政府|中心|办公室|委员会|居委会|村委会|工会|协会|"
                   r"工作组|调研组|课题组|指挥部|专班))$")
_DATE = re.compile(r"(\d{4}|××××|XXXX|ＸＸＸＸ)\s*年\s*(\d{1,2}|××|XX)\s*月"
                   r"\s*(\d{1,2}|××|XX)\s*日$")


def has_call(text):
    """称谓：单独一行、冒号结尾、指向人。"""
    return any(_CALL.match(re.sub(r"\s", "", ln)) for ln in lines(text)[:4])


def has_to(text):
    """主送机关：机关名 + 冒号。和称谓的区别是指向单位不指向人。"""
    for ln in lines(text)[:4]:
        s = re.sub(r"\s", "", ln)
        if not _CALL.match(s) and _TO.match(s):
            return True
    return False


def has_sign(text):
    return any(_SIGN.search(re.sub(r"\s", "", ln)) for ln in lines(text)[-3:])


def has_date(text):
    return any(_DATE.search(re.sub(r"\s", "", ln)) for ln in lines(text)[-3:])


def fentiao_kinds(text):
    """用了哪些分条方式。返回列表，可能多种并存。"""
    s = re.sub(r"\s", "", text or "")
    out = []
    if len(re.findall(r"[一二三四五六]、", s)) >= 2:
        out.append("汉字序号")
    if len(re.findall(r"[（(][一二三四五六][)）]", s)) >= 2:
        out.append("括号序号")
    if len(re.findall(r"[1-9][、.．]", s)) >= 2:
        out.append("阿拉伯序号")
    if "一是" in s and "二是" in s:
        out.append("一是二是")
    return out or ["不分条"]


# 部件 → 探测器。只有能靠字面判的才进来；
# 「主体·举措」这类语义部件判不了，**不猜**（猜错会误报成错例，比不报更糟）
PART_PROBES = {
    "标题": has_title,
    "称谓": has_call,
    "主送机关": has_to,
    "落款": has_sign,
}


# ---------- 检查器：每条返回一对错例 ----------

def _pair(kind, bad, good, why, part=""):
    return {"check": kind, "bad": bad, "good": good, "why": why, "part": part}


_XSHI_RUN = re.compile(r"([^\n。；;]{0,24})([一二三四五六])是([^\n。；]{0,30})")


def check_fentiao(content, doctype=None):
    """「一是…二是…」当分条骨架。口语文种豁免——真题里讲话稿就是这么写的。"""
    if doctype in GW_SPOKEN:
        return []
    s = content or ""
    if "一是" not in s or "二是" not in s:
        return []
    out = []
    for m in _XSHI_RUN.finditer(s):
        if m.group(2) not in ("一", "二"):
            continue
        bad = m.group(0).strip()
        good = re.sub(r"([一二三四五六])是", r"\1、", bad, count=1)
        out.append(_pair(
            "分条方式", bad, good,
            "「一是…二是…」是口头汇报的说法，写进书面公文正文要扣分；"
            "分条要用「一、二、三、」这类规范序号（36 份真题参考答案里，"
            "只有讲话稿这类口语文种用它）", "主体·举措"))
        if len(out) >= 3:            # 一篇取前 3 条就够，不刷屏
            break
    return out


_ORDER_CMD = re.compile(r"请\s*(?:各[^\s，。]{0,6})?遵照执行|务必(?:严格)?(?:遵照|执行|落实)|"
                        r"请(?:予|以)?(?:遵照|照办)|限期(?:整改|办结)|一律(?:严禁|禁止)")
# 面向群众、靠感染力的文种。判据：这些文种的真题答案通篇没有命令式收尾
_SOFT_DOCTYPES = {"倡议书", "公开信", "宣传稿", "短评", "编者按", "发布词", "展板文稿"}


def check_tone(content, doctype=None):
    """面向群众的文种用命令口气。"""
    if doctype not in _SOFT_DOCTYPES:
        return []
    out = []
    for m in _ORDER_CMD.finditer(content or ""):
        out.append(_pair(
            "语气合身份", m.group(0),
            "让我们携手…／欢迎广大市民…／期待您的参与",
            "%s 是写给群众看的，靠感染力不靠命令。「%s」这种下行文的命令口气"
            "用在这儿，是语言不得体，扣「得体」那一项" % (doctype, m.group(0)),
            "结尾·号召"))
    return out[:2]


def check_sign_inline(content, doctype=None):
    """落款和正文挤在同一行。真题答案里落款、日期各自单独成行。"""
    ls = lines(content)
    out = []
    for ln in ls[-3:]:
        s = re.sub(r"\s", "", ln)
        if len(s) < 12:
            continue
        m = _SIGN.search(s) or _DATE.search(s)
        if m and not (_SIGN.match(s) or _DATE.match(s)):
            out.append(_pair(
                "落款成行", "把落款和正文写在同一行：%s" % ln.strip(),
                "正文写完换行，署名机关单独一行、日期再单独一行放最后",
                "落款的署名机关和日期要**各自单独成行、放在全文最后**，"
                "和正文挤在一行是格式错", "落款"))
            break
    return out


# 「标题：xxx」这种把部件名当标签写在正文里的写法。
# 判据是实测出来的：自产范文 10/71 篇这么写，**真题参考答案 0/45 份**这么写。
# 所以它是自产范文特有的毛病，是一条真错例。
_LABEL_PRE = re.compile(r"^\s*(标题|称谓|正文|落款|日期|主送机关|开场|结尾|附件)\s*[：:]",
                        re.M)


def has_label_prefix(content):
    return len(_LABEL_PRE.findall(content or "")) >= 2


def check_label_prefix(content, doctype=None):
    """把部件名当标签写进正文（「标题：xxx」「落款：xxx」）。"""
    hits = _LABEL_PRE.findall(content or "")
    if len(hits) < 2:
        return []
    bad = "、".join("%s：" % h for h in dict.fromkeys(hits))
    return [_pair(
        "标签前缀", "把「%s」这些部件名当标签写进答卷" % bad.rstrip("、"),
        "直接写内容，不写部件名：标题单独一行居中，称谓另起一行以冒号结尾，"
        "落款和日期各自成行放最后",
        "「标题：」「落款：」这类部件名不能写进答卷——那是给自己看的骨架标记。"
        "45 份真题参考答案里一份都没这么写过；写了等于把提纲当成文交上去", "标题")]


def check_missing_parts(content, doctype=None):
    """缺必需部件。只查有字面探测器的那几个，语义部件不猜。

    两道前置闸，都是实测踩出来的：

    ① **带标签前缀的直接跳过**。那种写法下部件其实是在的（「称谓：同志们」），
       只是格式不对，已经由 check_label_prefix 报了。在这儿再报一次「缺称谓」
       就是误报——把正确内容当成缺失，比不报更糟（第一版这么误报了 7 条）。

    ② **只查 parts_src='real' 的文种**。这个检查器的准确性完全取决于 `parts`，
       而 15 个文种族里只有 8 个的 parts 有真题答案支撑（n≥3），其余是先验设定。
       拿先验去生产「错例」，等于把猜测当成标准答案教给用户 —— 这是整个方案里
       反复强调不能做的事。样本攒够了再放开。
    """
    if has_label_prefix(content):
        return []
    if (GW_MAP.get(doctype) or {}).get("parts_src") != "real":
        return []
    out = []
    for part, req in parts_of(doctype):
        if not req:
            continue
        probe = PART_PROBES.get(part.split("·")[0])
        if probe and not probe(content or ""):
            out.append(_pair(
                "缺部件", "写%s时省掉「%s」这一块" % (doctype or "这个文种", part),
                "写%s必须写上「%s」" % (doctype or "这个文种", part),
                "%s 的「%s」是必需部件，缺整块要扣格式分" % (doctype or "这个文种", part),
                part))
    return out


CHECKS = (check_fentiao, check_tone, check_sign_inline, check_label_prefix,
          check_missing_parts)


def check_all(content, doctype=None):
    """跑全部检查器 → [错例对]。空列表 = 这篇格式上没抓到问题。"""
    out = []
    for fn in CHECKS:
        try:
            out.extend(fn(content, doctype))
        except Exception:            # 单个检查器出错不能拖垮出稿
            continue
    return out
