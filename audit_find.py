#!/usr/bin/env python3
"""小题训练找点质量的体检表 —— 采分点到底铺没铺开全材料。

为什么需要它：小题训练靠「采分点 ↔ 材料原文逐字依据」判找漏找错，判定精度是够的，
可**选点**这一步有系统性偏置 —— 采分点会挤在材料前段、挤在句式规整好照抄的地方。
2026 国考副省级第 1 题（H 市城市用光）是个现成的反例：23 句材料标了 5 个点（数量对），
全落在句 3~9；句 13~17 智慧照明整段、句 22 长效管理机制整段一个点没标，而这两块
恰好是真题标准答案的第 4、5 点。练这道题的人会以为自己找全了。

这种偏差不报错、不崩，只会让人练歪。所以要有个能反复跑的数字：
    max_gap  —— 最长连续多少句没有采分点（跟块大小无关，最客观）
    coverage —— 有采分点的「句块」占比
口径一律从 mods/find.py 的 _find_coverage 取，别在这儿另立一套：审计脚本存在的
全部意义就是当那个唯一可信的数字，它自己和线上出题时跑的闸门不一致就彻底没用了。

用法：
    .venv/bin/python3 audit_find.py                  # 基线体检，只量不调 AI（免费、秒出）
    .venv/bin/python3 audit_find.py --show 21        # 摊开某道题：逐句列出哪句有点哪句没有
    .venv/bin/python3 audit_find.py --check          # 有不达标的题就退出码 1（改完自查用）
    .venv/bin/python3 audit_find.py --rerun 21 22    # 用新流程重跑这几道，新旧对比，**不写库**
    .venv/bin/python3 audit_find.py --rerun all --apply   # 对比后把新采分点写回去（重标）

--rerun 会真调 AI（每道题 2~3 次 pro 调用），慢且花钱；先拿一两道试，看对比表满意了
再 --apply。--apply 会顺手把旧采分点备份进 find_papers.points_old。
"""
import argparse
import json
import sqlite3
import sys

from mods.find import (_FIND_COV_MIN, _FIND_GAP_MAX, _ZW_CATS, _find_coverage,
                       _find_needs_more, _find_points, _find_sents,
                       _q_scoped_material, _split_materials)

DB = "app.db"


def load_sl(con, ids=None):
    """真题批改那边的题（shenlun_questions），主要为了测**大作文** —— 它只存在于那张表。

    材料要按「一题一则」切过再量：shenlun_papers.material 是整份卷子的给定资料，
    不切的话一道题会拿 291 句去标，量出来的数字没有意义。
    """
    sql = ("SELECT q.id, q.seq, q.qtype, q.type_name, q.full, q.stem, q.points, "
           "q.word_min, q.word_max, p.material, p.title source "
           "FROM shenlun_questions q JOIN shenlun_papers p ON p.id=q.paper_id")
    args = []
    if ids:
        sql += " WHERE q.id IN (%s)" % ",".join("?" * len(ids))
        args = ids
    out = []
    for r in con.execute(sql + " ORDER BY q.id", args):
        d = dict(r)
        d["material"] = _q_scoped_material(r["stem"] or "", _split_materials(r["material"] or ""),
                                           r["material"] or "")
        try:
            pts = json.loads(r["points"] or "[]")
        except Exception:
            pts = []
        out.append({"row": d, "sents": _find_sents(d["material"]), "points": pts, "sl": True})
    return out


def load(con, ids=None):
    """把题目连同它的采分点、切好的句子一起取出来。"""
    # word_min/word_max/reference 是 --backfill-ref 要用的（参考答案按题目字数区间收口）
    sql = ("SELECT id, qtype, type_name, full, source, stem, material, points, "
           "word_min, word_max, reference, near FROM find_papers")
    args = []
    if ids:
        sql += " WHERE id IN (%s)" % ",".join("?" * len(ids))
        args = ids
    out = []
    for r in con.execute(sql + " ORDER BY id", args):
        try:
            pts = json.loads(r["points"] or "[]")
        except Exception:
            pts = []
        out.append({"row": r, "sents": _find_sents(r["material"] or ""), "points": pts})
    return out


def table(items):
    """体检表：一题一行，不达标的打 ✗。返回不达标的题数。"""
    print("%-5s %-8s %-4s %-5s %-6s %-8s %-9s %s" %
          ("id", "题型", "满分", "句数", "点数", "coverage", "max_gap", "来源"))
    print("-" * 92)
    bad = []
    for it in items:
        r, pts = it["row"], it["points"]
        cov = _find_coverage(it["sents"], pts)
        ng = _find_needs_more(cov)
        if ng:
            bad.append((r["id"], cov))
        gap = "%d" % cov["max_gap"]
        if cov["gap_range"]:
            gap += " (句%d-%d)" % cov["gap_range"]
        print("%-5s %-8s %-4s %-5s %-6s %-8s %-9s %s%s" %
              (r["id"], (r["type_name"] or "")[:4], r["full"], cov["n_sents"], len(pts),
               "%d/%d" % (cov["cov_blocks"], cov["n_blocks"]), gap,
               (r["source"] or "")[:26], "  ✗" if ng else ""))
    print("-" * 92)
    n = len(items)
    print("共 %d 道，%d 道值得看一眼（判据：max_gap ≥ %d 或 coverage < %.0f%%）"
          % (n, len(bad), _FIND_GAP_MAX, _FIND_COV_MIN * 100))
    # ✗ 是「去看看」，不是「一定错了」：材料里**合法地**存在整块无采分点的情况 ——
    # 实测一道题的句 28~39 讲的是 J 省 H 市，而题干只问 S 省 T 市和 L 省 Y 市，
    # 那一整块是出题时掺的越界干扰材料，扫描跳过它、补点返回空都是对的。
    # 所以这张表是筛查用的：先 --show 看看那段材料到底该不该有点，再决定要不要 --rerun。
    print("（✗ = 有整块材料没落上采分点，先 --show <id> 看看那段该不该有点，别直接当错）")
    if bad:
        # 平均值会把问题摊平，这里要的是「最差的几道有多差」
        worst = sorted(bad, key=lambda x: -x[1]["max_gap"])[:5]
        print("最漏的几道：" + "、".join(
            "id=%d 连续 %d 句无点" % (i, c["max_gap"]) for i, c in worst))
    return len(bad)


def show(items):
    """摊开一道题：逐句标出有没有采分点。看「漏在哪儿」比看数字管用。"""
    for it in items:
        r, pts = it["row"], it["points"]
        cov = _find_coverage(it["sents"], pts)
        print("\n[id=%d] %s · %d 分 · %s" % (r["id"], r["type_name"], r["full"], r["source"]))
        print("题干：%s" % (r["stem"] or "").replace("\n", " ")[:90])
        print("coverage %d/%d · max_gap %d%s\n" %
              (cov["cov_blocks"], cov["n_blocks"], cov["max_gap"],
               (" (句%d-%d)" % cov["gap_range"]) if cov["gap_range"] else ""))
        owner = {}
        for k, p in enumerate(pts):
            for i in p.get("sents") or []:
                owner[i] = k
        for i, s in enumerate(it["sents"]):
            if s.get("head"):
                print("   -- %s" % s["t"][:72])
                continue
            k = owner.get(i)
            print("%s%2d %s" % ("★" if k is not None else "   ", i, s["t"][:72]))
            if k is not None:
                print("      └ [%.3g 分] %s" % (pts[k].get("score") or 0, pts[k].get("point") or ""))
        print("\n采分点清单：")
        for k, p in enumerate(pts, 1):
            print("  %d. [%.3g 分] %s  ← 句%s" %
                  (k, p.get("score") or 0, p.get("point") or "", p.get("sents")))


def repeat(con, items, n):
    """同一道题连出 n 次，量「维度选偏」——位置指标抓不到的那一类漏。

    实测过一次：coverage 4/4、max_gap 4，看着完美，实际把「智慧管控」拆成了两个点、
    整个「因地制宜」维度（句 9~12）一个点没有。max_gap 抓不住它 —— 23 句材料配 5 个点，
    平均间距就有 4.6 句，空 4 句根本不报警。**位置指标原理上就看不见「这块给了点、但维度选偏」。**

    所以换个看法：连出 n 次，统计每一句被采分点覆盖的**频率**。
      · n/n 覆盖 —— 稳定命中，这是材料里公认的得分句
      · 0/n 覆盖 —— 稳定不中，多半是干扰信息（正常）
      · 中间的 —— **摇摆句**，说明这个维度时有时无，正是选偏的指纹
    摇摆句越多，说明这道题的采分点越不可复现；同一个人练两遍会被判出两套标准。"""
    stats = []
    for it in items:
        r, sents = it["row"], it["sents"]
        idx = [i for i, s in enumerate(sents) if not s.get("head")]
        freq = {i: 0 for i in idx}
        runs, ok = [], 0
        print("\n[id=%d] %s · %s —— 连出 %d 次" % (r["id"], r["type_name"], (r["source"] or "")[:30], n))
        for k in range(n):
            pts, info, err = _find_points(r["qtype"], r["stem"] or "", r["material"] or "", r["full"])
            if err:
                print("  第%d次 ✗ %s" % (k + 1, err[0].get("error"))); continue
            ok += 1
            runs.append(pts)
            hit = {i for p in pts for i in p["sents"]}
            for i in hit:
                if i in freq:
                    freq[i] += 1
            c = info["cov"]
            print("  第%d次：%d 点 · coverage %d/%d · max_gap %d"
                  % (k + 1, len(pts), c["cov_blocks"], c["n_blocks"], c["max_gap"]))
        if ok < 2:
            print("  成功次数不足，测不出稳定性")
            stats.append({"row": r, "ok": ok, "n": n})
            continue
        always = [i for i in idx if freq[i] == ok]
        never = [i for i in idx if freq[i] == 0]
        waver = [i for i in idx if 0 < freq[i] < ok]
        pct = 100.0 * len(waver) / len(idx)
        print("  ── 稳定命中 %d 句 · 稳定不中 %d 句 · **摇摆 %d 句**（占可勾画句 %.0f%%）"
              % (len(always), len(never), len(waver), pct))
        for i in waver:
            print("     %d/%d  [句%d] %s" % (freq[i], ok, i, sents[i]["t"][:56]))
        st = {"row": r, "ok": ok, "n": n, "waver": pct, "n_sents": len(idx),
              "pts": [len(p) for p in runs],
              "gap": [_find_coverage(sents, p)["max_gap"] for p in runs]}
        # 大作文另看一件事：**每一轮是否都找到【立意】**。它只会有一两条、最容易被
        # 一堆论据淹掉，可它恰恰是总论点的根 —— 找不到它整篇就跑题。摇摆句占比看不出这个。
        if r["qtype"] == "zuowen":
            st["cats"] = [{k: sum(1 for p in pts if (p["point"] or "").startswith(k))
                           for k in _ZW_CATS} for pts in runs]
            print("  ── 三类齐全度：" + " | ".join(
                "第%d次 %s" % (k + 1, "·".join("%s%d" % (c.strip("【】"), v)
                                              for c, v in cs.items()))
                for k, cs in enumerate(st["cats"])))
            miss = [k + 1 for k, cs in enumerate(st["cats"]) if not cs.get("【立意】")]
            if miss:
                print("     ⚠ 第 %s 次没找到【立意】—— 总论点没有根，整篇会跑题"
                      % "、".join(map(str, miss)))
        stats.append(st)
        # 逐轮列出采分点，人眼一扫就能看出哪个维度这轮有、那轮没有
        for k, pts in enumerate(runs, 1):
            print("  第%d次采分点：" % k)
            for p in pts:
                print("     · %s ← 句%s" % (p["point"], p["sents"]))
    return stats


def _summary(stats):
    """一张总表。单题的细节前面已经打过了，这里只留能横向比的数字。"""
    print("\n" + "=" * 96)
    print("稳定性基线（摇摆句 = 有几轮标中、有几轮没标中的句子，占比越高说明采分点越不可复现）")
    print("%-5s %-10s %-5s %-9s %-9s %-8s %s" %
          ("id", "题型", "句数", "点数(轮次)", "max_gap", "摇摆句", "备注"))
    print("-" * 96)
    for s in stats:
        r = s["row"]
        if "waver" not in s:
            print("%-5s %-10s %-5s %-9s %-9s %-8s %s"
                  % (r["id"], (r["type_name"] or "")[:5], "-", "-", "-", "-",
                     "✗ %d/%d 轮失败，测不出" % (s["n"] - s["ok"], s["n"])))
            continue
        note = ""
        if s.get("cats"):
            bad = sum(1 for c in s["cats"] if not c.get("【立意】"))
            note = "立意齐全 %d/%d 轮" % (len(s["cats"]) - bad, len(s["cats"]))
        flag = "  ⚠" if s["waver"] >= 20 else ""
        print("%-5s %-10s %-5s %-9s %-9s %-8s %s%s"
              % (r["id"], (r["type_name"] or "")[:5], s["n_sents"],
                 "%d~%d" % (min(s["pts"]), max(s["pts"])),
                 "%d~%d" % (min(s["gap"]), max(s["gap"])),
                 "%.0f%%" % s["waver"], note, flag))
    print("-" * 96)
    good = [s for s in stats if "waver" in s]
    if good:
        print("摇摆句占比：最低 %.0f%% · 最高 %.0f%% · 中位 %.0f%%"
              % (min(s["waver"] for s in good), max(s["waver"] for s in good),
                 sorted(s["waver"] for s in good)[len(good) // 2]))
    print("（⚠ = 摇摆句 ≥20%，这道题的采分点值得再看一眼；大作文另看「立意齐全几轮」）")


def _fmt(cov, n_pts):
    return "点%-2d coverage %-5s max_gap %-2d%s" % (
        n_pts, "%d/%d" % (cov["cov_blocks"], cov["n_blocks"]), cov["max_gap"],
        (" (句%d-%d)" % cov["gap_range"]) if cov["gap_range"] else "")


def rerun(con, items, apply_=False):
    """用新流程重跑，逐题打新旧对比。--apply 才写库（旧的备份进 points_old）。"""
    if apply_:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(find_papers)")}
        if "points_old" not in cols:
            con.execute("ALTER TABLE find_papers ADD COLUMN points_old TEXT")
            con.commit()
    won = lost = same = failed = 0
    for it in items:
        r, old, sents = it["row"], it["points"], it["sents"]
        cov_o = _find_coverage(sents, old)
        print("\n[id=%d] %s · %d 分 · %s" % (r["id"], r["type_name"], r["full"], (r["source"] or "")[:40]))
        print("  旧  " + _fmt(cov_o, len(old)))
        pts, info, err = _find_points(r["qtype"], r["stem"] or "", r["material"] or "", r["full"])
        if err:
            failed += 1
            print("  新  ✗ 失败：%s" % (err[0].get("error") if isinstance(err, tuple) else err))
            continue
        cov_n = info["cov"]
        print("  新  " + _fmt(cov_n, len(pts)) +
              "   （扫出 %d + 补 %d，丢弃 %d）" % (info["n_scan"], info["n_filled"], info["dropped"]))
        # 判优劣只看 max_gap：coverage 会被块数抹平，max_gap 才直接对应「整段材料被漏掉」
        if cov_n["max_gap"] < cov_o["max_gap"]:
            won += 1; print("  → 改善：最长空白带 %d → %d 句" % (cov_o["max_gap"], cov_n["max_gap"]))
        elif cov_n["max_gap"] > cov_o["max_gap"]:
            lost += 1; print("  → ⚠ 变差：%d → %d 句" % (cov_o["max_gap"], cov_n["max_gap"]))
        else:
            same += 1; print("  → 持平")
        # 逐条把「采分点」和「它声称的原文」并排printed出来 —— 覆盖率正常但锚错位的 bug
        # 只有这样对读才看得见（分数/点数/coverage 全都自洽，evidence 也是从错句子里取的）
        for k, p in enumerate(pts, 1):
            print("     %d. [%.3g 分] %s  ← 句%s" % (k, p["score"], p["point"], p["sents"]))
            print("        原文：%s" % (p.get("evidence") or "")[:70])
        if apply_:
            # near 必须跟着一起写：它是「扫描认过、但没能独立成点」的句子，判定时用来
            # 把「沾边」和「真找错」分开。漏写过一次 —— 重标跑了 22 分钟，points 换了
            # 一遍（还抽差了几道），near 却全是空，等于白跑。
            con.execute("UPDATE find_papers SET points_old=COALESCE(points_old,points), points=?, "
                        "near=? WHERE id=?",
                        (json.dumps(pts, ensure_ascii=False),
                         json.dumps(info["near"]), r["id"]))
            con.commit()
            print("  ✓ 已写回（旧采分点存进 points_old）")
    print("\n%s\n改善 %d · 持平 %d · 变差 %d · 失败 %d" % ("=" * 60, won, same, lost, failed))
    return lost + failed


def backfill_near(con, items, force=False):
    """给存量题目补 near，**完全不动已有的采分点**。

    为什么要单独一条路径、而不是用 `--rerun --apply` 顺带补：
    重标是**重新抽一次签**。`--baseline` 量出来采分点的摇摆率有 31~53%，重标一道
    原本标得不错的题，很可能抽到更差的一版 —— 实测 11 道重标下来「改善 3 · 持平 3 ·
    变差 4」，为了拿 near 把好签也重抽了，得不偿失。

    而 near 根本不需要重新定点：
        near = 扫描扫出的候选句 − 现有采分点已覆盖的句子
    扫描是独立的一步，跟最终选了哪几个点无关。所以只跑扫描（外加覆盖不足时的补点），
    拿候选算 near，采分点原样不动。**一道题一次 AI 调用**，比重标省一半以上。
    """
    from mods.find import (_PT_TYPES, _find_coverage, _find_fill, _find_needs_more,
                           _find_norm, _find_scan)
    done = skipped = failed = 0
    for it in items:
        r, pts = it["row"], it["points"]
        if not pts or r["qtype"] not in _PT_TYPES:
            print("[id=%d] 没有采分点，跳过" % r["id"]); skipped += 1; continue
        if (r["near"] or "").strip() and not force:
            print("[id=%d] 已有 near，跳过" % r["id"]); skipped += 1; continue
        sents = it["sents"]
        name = _PT_TYPES[r["qtype"]][0]
        cands, err = _find_scan(name, r["stem"] or "", sents, r["qtype"])
        if err:
            print("[id=%d] ✗ 扫描失败：%s" % (r["id"], err[0].get("error"))); failed += 1; continue
        cands = _find_norm(sents, cands)
        cov = _find_coverage(sents, [{"sents": c["sents"]} for c in cands])
        if _find_needs_more(cov):          # 空白处再补一轮，让 near 也铺得开
            cands += _find_norm(sents, _find_fill(name, r["stem"] or "", sents, r["qtype"],
                                                  cov["blanks"], cands), exist=cands)
        in_pts = {i for p in pts for i in (p.get("sents") or [])}
        near = sorted({i for c in cands for i in c["sents"]} - in_pts)
        con.execute("UPDATE find_papers SET near=? WHERE id=?", (json.dumps(near), r["id"]))
        con.commit()
        print("[id=%d] ✓ %-6s 采分点 %d 个（未改动）· 沾边 %d 句"
              % (r["id"], r["type_name"][:4], len(pts), len(near)))
        done += 1
    print("\n补齐 %d · 跳过 %d · 失败 %d" % (done, skipped, failed))
    return failed


def backfill_ref(con, items, force=False):
    """给存量题目补参考答案（由它们自己的采分点拼装）。已有的不重生成，除非 --force。

    参考答案是这一轮新加的，出题时才会顺带生成 —— 之前出的题一律没有。
    补一次就存进 find_papers.reference，之后批改和回看都直接取，不再调 AI。"""
    from mods.find import _find_doctype, _find_reference
    done = skipped = failed = 0
    for it in items:
        r, pts = it["row"], it["points"]
        if not pts:
            print("[id=%d] 没有采分点，跳过" % r["id"]); skipped += 1; continue
        if (r["reference"] or "").strip() and not force:
            print("[id=%d] 已有参考答案（%d 字），跳过" % (r["id"], len(r["reference"]))); skipped += 1; continue
        ref = _find_reference(r["qtype"], r["type_name"], r["stem"] or "", pts,
                              r["word_min"] or 150, r["word_max"] or 300, _find_doctype(r))
        if not ref:
            print("[id=%d] ✗ 没生成出来" % r["id"]); failed += 1; continue
        con.execute("UPDATE find_papers SET reference=? WHERE id=?", (ref, r["id"]))
        con.commit()
        print("[id=%d] ✓ %s · %d 字\n     %s…" % (r["id"], r["type_name"], len(ref), ref[:90]))
        done += 1
    print("\n补齐 %d · 跳过 %d · 失败 %d" % (done, skipped, failed))
    return failed


def pick_baseline(con):
    """各题型各挑一道，凑一份能横向比的样本。

    挑的规则：**优先真题**（AI 命制的材料自带出题痕迹，量出来的稳定性偏乐观），
    每个题型只取一道，再从真题批改那边补上**大作文** —— 它只存在于 shenlun_questions，
    而且是唯一走「备料」口径的题型，最该单独盯。
    """
    items, seen = [], set()
    rows = list(con.execute(
        "SELECT id, qtype FROM find_papers ORDER BY (source LIKE '真题%') DESC, id"))
    for r in rows:
        if r["qtype"] not in seen:
            seen.add(r["qtype"]); items.append(("find", r["id"]))
    zw = con.execute("SELECT id FROM shenlun_questions WHERE qtype='zuowen' "
                     "ORDER BY id LIMIT 1").fetchone()
    if zw:
        items.append(("sl", zw["id"]))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--show", nargs="*", type=int, metavar="ID",
                    help="摊开这几道题逐句看（不给 id 就摊开所有不达标的）")
    ap.add_argument("--rerun", nargs="+", metavar="ID|all",
                    help="用新流程重跑并对比（真调 AI）。'all' = 全部不达标的题")
    ap.add_argument("--apply", action="store_true", help="配合 --rerun：把新采分点写回数据库")
    ap.add_argument("--backfill-ref", nargs="*", type=int, metavar="ID",
                    help="给存量题目补参考答案（不给 id 就全部）。会写库")
    ap.add_argument("--backfill-near", nargs="*", type=int, metavar="ID",
                    help="给存量题目补 near（沾边句），**不动采分点**。不给 id 就全部")
    ap.add_argument("--force", action="store_true",
                    help="配合 --backfill-ref / --backfill-near：已有的也重做")
    ap.add_argument("--repeat", nargs=2, metavar=("ID", "N"),
                    help="同一道题连出 N 次，量维度选偏（摇摆句占比）。真调 AI，不写库")
    ap.add_argument("--sl", action="store_true",
                    help="配合 --repeat：ID 指的是 shenlun_questions（真题批改，大作文在这儿）")
    ap.add_argument("--baseline", type=int, metavar="N",
                    help="各题型各挑一道（含大作文），每道连出 N 次，打一张稳定性基线总表")
    ap.add_argument("--check", action="store_true", help="有不达标的题就退出码 1")
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row

    if a.baseline:
        stats = []
        for kind, qid in pick_baseline(con):
            items = (load_sl(con, [qid]) if kind == "sl" else load(con, [qid]))
            stats += repeat(con, items, a.baseline)
        _summary(stats)
        return 0

    if a.repeat:
        loader = load_sl if a.sl else load
        _summary(repeat(con, loader(con, [int(a.repeat[0])]), int(a.repeat[1])))
        return 0

    if a.backfill_near is not None:
        return 1 if backfill_near(con, load(con, a.backfill_near or None), a.force) else 0

    if a.backfill_ref is not None:
        return 1 if backfill_ref(con, load(con, a.backfill_ref or None), a.force) else 0

    if a.rerun:
        if a.rerun == ["all"]:
            items = [x for x in load(con)
                     if _find_needs_more(_find_coverage(x["sents"], x["points"]))]
        else:
            items = load(con, [int(x) for x in a.rerun])
        if not items:
            print("没有要重跑的题"); return 0
        return 1 if rerun(con, items, a.apply) else 0

    if a.show is not None:
        items = load(con, a.show or None)
        if not a.show:                      # 不给 id：只摊开有问题的
            items = [x for x in items if _find_needs_more(_find_coverage(x["sents"], x["points"]))]
        show(items)
        return 0

    bad = table(load(con))
    return 1 if (a.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
