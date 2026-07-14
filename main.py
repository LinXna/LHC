import os
import json
from datetime import datetime
from itertools import combinations
from zodiac_analyzer import ZodiacPatternAnalyzer

ranges_config = {
    "0-9": (1, 9),
    "10-19": (10, 19),
    "20-29": (20, 29),
    "30-39": (30, 39),
    "40-49": (40, 49),
}


def get_base_zodiac_by_year(year_int):
    """根据年份自动推导本命年"""
    zodiac_cycle = [
        "猴",
        "鸡",
        "狗",
        "猪",
        "鼠",
        "牛",
        "虎",
        "兔",
        "龙",
        "蛇",
        "马",
        "羊",
    ]
    return zodiac_cycle[year_int % 12]


def main():
    data_dir = "data"
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
        json_files = sorted([f for f in os.listdir(data_dir) if f.endswith(".json")])
    except OSError as e:
        print(f"❌ 错误：读取数据目录失败：{e}")
        return

    if not json_files:
        print(f"❌ 错误：【{data_dir}】 文件夹内没有找到任何年份的 JSON 文件。")
        return

    # 🚀 按年份加载数据
    for file_name in json_files:
        try:
            year_int = None
            file_path = os.path.join(data_dir, file_name)

            # 优先从文件内容提取年份（从第一条记录的 preDrawDate）
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    body_list = (
                        payload.get("result", {}).get("data", {}).get("bodyList", [])
                    )
                    if isinstance(body_list, list) and len(body_list) > 0:
                        first_date = body_list[0].get("preDrawDate")
                        if first_date and len(first_date) >= 4:
                            year_int = int(first_date[:4])
            except Exception:
                pass  # 回退到文件名解析

            # 内容提取失败则从文件名提取
            if year_int is None:
                year_str = file_name.split(".")[0]
                year_int = int(year_str)

            dynamic_base = get_base_zodiac_by_year(year_int)

            # 实例化当年的分析器
            temp_analyzer = ZodiacPatternAnalyzer(base_zodiac=dynamic_base)
            year_records = temp_analyzer.load_json_data(file_path=file_path)

            if year_records:
                for record in year_records:
                    if isinstance(record, dict):
                        record["archive_year"] = year_int
                        all_merged_records.append(record)

            print(
                f"📂 发现数据源: {file_name} | 本命年: 【{dynamic_base}】 -> 加载成功"
            )

        except Exception as e:
            print(f"⚠️ 警告：处理文件 {file_name} 失败，原因: {e}")

    if not all_merged_records:
        print("❌ 未成功加载任何年份的历史数据。")
        return

    # 🔧 全局排序，保证期号顺序
    all_merged_records.sort(key=lambda x: x.get("issue", 0))

    print(f"成功加载 {len(all_merged_records)} 条历史记录。")

    # 确定最新年份
    latest_file_year = None
    try:
        latest_file_year = int(json_files[-1].split(".")[0])
    except (ValueError, IndexError):
        # 回退方案：如果文件名解析失败，尝试从最后一条记录获取
        if all_merged_records:
            latest_file_year = all_merged_records[-1].get("archive_year")
        if latest_file_year is None:
            print("❌ 无法确定最新年份，请检查数据文件。")
            return

    final_base_zodiac = get_base_zodiac_by_year(latest_file_year)
    print(
        f"\n🚀 统一采用最新 【{latest_file_year} ({final_base_zodiac}年)】 逻辑引擎进行全盘规律推演..."
    )

    try:
        analyzer = ZodiacPatternAnalyzer(base_zodiac=final_base_zodiac)
    except Exception as e:
        print(f"❌ 分析失败：{e}")
        return

    # 喂入合并后的大池子
    report = analyzer.compute_patterns(all_merged_records)
    total_valid_p = report["total"] - 1

    # ========================================================================
    # 报告渲染输出逻辑
    # ========================================================================
    output = []
    output.append("==================================================")
    output.append("    量化多组合精准特征深度挖潜报告 (V6-Strict)    ")
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

    output.append("\n【查找器 2：微观高置信度跨期强力杀号过滤器】")
    if report["rule2_kills"]:
        for item in report["rule2_kills"]:
            status = "🔥绝对断档" if item["prob"] == 0 else "❄️极度罕见"
            output.append(
                f"    * 过滤线：本期开出 【{item['curr']}】(跨年触发{item['trigger_p']}期) -> 下期绝杀: 【{item['kill']}】(开出率: {item['prob']:.1%}) [{status}]"
            )
    else:
        output.append("    * 暂未洗出符合过滤条件的跨期绝杀生肖。")

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
    last_zodiacs = [analyzer.zodiac_map[n] for n in last_nums]
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
                f"      ---> 实际历史打烊绝杀 (负向偏态): {cold_str if cold_str else '无'}"
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
                f"    * 🛡️ 踩中高阶联合特征形态：联合包含 {last_pair} (跨年共现 {p_data['periods']} 期) -> 联合突围生肖: {p_hot if p_hot else '无'} | 联合锁死绝杀: {p_cold if p_cold else '无'}"
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
            output.append(f"      ---> 联合绝杀: {cold_str}")

    if not matched_triplet:
        output.append("    * 当前未命中任何三生肖联合规则。")

    output.append("\n  【🛑 预测期单期跨期绝对杀号线（源自查找器 2）】:")
    matched_r2 = False
    for item in report["rule2_kills"]:
        if item["curr"] in last_z_set and item["prob"] == 0 and item["trigger_p"] >= 3:
            matched_r2 = True
            difficulty_score -= 12
            eval_reasons.append(
                f"【利好】触发跨期高频100%杀号过滤器，强制绝杀 【{item['kill']}】"
            )
            output.append(
                f"    * 命中绝杀线：因为当期开出了【{item['curr']}】，跨年历史上明文规定下期 100% 绝杀 -> 【{item['kill']}】"
            )
    if not matched_r2:
        output.append("    * 本期未匹配到历史高频跨期 100% 绝对杀号过滤器。")

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
        last1 = set(analyzer.zodiac_map[n] for n in records[-2]["numbers"])
        last2 = set(analyzer.zodiac_map[n] for n in records[-3]["numbers"])

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
        action_advice = "🎯 黄金出击时刻！单点/高阶联合特征与跨期绝杀线在大样本下产生多重锁死共振，防线极其稳固！"
    else:
        conclusion = "🟡【常规波动（平稳过渡期）】"
        action_advice = "⚠️ 谨慎按部就班。小仓位严格遵循跨年高低频截尾圈防守。"

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
    output.append("🎯 综合生肖评分排行榜")
    output.append("=" * 50)
    ranking = report["zodiac_ranking"]
    for idx, (z, info) in enumerate(ranking, 1):
        output.append(
            f"{idx:02d}. 【{z}】"
            f"   得分:{info['score']}"
            f"   可信度:{info['confidence']}"
        )
        for r in info["reasons"][:5]:
            output.append(f"      └─ {r}")

    final_report = "\n".join(output)
    print(final_report)

    # 安全写入文件
    try:
        with open("zodiac_advanced_report.txt", "w", encoding="utf-8") as f:
            f.write(final_report)
        print("\n[系统提示] 跨年数据打通成功，结果已写入 zodiac_advanced_report.txt")
    except IOError as e:
        print(f"\n⚠️ 写入报告文件失败: {e}")


if __name__ == "__main__":
    main()
