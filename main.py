import os
import json
import sys
from datetime import datetime
from itertools import combinations
from zodiac_analyzer import ZodiacPatternAnalyzer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ranges_config = {
    "0-9": (1, 9),
    "10-19": (10, 19),
    "20-29": (20, 29),
    "30-39": (30, 39),
    "40-49": (40, 49),
}


def get_f5_switch(argv):
    value = "off"
    for index, argument in enumerate(argv):
        if argument.startswith("--f5="):
            value = argument.split("=", 1)[1].lower()
        elif argument == "--f5" and index + 1 < len(argv):
            value = argv[index + 1].lower()
    if value not in {"on", "off"}:
        raise ValueError("F5开关只接受 --f5 on 或 --f5 off")
    return value == "on"


def main():
    try:
        f5_enabled = get_f5_switch(sys.argv[1:])
    except ValueError as exc:
        print(f"❌ {exc}")
        return
    # 只读取核验后的数据目录；原始 data 目录保留作审计备份。
    data_dir = "data_verified"
    all_merged_records = []

    print("==================================================")
    print("正在执行 跨年份全自动对齐与高阶特征量化清洗...")
    print("==================================================")

    print("开始加载历史开奖数据...")

    if not os.path.exists(data_dir):
        print(f"❌ 错误：找不到 【{data_dir}】 文件夹，请检查路径。")
        return

    if not os.path.isdir(data_dir):
        print(f"❌ 错误：{data_dir} 不是一个目录")
        return

    # 获取所有年份的 json 文件
    try:
        json_files = sorted(
            f
            for f in os.listdir(data_dir)
            if f.endswith(".json")
            and len(os.path.splitext(f)[0]) == 4
            and os.path.splitext(f)[0].isdigit()
        )
    except OSError as e:
        print(f"❌ 错误：读取数据目录失败：{e}")
        return

    if not json_files:
        print(f"❌ 错误：【{data_dir}】 文件夹内没有找到任何年份的 JSON 文件。")
        return

    # 一次性读取核验目录；分析器仍按每条开奖日期和正月初一动态映射生肖。
    # 旧流程会先手工解析一次、再由分析器解析一次，属于重复I/O。
    loader = ZodiacPatternAnalyzer()
    all_merged_records = loader.load_json_data(data_dir=data_dir)
    for file_name in json_files:
        print(f"📂 发现核验数据源: {file_name} | 动态生肖映射由统一加载器完成")

    if not all_merged_records:
        print("❌ 未成功加载任何年份的历史数据。")
        return

    # 跨年必须按开奖日期排序，不能只按每年都会重置的期号排序。
    all_merged_records.sort(key=ZodiacPatternAnalyzer._record_sort_key)

    print(f"成功加载 {len(all_merged_records)} 条历史记录。")

    latest_record = all_merged_records[-1]
    latest_date = latest_record.get("date")
    try:
        latest_zodiac_year = ZodiacPatternAnalyzer.get_zodiac_year_by_date(latest_date)
        final_base_zodiac = ZodiacPatternAnalyzer.get_base_zodiac_by_date(latest_date)
    except (TypeError, ValueError) as exc:
        print(f"❌ 无法根据最新开奖日期确定本命生肖：{exc}")
        return
    print(
        f"\n🚀 最新开奖 {latest_date} 属于 【{latest_zodiac_year} ({final_base_zodiac}年)】，历史各期按各自日期动态映射..."
    )

    try:
        analyzer = ZodiacPatternAnalyzer(base_zodiac=final_base_zodiac)
    except Exception as e:
        print(f"❌ 分析失败：{e}")
        return

    # 喂入合并后的大池子
    report = analyzer.compute_patterns(all_merged_records)
    top6_json_path = os.path.join(
        "结果",
        "top6_walk_forward_report_f5_on.json"
        if f5_enabled
        else "top6_walk_forward_report.json",
    )
    incremental_state_path = os.path.join(
        "结果", "top6_incremental_state.pkl"
    )
    expected_snapshot = {
        "record_count": len(all_merged_records),
        "first_date": all_merged_records[0]["date"],
        "latest_date": all_merged_records[-1]["date"],
        "latest_issue": all_merged_records[-1]["issue"],
        "latest_numbers": all_merged_records[-1]["numbers"],
    }
    top6_report = None
    cached_selection = None
    try:
        with open(top6_json_path, "r", encoding="utf-8") as f:
            cached_top6 = json.load(f)
        cached_selection = cached_top6
        if (
            cached_top6.get("model_version") == analyzer.TOP6_MODEL_VERSION
            and cached_top6.get("source_snapshot") == expected_snapshot
            and cached_top6.get("f5_enabled") is f5_enabled
            and cached_top6.get("incremental_cache_version") == 2
            and os.path.isfile(incremental_state_path)
        ):
            top6_report = cached_top6
            print("已复用与当前模型、当前数据完全一致的Top6严格回测缓存。")
    except (OSError, ValueError, TypeError):
        pass
    if top6_report is None:
        print("正在执行综合生肖Top6严格滚动/增量回测（2024–2026隔离验证）...")
        contexts, rows, _, incremental_meta = (
            analyzer.build_or_update_incremental_state(
                all_merged_records, incremental_state_path
            )
        )
        top6_report = analyzer.build_walk_forward_top6_report(
            all_merged_records,
            f5_enabled=f5_enabled,
            precomputed=(contexts, rows),
            cached_selection=cached_selection,
        )
        top6_report["incremental_update"] = incremental_meta
        top6_report["incremental_cache_version"] = 2
        print(
            "增量状态："
            f"{incremental_meta['mode']}；"
            f"新增 {incremental_meta['appended_records']} 期；"
            f"权重搜索复用={'是' if top6_report['incremental_selection_reused'] else '否'}。"
        )
    total_valid_p = report["total"] - 1

    # ========================================================================
    # 报告渲染输出逻辑
    # ========================================================================
    output = []
    output.append("==================================================")
    output.append("量化多组合精准特征深度挖潜报告 (V8-Joint)")
    output.append("==================================================")
    output.append(f"生成时间 ：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(
        f"有效盘口 ：跨年总融合数据 {report['total']} 期 (最大有效跨期基数: {total_valid_p} 期)\n"
    )

    output.append(
        "【查找器 1：当前期生肖数量与具体生肖交叉精细联动规律（双向红蓝截击）】"
    )

    # 📈 全局大底特征
    output.append(
        "  ① 全局大底特征：去重后生肖多样性数量下的临期生肖连庄/重复出现规律："
    )
    for div, stat in sorted(report["diversity_repeat_rule"].items()):
        output.append(
            f"    * 历史当期共开出 【{div}】 种不同生肖时 (跨年共现 {stat['total_occur']} 期) -> 下期[临期生肖重复出现]的总概率为: {stat['repeat_rate']:.1%}"
        )
        rep_counts = stat.get("repeat_counts", {})
        total_occur = stat["total_occur"] if stat["total_occur"] > 0 else 1
        for k in range(1, 8):
            k_count = rep_counts.get(k, 0)
            k_rate = k_count / total_occur
            output.append(
                f"      ---> 🛒 精确重复 【{k}】 个生肖的期数: {k_count} 期 | 实战发生率: {k_rate:.1%}"
            )

    output.append("\n  ② 微观单点交叉形态拦截库：")
    sorted_r1 = sorted(report["rule1"].items(), key=lambda x: x[0])
    for condition, data in sorted_r1:
        hot_str = ", ".join([f"【{z}】({pct:.1%})" for z, c, pct in data["hot"]])
        cold_str = ", ".join(
            [
                f"【{z}】(🔥0.0%)" if pct == 0 else f"【{z}】({pct:.1%})"
                for z, c, pct in data["cold"]
            ]
        )
        output.append(
            f"    * 特征形态 {condition} [{data['morphology']}] ：跨年共触发 {data['periods']} 期"
        )
        output.append(f"      ---> 🎯下期高频狙击: {hot_str if hot_str else '无'}")
        output.append(f"      ---> ❄️下期低频冰点: {cold_str if cold_str else '无'}")

    output.append("\n  ③ 高阶生肖对联合交叉联动库 (新加入双核心渗透) ：")
    sorted_r1_pairs = sorted(report["rule1_pairs"].items(), key=lambda x: x[0])
    pair_printed_count = 0
    for condition, data in sorted_r1_pairs:
        if data["periods"] >= 2 or len(data["cold"]) > 0:
            pair_printed_count += 1
            hot_str = ", ".join(
                [f"【{z}】({pct:.1%})" for z, c, pct in data["hot"][:3]]
            )
            cold_str = ", ".join([f"【{z}】(🛑硬杀)" for z, cold, pct in data["cold"]])
            output.append(
                f"    * [联合特征] {condition} ：跨年共触发 {data['periods']} 期"
            )
            if hot_str:
                output.append(f"      ---> 🎯联合靶向狙击: {hot_str}")
            if cold_str:
                output.append(f"      ---> 🛑联合铁律强杀: {cold_str}")
    if pair_printed_count == 0:
        output.append("    * 当前暂无满足高频爆发或绝对硬杀的高阶生肖对联合特征形态。")

    output.append("\n【查找器 7：前三期生肖轨迹断层回补矩阵】")
    trace = report.get("trace_recovery", {})
    for name, data in trace.items():
        if not data:
            continue
        output.append(f"  >>> {name}")
        sorted_data = sorted(data.items(), key=lambda x: x[1]["rate"], reverse=True)
        for z, stat in sorted_data[:5]:
            output.append(
                f"    * 【{z}】: "
                f"触发 {stat['trigger']} 次 | "
                f"下一期回补 {stat['recover']} 次 | "
                f"概率 {stat['rate']:.1%}"
            )

    output.append("\n【查找器 2：历史零出现条件审计（不直接杀号）】")
    if report["rule2_kills"]:
        for item in report["rule2_kills"]:
            status = "🔥绝对断档" if item["prob"] == 0 else "❄️极度罕见"
            output.append(
                f"    * 历史观察：本期开出 【{item['curr']}】(跨年触发{item['trigger_p']}期) -> 下期【{item['kill']}】开出率: {item['prob']:.1%} [{status}；不进入正式排除]"
            )
    else:
        output.append("    * 暂未洗出符合过滤条件的跨期零出现观察。")

    output.append("\n==================================================")
    output.append("【查找器 3：十进制区间空间局限性下沉细分矩阵（全形态通透版）】")
    output.append("==================================================")
    for r_label, r_data in report["rule3_report"].items():
        periods_data = r_data.get("periods_with_two", r_data.get("periods", 0))
        output.append(
            f"\n  >>> 区间 [{r_label}] <<< ：跨年共触发双号现象 {periods_data} 期"
        )
        if not r_data.get("slots"):
            continue
        for slots_num, s_stat in sorted(r_data["slots"].items()):
            tot = s_stat["total"] if s_stat["total"] > 0 else 1
            output.append(
                f"    * [物理约束] 当中间仅夹着 [{slots_num}] 个数字槽时 (触发 {s_stat['total']} 次)："
            )
            output.append(
                f"      ① 组内夹击率 -> {s_stat['in_range']/tot:.1%} | ② 全组断档率 -> {s_stat['no_hit']/tot:.1%}"
            )

    output.append("\n【查找器 4：时间隔离版特定号码衍生微观行为特征规则库】")
    for rank, (num, score, b_rate, most_z, app_times, behavior) in enumerate(
        report["top_special_expanded"], 1
    ):
        output.append(
            f"    * 规则记录 [{rank:02d}]: 当期开出号码 【{num:02d}】 时(数据隔离期数: {app_times}) -> 5期内生肖偏态率: {b_rate:.1%}（靶向: 【{most_z}】）"
        )
        output.append(
            f"      [🎯号码衍生规则] ==> 下期期望大盘形态：单数比例 【{behavior['odd_ratio']}%】，大号比例 【{behavior['big_ratio']}%】，核心极热尾数: {', '.join(behavior['hot_tails'])}"
        )

    output.append("\n【查找器 5 & 6：生肖伴生核心阵营（全盘配对统计）】")
    for rank, (pair, freq, pct) in enumerate(report["top_15_pairs"], 1):
        output.append(
            f"    * Top {rank:02d}: 核心黄金对 {pair} -> 跨年大池同期共现 {freq} 期 (共现率: {pct:.1%})"
        )

    output.append("\n" + "=" * 50)
    output.append(f" 🎯 【实战发射台】：基于跨年特征共振 -> 下期预测推演")
    output.append("=" * 50)

    records = all_merged_records
    last_record = records[-1]
    last_nums = last_record["numbers"]
    latest_zodiac_map = analyzer.get_zodiac_map_by_date(last_record["date"])
    last_zodiacs = [latest_zodiac_map[n] for n in last_nums]
    last_z_set = set(last_zodiacs)
    last_count = len(last_z_set)

    output.append(f"  - 最新一期真实奖号 : {last_nums}")
    output.append(f"  - 最新一期开出生肖 : {last_zodiacs} (共 {last_count} 个不同生肖)")

    # 🔍 核心环境审计
    output.append("\n  ==================================================")
    output.append("  🔍 核心环境严谨度审计：当期生肖环境羁绊与偏态对冲")
    output.append("  ==================================================")
    for target_z in sorted(list(last_z_set)):
        teammates = [z for z in last_z_set if z != target_z]
        output.append(f"  >>> 审计锚点生肖: 【{target_z}】")
        output.append(
            f"    * 当期同伙组合环境 : 包含【{target_z}】的同时，队友为 {teammates}"
        )
        output.append(
            "    * 🛡️ [环境理论预测] : 剔除已开出4生肖后，其余8生肖在盲盒状态下的理论概率均等，下期完全随机时的回补爆发率理论上应为均值(约 55.0%)。"
        )
        cond_key = f"当期多样性[{last_count}种生肖]且含【{target_z}】"
        if cond_key in report["rule1"]:
            data = report["rule1"][cond_key]
            hot_str = ", ".join(
                [f"【{z}】({pct:.1%})" for z, _, pct in data["hot"][:2]]
            )
            cold_str = ", ".join(
                [
                    f"【{z}】(🔥0.0%)" if pct == 0 else f"【{z}】({pct:.1%})"
                    for z, _, pct in data["cold"][:2]
                ]
            )
            output.append(f"    * 📊 [跨年实际偏态] : 跨年共触发 {data['periods']} 期")
            output.append(
                f"      ---> 实际爆发严重超标 (正向偏态): {hot_str if hot_str else '无'}"
            )
            output.append(
                f"      ---> 历史低频/零出现观察 (负向偏态，不直接排除): {cold_str if cold_str else '无'}"
            )
        else:
            output.append(
                "    * 📊 [跨年实际偏态] : 历史大底中该单点环境未形成显著记录。"
            )
    output.append("  --------------------------------------------------")

    difficulty_score = 50
    eval_reasons = []

    if last_count in report["diversity_repeat_rule"]:
        current_div_rate = report["diversity_repeat_rule"][last_count]["repeat_rate"]
        output.append(
            f"  - 💡 【临期重复趋势预判】：本期去重多样性数量为 【{last_count}】。基于跨年大底，下期临期生肖[有号码重复出现]的概率为: 【{current_div_rate:.1%}】。"
        )
        if current_div_rate >= 0.70 or current_div_rate <= 0.30:
            difficulty_score -= 15
            eval_reasons.append(
                f"【利好】跨年大底重复概率明显偏向极端（{current_div_rate:.1%}），大底极其好防守"
            )
        else:
            difficulty_score += 10
            eval_reasons.append(
                f"【风险】重复概率极其接近50%生死线（{current_div_rate:.1%}），去留极难拿捏"
            )

    output.append("  --------------------------------------------------")
    output.append(
        "  🔥 根据跨年铁律共振，下一期（预测期）组合生成必须强制执行以下过滤：\n"
    )

    output.append(
        "  【💥 预测期生肖加减权要素（源自查找器 1 单点+高阶双核心拦截线）】:"
    )
    rule1_triplets = report.get("rule1_triplets", {})
    output.append(f"DEBUG 三生肖规则数量: {len(rule1_triplets)}")

    matched_r1 = False
    for condition, data in report["rule1"].items():
        if condition.startswith(f"当期多样性[{last_count}种生肖]") and any(
            f"【{z}】" in condition for z in last_z_set
        ):
            matched_r1 = True
            hot_str = ", ".join([f"【{z}】" for z, _, _ in data["hot"]])
            cold_str = ", ".join([f"【{z}】" for z, _, pct in data["cold"] if pct == 0])
            if cold_str and data["periods"] >= 3:
                difficulty_score -= 10
                eval_reasons.append(
                    f"【利好】触发跨年单点形态硬过滤线，稳杀生肖 {cold_str}"
                )
            if hot_str:
                output.append(
                    f"    * 💥 匹配单点环境 [{condition}] -> 下期大样本推荐保留: {hot_str}"
                )
            if cold_str:
                output.append(
                    f"    * 🛑 历史0爆发！下期组合生成时【坚决一键全杀】: {cold_str}"
                )

    matched_pair_r1 = False
    for last_pair in combinations(sorted(list(last_z_set)), 2):
        pair_cond_key = (last_count, last_pair)
        if pair_cond_key in report["rule1_pairs"]:
            matched_pair_r1 = True
            p_data = report["rule1_pairs"][pair_cond_key]
            p_hot = ", ".join([f"【{z}】" for z, _, _ in p_data["hot"][:2]])
            p_cold = ", ".join([f"【{z}】" for z, _, _ in p_data["cold"]])
            if p_cold and p_data["periods"] >= 2:
                difficulty_score -= 15
                eval_reasons.append(
                    f"【强利好】触发跨年高阶联合排查硬杀铁律，联合锁定斩杀生肖 【{p_cold}】"
                )
            output.append(
                f"    * 🛡️ 踩中高阶联合特征形态：联合包含 {last_pair} (跨年共现 {p_data['periods']} 期) -> 联合热点观察: {p_hot if p_hot else '无'} | 联合低频观察: {p_cold if p_cold else '无'}（不直接排除）"
            )

    if not matched_r1 and not matched_pair_r1:
        difficulty_score += 15
        eval_reasons.append(
            "【强风险】当前微观交叉与高阶联合排查均未命中任何历史形态，处于规则盲区"
        )
        output.append(
            "    * 当前组合形态属于历史罕见真空期，未产生高置信度红蓝交尾圈。"
        )

    matched_triplet = False
    for last_triplet in combinations(sorted(list(last_z_set)), 3):
        trip_key = (last_count, last_triplet)
        if trip_key not in rule1_triplets:
            continue
        matched_triplet = True
        t_data = rule1_triplets[trip_key]
        hot_str = ", ".join(f"【{z}】" for z, _, _ in t_data["hot"][:3])
        cold_str = ", ".join(f"【{z}】" for z, _, _ in t_data["cold"])
        output.append(
            f"    * ⭐ 三生肖联合 {last_triplet}" f"（跨年共现 {t_data['periods']} 期）"
        )
        if hot_str:
            output.append(f"      ---> 联合热点: {hot_str}")
        if cold_str:
            output.append(f"      ---> 联合低频/零出现观察（不直接排除）: {cold_str}")

    if not matched_triplet:
        output.append("    * 当前未命中任何三生肖联合规则。")

    output.append("\n  【🛑 预测期单期跨期零出现审计（源自查找器 2，不执行硬杀号）】:")
    matched_r2 = False
    for item in report["rule2_kills"]:
        if item["curr"] in last_z_set and item["prob"] == 0 and item["trigger_p"] >= 3:
            matched_r2 = True
            output.append(
                f"    * 命中历史零出现样本：本期开出【{item['curr']}】后，样本中下期【{item['kill']}】为0%；仅记录，必须再过多查找器共识和双层零误杀门禁。"
            )
    if not matched_r2:
        output.append("    * 本期未匹配到历史高频跨期零出现条件。")

    output.append("\n  【📐 预测期区间空间物理形态拦截（源自查找器 3）】:")
    matched_r3 = False
    for r_label, (r_min, r_max) in ranges_config.items():
        in_range_nums = sorted([n for n in last_nums if r_min <= n <= r_max])
        if len(in_range_nums) == 2:
            matched_r3 = True
            n1, n2 = in_range_nums[0], in_range_nums[1]
            slots_count = len([n for n in range(n1 + 1, n2)])
            r3_data = report["rule3_report"].get(r_label)
            if r3_data and "slots" in r3_data and slots_count in r3_data["slots"]:
                s_stat = r3_data["slots"][slots_count]
                tot = s_stat["total"] if s_stat["total"] > 0 else 1
                in_pct = s_stat["in_range"] / tot
                no_pct = s_stat["no_hit"] / tot
                if in_pct >= 0.65 or no_pct >= 0.65:
                    difficulty_score -= 10
                    eval_reasons.append(
                        f"【利好】区间 [{r_label}] 跨年物理卡槽约束力极强，方向极度凝聚"
                    )
                output.append(
                    f"    * 区间 [{r_label}] 触发双号 {in_range_nums}，槽位夹击空间 [{slots_count}] 个 -> 历史实战组内夹击率: {in_pct:.1%} | 全组断档率: {no_pct:.1%}"
                )
    if not matched_r3:
        difficulty_score += 8
        eval_reasons.append("【风险】无任何区间触发双号空间局限性")
        output.append("    * 本期无十进制区间触发物理槽位约束，属于自由波动形态。")

    output.append("\n  【🔮 预测期特码隔离形态特征拦截（源自查找器 4 规则库）】:")

    output.append("\n【查找器7：前三期轨迹回补规律】")
    trace_recovery_hot = report.get("trace_recovery_hot", {})
    if len(records) >= 3:
        curr = set(last_zodiacs)
        previous_map = analyzer.get_zodiac_map_by_date(records[-2]["date"])
        previous2_map = analyzer.get_zodiac_map_by_date(records[-3]["date"])
        last1 = set(previous_map[n] for n in records[-2]["numbers"])
        last2 = set(previous2_map[n] for n in records[-3]["numbers"])

        disappear = (last1 & last2) - curr
        if disappear:
            for z in disappear:
                if z in trace_recovery_hot:
                    item = trace_recovery_hot[z]
                    hot = ", ".join(f"【{a}】({b:.1%})" for a, _, b in item["hot"][:3])
                    output.append(
                        f"    * 【{z}】连续两期出现，本期消失 -> 下期历史高频：{hot}"
                    )
        else:
            output.append("    * 当前未发现连续两期消失的生肖。")
    else:
        output.append("    * 历史记录不足 3 期，无法分析前三期轨迹回补规律。")

    # 特码特征规则输出
    num_behavior_lookup = {item[0]: item[5] for item in report["top_special_expanded"]}
    odd_biases = []
    big_biases = []

    for n in last_nums:
        if n in num_behavior_lookup:
            rule_bh = num_behavior_lookup[n]
            odd_biases.append(rule_bh["odd_ratio"])
            big_biases.append(rule_bh["big_ratio"])
            output.append(
                f"    * 踩中历史奖号 【{n:02d}】 干净特征轴行为 ==> 规则提示下期形态：单数概率 {rule_bh['odd_ratio']}%，大号概率 {rule_bh['big_ratio']}%，关注尾数 {', '.join(rule_bh['hot_tails'])}"
            )

    if len(odd_biases) >= 2:
        max_o = max(odd_biases)
        min_o = min(odd_biases)
        if max_o > 60.0 and min_o < 40.0:
            difficulty_score += 20
            eval_reasons.append(
                f"【极度危险】特码特征规则库产生剧烈对冲！多组单双概率（最大{max_o}% vs 最小{min_o}%）相互矛盾，极易引发资金归零"
            )

    output.append("\n" + "📊 " * 15)
    output.append("  【🌟 全功能自动化大盘推演预测难易度量化评估面板】")
    output.append("📊 " * 15)

    difficulty_score = max(10, min(95, difficulty_score))

    if difficulty_score >= 70:
        conclusion = "❌【极难预测（混乱撕裂/数据对冲期）】"
        action_advice = "🛑 战略性空仓！当前跨年多重微观行为规则发生剧烈内耗与对冲，资金不建议进场硬碰硬。"
    elif difficulty_score <= 40:
        conclusion = "🟢【极易拦截（特征高聚能共振期）】"
        action_advice = "历史描述形态较集中，但不代表下一期确定；正式判断仍以无泄漏回测榜和上线门禁为准。"
    else:
        conclusion = "🟡【常规波动（平稳过渡期）】"
        action_advice = "当前描述形态接近常规波动；正式判断仍以无泄漏回测榜为准。"

    output.append(
        f"  - 综合指标量化总分 : 【{difficulty_score} 分】 (分数越高越混乱，超过70分即判定为不可测期)"
    )
    output.append(f"  - 预测难易度结论评级: {conclusion}")
    output.append("  - 底层大盘状态审计日志 :")
    for r in eval_reasons:
        output.append(f"    * {r}")
    output.append(f"  - 💡 实战决策执行指令: \n    {action_advice}")
    output.append("\n" + "=" * 50)

    output.append("")
    output.append("==================================================")
    output.append("【查找器 7：跨期时间轴演化规律】")
    output.append("==================================================")
    timeline = report.get("timeline", {})
    prev_miss_return = timeline.get("prev_miss_return", {})
    for z, data in sorted(
        prev_miss_return.items(),
        key=lambda x: x[1]["return_rate"],
        reverse=True,
    ):
        output.append(
            f"    * 【{z}】 上期出现→本期断档 "
            f"(历史触发 {data['trigger']} 次)"
            f" -> 下一期回补 {data['return']} 次"
            f" | 回补率 {data['return_rate']:.1%}"
        )

    output.append("")
    output.append("  【连续2期出现 → 本期断档 → 下一期回补】")
    double_keep = timeline.get("double_keep_break", {})
    for z, data in sorted(
        double_keep.items(),
        key=lambda x: x[1]["return_rate"],
        reverse=True,
    ):
        output.append(
            f"    * 【{z}】 连续2期出现后断档"
            f"（{data['trigger']} 次）"
            f" -> 回补率 {data['return_rate']:.1%}"
        )

    output.append("")
    output.append("  【连续空窗 → 下一期立即回补】")
    gap_return = timeline.get("gap_return", {})
    for gap, data in sorted(gap_return.items(), key=lambda x: x[0]):
        output.append(
            f"    * 连续空窗 {gap} 期"
            f"（历史 {data['trigger']} 次）"
            f" -> 下一期立即回补率 {data['return_rate']:.1%}"
        )
    output.append("")
    output.append("  【连续空窗最终结束规律】")
    gap_finish = timeline.get("gap_finish", {})
    for gap, data in sorted(gap_finish.items(), key=lambda x: x[0]):
        output.append(
            f"    * 连续空窗 {gap} 期"
            f"（历史 {data['trigger']} 次）"
            f" -> 最终结束空窗率 {data['return_rate']:.1%}"
        )

    output.append("=" * 50)
    output.append("🎯 综合生肖概率排行榜（严格滚动回测版）")
    output.append("=" * 50)
    holdout = top6_report["holdout"]
    frequency_holdout = top6_report["frequency_baseline_holdout"]
    random_expected = top6_report["random_top6_expected_hit5_eligible_rate"]
    interval = holdout["unique_hit5_eligible_wilson95"]
    output.append(
        "  指标定义：前6与下一期去重生肖集合交集不少于5；"
        "另行统计前6覆盖7个开奖位置不少于5。"
    )
    output.append(
        f"  2024–2026隔离期：{holdout['periods']}期，"
        f"其中可中5的有效期{holdout['eligible_periods']}期。"
    )
    output.append(
        f"  去重生肖中5率：{holdout['unique_hit5_eligible_rate']:.2%} "
        f"(95%区间 {interval[0]:.2%}–{interval[1]:.2%})；"
        f"频率基线 {frequency_holdout['unique_hit5_eligible_rate']:.2%}；"
        f"随机Top6理论期望 {random_expected:.2%}。"
    )
    output.append(
        f"  7个号码位置覆盖至少5个：{holdout['ball_hit5_rate']:.2%}；"
        f"平均命中去重生肖 {holdout['average_unique_hits']:.3f} 个。"
    )
    active_weights = ", ".join(
        f"{name}={weight:.2f}"
        for name, weight in top6_report["weights"].items()
        if weight > 0
    )
    output.append(f"  开发期选定权重：{active_weights}")
    incremental = top6_report.get("incremental_update")
    if incremental:
        mode_label = {
            "full_rebuild": "全量初始化",
            "incremental_append": "只处理新增期",
            "cache_reused": "复用当前检查点",
        }.get(incremental["mode"], incremental["mode"])
        output.append(
            f"  数据更新模式：{mode_label}；"
            f"检查点 {incremental['previous_record_count']}→"
            f"{incremental['current_record_count']} 期；"
            f"追加校验={'通过' if incremental['append_validation_passed'] else '失败'}。"
        )
        for detail in incremental.get("appended_details", []):
            output.append(
                f"    * 新增第{detail['issue']}期 {detail['date']}："
                f"{detail['numbers']}；农历生肖年{detail['zodiac_year']}，"
                f"本命生肖【{detail['base_zodiac']}】。"
            )
    output.append(
        f"  F5轨迹断层开关：{'开启' if top6_report['f5_enabled'] else '关闭'}；"
        f"{top6_report['f5_effect_reason']}。"
    )
    output.append(
        f"  F5历史门禁：{'通过' if top6_report['f5_gate_passed'] else '未通过'}；"
        f"{top6_report['f5_gate_reason']}。"
    )
    output.append(
        f"  F6/F7去偏关联上线状态："
        f"{'已上线' if top6_report['f67_feature_deployed'] else '已拒绝'}；"
        f"{top6_report['f67_gate_reason']}。"
    )
    output.append("  切换方法：python main.py --f5 on 或 python main.py --f5 off")
    candidate_validation = top6_report["candidate_validation"]
    candidate_holdout = top6_report["candidate_holdout_audit"]
    previous_validation = top6_report["previous_stage_validation"]
    previous_holdout = top6_report["previous_stage_holdout"]
    output.append(
        f"  F6/F7候选：验收期中5率 {candidate_validation['unique_hit5_eligible_rate']:.2%} "
        f"(旧模型 {previous_validation['unique_hit5_eligible_rate']:.2%})；"
        f"最终隔离期 {candidate_holdout['unique_hit5_eligible_rate']:.2%} "
        f"(旧模型 {previous_holdout['unique_hit5_eligible_rate']:.2%})。"
    )
    joint_validation = top6_report["joint_candidate_validation"]
    joint_holdout = top6_report["joint_candidate_holdout_audit"]
    joint_reference_validation = top6_report["joint_reference_validation"]
    joint_reference_holdout = top6_report["joint_reference_holdout"]
    joint_weights = ", ".join(
        f"{name}={weight:.2f}"
        for name, weight in top6_report["joint_candidate_weights"].items()
        if weight > 0
    )
    output.append("  【F1–F7联合消融与评分约束】")
    output.append(
        f"    * 联合候选上线状态："
        f"{'已上线' if top6_report['joint_feature_deployed'] else '已拒绝'}；"
        f"{top6_report['joint_gate_reason']}。"
    )
    output.append(f"    * 开发期联合候选权重：{joint_weights}")
    output.append(
        f"    * 验收期中5：候选 {joint_validation['unique_hit5']}次/"
        f"{joint_validation['eligible_periods']}期 "
        f"({joint_validation['unique_hit5_eligible_rate']:.2%})，"
        f"现行 {joint_reference_validation['unique_hit5']}次 "
        f"({joint_reference_validation['unique_hit5_eligible_rate']:.2%})。"
    )
    output.append(
        f"    * 2024–2026中5：候选 {joint_holdout['unique_hit5']}次/"
        f"{joint_holdout['eligible_periods']}期 "
        f"({joint_holdout['unique_hit5_eligible_rate']:.2%})，"
        f"现行 {joint_reference_holdout['unique_hit5']}次 "
        f"({joint_reference_holdout['unique_hit5_eligible_rate']:.2%})。"
    )
    caps = top6_report["weight_family_caps"]
    output.append(
        "    * 同源权重上限："
        + "、".join(f"{name}≤{cap:.0%}" for name, cap in caps.items())
        + "；同一查找器拆出的多列不能重复满额加分。"
    )
    output.append("    * 现行特征逐项关闭（验收期中5 / 隔离期中5）：")
    for item in top6_report["ablation"]["leave_one_out"]:
        output.append(
            f"      - 关闭 {item['removed']}："
            f"{item['validation']['unique_hit5']} / {item['holdout']['unique_hit5']}"
        )
    high_overlap = [
        item
        for item in top6_report["feature_dependency_audit"]
        if item["overlap_level"] == "high_overlap"
    ]
    if high_overlap:
        output.append(
            "    * 高重复证据："
            + "；".join(
                f"{'+'.join(item['features'])} 相关系数 {item['correlation']:.3f}"
                for item in high_overlap[:5]
            )
            + "；受同源权重上限约束。"
        )
    else:
        output.append("    * 未发现绝对相关系数达到0.80的高重复证据。")
    kill_validation = top6_report["hard_kill_validation"]
    kill_holdout = top6_report["hard_kill_holdout_audit"]
    output.append("  【F2多查找器硬绝杀门禁】")
    output.append(
        "    * 必须同时满足：F2大样本跨年至少30期/10年且上置信界≤20%；"
        "至少3个独立查找器看空、其中2个强看空；任何弱/强看多立即否决。"
    )
    output.append(
        f"    * 策略验收触发 {kill_validation['triggers']} 次、误杀 "
        f"{kill_validation['false_kills']} 次；隔离期触发 "
        f"{kill_holdout['triggers']} 次、误杀 {kill_holdout['false_kills']} 次。"
    )
    output.append(
        f"    * 正式状态："
        f"{'已开启' if top6_report['hard_kill_policy_deployed'] else '关闭'}；"
        "未通过门禁时只记录审计证据，不扣分、不移出Top6。"
    )
    output.append(
        "  注意：这是隔离回测概率，不是每期保证；下一期少于5种生肖时逻辑上无法中5。"
    )
    output.append("")
    latest_ranking = top6_report["latest"]["ranking"]
    strength_report = top6_report["latest"]["signal_strength"]
    feature_labels = {
        "baseline": "长期基线",
        "diversity": "F1数量",
        "sequence": "F1序列",
        "prototype": "F1原型",
        "special": "F4特码状态",
        "stable_conditional": "F2稳定条件",
        "f3_attributes": "F3属性",
        "f4_special": "F4组合",
        "f5_trajectory": "F5轨迹",
        "f67_debiased": "F6/F7去偏",
    }
    tier_labels = {
        "strong_positive": "强升",
        "weak_positive": "弱升",
        "neutral": "微弱",
        "weak_negative": "弱降",
        "strong_negative": "强降",
    }
    for idx, item in enumerate(latest_ranking, 1):
        marker = "TOP6" if item["in_top6"] else "候补"
        components = item["components"]
        baseline = components["baseline"]
        net_adjustment = item["probability"] - baseline
        drivers = [
            signal
            for signal in strength_report[item["zodiac"]]
            if abs(signal["score_contribution"]) >= 0.00005
        ][:3]
        driver_text = "、".join(
            f"{feature_labels.get(signal['feature'], signal['feature'])}"
            f"{signal['score_contribution']:+.2%}"
            f"({tier_labels.get(signal['tier'], signal['tier'])})"
            for signal in drivers
        ) or "无显著调整"
        output.append(
            f"{idx:02d}. 【{item['zodiac']}】 {marker} "
            f"| 下一期出现概率估计 {item['probability']:.2%} "
            f"| 长期基线 {baseline:.2%} | 净调整 {net_adjustment:+.2%} "
            f"| 主要贡献：{driver_text}"
        )
    output.append(
        "  当前Top6：" + "、".join(top6_report["latest"]["top6"])
    )
    output.append(
        "  F5关闭Top6：" + "、".join(top6_report["latest"]["f5_off_top6"])
    )
    output.append(
        "  F5开启Top6：" + "、".join(top6_report["latest"]["f5_on_top6"])
    )
    output.append("")
    conditional_latest = top6_report["latest"]["conditional"]
    output.append("  【F6/F7扣除边际热度后的关联审计】")
    output.append(
        "    * 搜索顺序：完整去重集合→逐级子集→单生肖；"
        "每个目标只保留一条规则；禁止打包推荐和打包排除。"
    )
    fdr_meta = conditional_latest["multiple_testing"]
    output.append(
        f"    * 多重检验：{fdr_meta['method']}，"
        f"本期检验 {fdr_meta['tests']} 条，FDR阈值 {fdr_meta['fdr_threshold']:.0%}。"
    )
    f67_rules = list(conditional_latest["selected_debiased_rules"].values())
    f67_rules.sort(key=lambda item: item["debiased_evidence_score"], reverse=True)
    if not f67_rules:
        output.append("    * 当前没有同时通过边际校正、FDR和跨年稳定性的规则。")
    for rule in f67_rules[:8]:
        direction = "升温" if rule["delta"] > 0 else "降温"
        output.append(
            f"    * {'+'.join(rule['combo'])} → {rule['target']} {direction}："
            f"{rule['hits']}/{rule['samples']}，组合{rule['size']}生肖，"
            f"边际校正Lift {rule['lift_after_marginal']:.3f}，"
            f"FDR q={rule['fdr_q_value']:.3f}，偏差 {rule['delta']:+.2%}"
        )
    pair_audit = top6_report["latest"]["f67_pair_audit"]
    output.append("  【F7同期生肖对独立性审计（仅解释，不打包）】")
    for pair in pair_audit[:8]:
        label = {
            "residual_positive": "扣除热度后仍正关联",
            "residual_negative": "扣除热度后仍负关联",
            "explained_by_marginals": "主要由各自热度解释",
        }[pair["association"]]
        output.append(
            f"    * {'+'.join(pair['pair'])}：同期{pair['cooccurrences']}次，"
            f"Lift {pair['lift']:.3f}，Phi {pair['phi']:+.3f}，{label}"
        )
    output.append("")
    f5_latest = top6_report["latest"]["f5"]
    output.append("  【F5轨迹断层开关效果审计】")
    f5_rules = list(f5_latest["selected_raw_rules"].values())
    f5_rules.sort(key=lambda item: item["evidence_score"], reverse=True)
    for rule in f5_rules[:8]:
        state = rule["state"]
        direction = "升温" if rule["delta"] > 0 else "降温"
        status = (
            "稳定通过"
            if rule["stability_passed"]
            else "拒绝（" + "、".join(rule["stability_failure_reasons"]) + "）"
        )
        output.append(
            f"    * 【{rule['target']}】轨迹 {''.join(map(str, state['bits']))}，"
            f"空窗{state['gap']}期/连开{state['streak']}期；"
            f"{rule['state_label']} → {direction}，"
            f"{rule['hits']}/{rule['samples']}，偏差 {rule['delta']:+.2%}，{status}"
        )
    output.append("")
    f3_latest = top6_report["latest"]["f3"]
    f3_profile = f3_latest["profile"]
    output.append("  【F3五行、阴阳、家禽野兽属性审计】")
    output.append(
        "    * 五行计数："
        + "、".join(
            f"{element}{count}"
            for element, count in f3_profile["element_counts"].items()
        )
        + f"；阴{f3_profile['yin_count']}/阳{f3_profile['yang_count']}；"
        + f"家禽{f3_profile['domestic_count']}/野兽{f3_profile['wild_count']}。"
    )
    output.append(
        "    * 达到样本门槛的属性层级："
        + ("、".join(f3_latest["eligible_states"]) or "无")
    )
    f3_diversity = top6_report["f3_diversity_holdout"]
    output.append(
        f"    * F3候选去重数：{f3_latest['predicted_next_diversity']}种；"
        f"隔离期精确率 {f3_diversity['exact_rate']:.2%}，"
        f"滚动众数基线 {f3_diversity['rolling_mode_baseline_exact_rate']:.2%}；"
        f"上线状态 {'已上线' if top6_report['f3_diversity_feature_deployed'] else '已拒绝'}，"
        f"正式采用 {f3_latest['deployed_next_diversity']}种。"
    )
    f3_rules = list(f3_latest["selected_raw_rules"].values())
    f3_rules.sort(key=lambda item: item["evidence_score"], reverse=True)
    for rule in f3_rules[:8]:
        direction = "升温" if rule["delta"] > 0 else "降温"
        status = (
            "稳定通过"
            if rule["stability_passed"]
            else "拒绝（" + "、".join(rule["stability_failure_reasons"]) + "）"
        )
        output.append(
            f"    * {rule['state_label']} → {rule['target']} {direction}："
            f"{rule['hits']}/{rule['samples']}，跨{rule['years']}年，"
            f"偏差 {rule['delta']:+.2%}，{status}"
        )
    output.append("")
    f4_latest = top6_report["latest"]["f4"]
    output.append("  【F4特码生肖与本期组合审计】")
    output.append(f"    * 上线状态：已拒绝；{top6_report['f4_gate_reason']}。")
    output.append(
        f"    * 本期特码生肖【{f4_latest['special']}】；"
        f"本命生肖={'是' if f4_latest['special_is_base'] else '否'}；"
        f"与正码生肖重复={'是' if f4_latest['special_repeated'] else '否'}；"
        f"特码身份样本 {f4_latest['identity_samples']} 期；"
        f"同状态样本 {f4_latest['state_samples']} 期。"
    )
    diversity_probs = f4_latest["next_diversity_probabilities"]
    output.append(
        "    * 下一期去重生肖数概率："
        + "，".join(
            f"{value}种={diversity_probs[str(value)] if str(value) in diversity_probs else diversity_probs[value]:.1%}"
            for value in range(3, 8)
        )
    )
    selected_diversity_rule = f4_latest.get("selected_diversity_rule")
    if selected_diversity_rule:
        output.append(
            f"    * 去重数组合审计采用：特码【{selected_diversity_rule['special']}】+"
            f"{'、'.join(selected_diversity_rule['other_combo']) if selected_diversity_rule['other_combo'] else '无其他生肖'}；"
            f"历史 {selected_diversity_rule['samples']} 期，跨"
            f"{selected_diversity_rule['years']}年。"
        )
    f4_diversity_holdout = top6_report["f4_diversity_holdout"]
    output.append(
        f"    * F4候选推定下一期去重数：{f4_latest['predicted_next_diversity']}种 "
        f"(期望值 {f4_latest['expected_next_diversity']:.2f})；"
        f"2024–2026精确命中率 {f4_diversity_holdout['exact_rate']:.2%}，"
        f"滚动众数基线 {f4_diversity_holdout['rolling_mode_baseline_exact_rate']:.2%}；"
        f"误差不超过1种 {f4_diversity_holdout['within_one_rate']:.2%}。"
    )
    output.append(
        f"    * F4去重数上线状态："
        f"{'已上线' if top6_report['f4_diversity_feature_deployed'] else '已拒绝'}；"
        f"{top6_report['f4_diversity_gate_reason']}；"
        f"正式采用 {f4_latest['deployed_next_diversity']}种。"
    )
    f4_raw_rules = list(f4_latest["selected_raw_rules"].values())
    f4_raw_rules.sort(key=lambda item: item["evidence_score"], reverse=True)
    for rule in f4_raw_rules[:8]:
        direction = "升温" if rule["delta"] > 0 else "降温"
        status = (
            "稳定通过"
            if rule["stability_passed"]
            else "拒绝（" + "、".join(rule["stability_failure_reasons"]) + "）"
        )
        output.append(
            f"    * 特码【{rule['special']}】+"
            f"{'、'.join(rule['other_combo']) if rule['other_combo'] else '无其他生肖'}"
            f" → {rule['target']} {direction}：{rule['hits']}/{rule['samples']}，"
            f"跨{rule['years']}年，偏差 {rule['delta']:+.2%}，{status}"
        )
    output.append("")
    output.append("  【条件组合跨年份稳定性审计（不重复加分）】")
    selected_rules = list(
        top6_report["latest"]["conditional"]["selected_rules"].values()
    )
    selected_rules.sort(key=lambda item: item["evidence_score"], reverse=True)
    for rule in selected_rules[:8]:
        direction = "升温" if rule["delta"] > 0 else "降温"
        stability_status = (
            "通过"
            if rule["stability_passed"]
            else "拒绝（" + "、".join(rule["stability_failure_reasons"]) + "）"
        )
        output.append(
            f"    * {'+'.join(rule['combo'])} → {rule['target']} {direction}："
            f"{rule['hits']}/{rule['samples']}，跨{rule['years']}年，"
            f"平滑概率 {rule['smoothed_rate']:.2%}，"
            f"相对基线 {rule['delta']:+.2%}，"
            f"同向年 {rule['same_direction_years']}/"
            f"{rule['same_direction_years'] + rule['opposite_direction_years']}，"
            f"留一年同向率 {rule['loo_direction_ratio']:.0%}，"
            f"稳定性 {stability_status}"
        )
    stable_rules = list(
        top6_report["latest"]["conditional"]["selected_stable_rules"].values()
    )
    stable_rules.sort(
        key=lambda item: item["stable_evidence_score"], reverse=True
    )
    output.append("  【当前通过稳定筛选的条件规则】")
    for rule in stable_rules[:8]:
        output.append(
            f"    * {'+'.join(rule['combo'])} → {rule['target']}："
            f"有效年份 {rule['effective_years']:.1f}，"
            f"年度加权同向率 {rule['weighted_direction_ratio']:.0%}，"
            f"最大单年样本占比 {rule['max_year_sample_share']:.0%}，"
            f"稳定得分 {rule['stability_score']:.3f}"
        )
    hard_kills = top6_report["latest"]["hard_kill_candidates"]
    output.append(
        f"    * 多查找器共同确认的硬绝杀："
        f"{', '.join(item['target'] for item in hard_kills) if hard_kills else '无'}"
    )

    final_report = "\n".join(output)
    print(final_report)

    # 安全写入文件
    try:
        advanced_report_path = (
            "zodiac_advanced_report_f5_on.txt"
            if f5_enabled
            else "zodiac_advanced_report.txt"
        )
        with open(advanced_report_path, "w", encoding="utf-8") as f:
            f.write(final_report)
        os.makedirs(os.path.dirname(top6_json_path), exist_ok=True)
        with open(top6_json_path, "w", encoding="utf-8") as f:
            json.dump(top6_report, f, ensure_ascii=False, indent=2)
        print(f"\n[系统提示] 跨年数据打通成功，结果已写入 {advanced_report_path}")
        print(f"[系统提示] Top6完整回测已写入 {top6_json_path}")
    except IOError as e:
        print(f"\n⚠️ 写入报告文件失败: {e}")


if __name__ == "__main__":
    main()
