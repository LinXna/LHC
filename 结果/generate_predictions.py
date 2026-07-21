import os
import sys
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from zodiac_analyzer import ZodiacPatternAnalyzer
except ImportError:
    print("❌ [错误]：无法从 zodiac_analyzer.py 中导入 ZodiacPatternAnalyzer。")
    sys.exit(1)


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


def auto_engine_prediction():
    print("==================================================")
    try:
        f5_enabled = get_f5_switch(sys.argv[1:])
    except ValueError as exc:
        print(f"❌ {exc}")
        return
    print(" 🚀 LHC 自动化多特征组合推演引擎 (联合约束版) 启动... ")
    print("==================================================")

    try:
        analyzer = ZodiacPatternAnalyzer("马")
    except Exception:
        analyzer = ZodiacPatternAnalyzer()

    verified_dir = os.path.join(PROJECT_ROOT, "data_verified")
    records = analyzer.load_json_data(data_dir=verified_dir)
    if not records:
        print("❌ 错误：未成功加载数据，请检查 data_verified/2026.json 是否存在。")
        return

    top6_cache_path = os.path.join(
        SCRIPT_DIR,
        "top6_walk_forward_report_f5_on.json"
        if f5_enabled
        else "top6_walk_forward_report.json",
    )
    incremental_state_path = os.path.join(
        SCRIPT_DIR, "top6_incremental_state.pkl"
    )
    top6_report = None
    cached_selection = None
    expected_snapshot = {
        "record_count": len(records),
        "first_date": records[0]["date"],
        "latest_date": records[-1]["date"],
        "latest_issue": records[-1]["issue"],
        "latest_numbers": records[-1]["numbers"],
    }
    try:
        with open(top6_cache_path, "r", encoding="utf-8") as f:
            cached_report = json.load(f)
        cached_selection = cached_report
        if (
            cached_report.get("model_version") == analyzer.TOP6_MODEL_VERSION
            and cached_report.get("source_snapshot") == expected_snapshot
            and cached_report.get("f5_enabled") is f5_enabled
            and cached_report.get("incremental_cache_version") == 2
            and os.path.isfile(incremental_state_path)
        ):
            top6_report = cached_report
            print("⚡ 已复用与当前数据完全一致的严格滚动回测缓存。")
    except (OSError, ValueError, TypeError):
        pass
    if top6_report is None:
        contexts, rows, _, incremental_meta = (
            analyzer.build_or_update_incremental_state(
                records, incremental_state_path
            )
        )
        top6_report = analyzer.build_walk_forward_top6_report(
            records,
            f5_enabled=f5_enabled,
            precomputed=(contexts, rows),
            cached_selection=cached_selection,
        )
        top6_report["incremental_update"] = incremental_meta
        top6_report["incremental_cache_version"] = 2
        with open(top6_cache_path, "w", encoding="utf-8") as f:
            json.dump(top6_report, f, ensure_ascii=False, indent=2)
        print(
            "⚙️ 增量状态："
            f"{incremental_meta['mode']}；"
            f"新增 {incremental_meta['appended_records']} 期；"
            f"权重搜索复用={'是' if top6_report['incremental_selection_reused'] else '否'}。"
        )
    last_record = records[-1]

    # 动态对齐生肖
    zodiac_order = getattr(
        analyzer,
        "zodiac_order",
        ["马", "蛇", "龙", "兔", "虎", "牛", "鼠", "猪", "狗", "鸡", "猴", "羊"],
    )
    zodiac_to_nums = {z: [] for z in zodiac_order}
    num_to_zodiac = {}

    if hasattr(analyzer, "get_zodiac_map_by_date"):
        num_to_zodiac = analyzer.get_zodiac_map_by_date(last_record["date"])
        for num, z_name in num_to_zodiac.items():
            if z_name in zodiac_to_nums:
                zodiac_to_nums[z_name].append(num)
    elif hasattr(analyzer, "zodiac_map"):
        num_to_zodiac = analyzer.zodiac_map
        for num, z_name in num_to_zodiac.items():
            if z_name in zodiac_to_nums:
                zodiac_to_nums[z_name].append(num)
    else:
        base_zodiac = "马"
        idx = zodiac_order.index(base_zodiac)
        aligned_zodiacs = zodiac_order[idx:] + zodiac_order[:idx]
        for i in range(1, 50):
            z_name = aligned_zodiacs[(i - 1) % 12]
            zodiac_to_nums[z_name].append(i)
            num_to_zodiac[i] = z_name

    # ------------------------------------------------------------------------
    # 🔥 核心特征提取：计算最新一期的开奖生肖及【生肖多样性】
    # ------------------------------------------------------------------------
    last_nums = last_record["numbers"]
    last_z_list = [num_to_zodiac.get(n, "未知") for n in last_nums]
    last_z_set = set(last_z_list)

    # 🌟 特征形态 2：计算每期生肖多样性数量（去重后的生肖个数）
    current_diversity = len(last_z_set)

    # ------------------------------------------------------------------------
    # 3. 智能化报告输出：正式排名只读取严格滚动报告
    # ------------------------------------------------------------------------
    probability_ranking = top6_report["latest"]["ranking"]
    sorted_zodiacs = [
        (item["zodiac"], round(item["probability"] * 100, 2))
        for item in probability_ranking
    ]
    tier_hot = list(top6_report["latest"]["top6"])
    tier_mid = [zodiac for zodiac, _ in sorted_zodiacs if zodiac not in tier_hot]

    latest_issue_num = last_record["issue"]
    try:
        next_issue = f"{int(latest_issue_num) + 1:03d}"
    except ValueError:
        next_issue = "下一"

    output = []
    output.append("==================================================")
    output.append(f"   ★ LHC 第 {next_issue} 期全闭环自动智能推荐报告 ★")
    output.append("==================================================")
    output.append(
        f"最新一期开奖 (第 {latest_issue_num} 期) : {last_nums} -> {last_z_list}"
    )
    output.append(
        f"💡 【特征形态分析】: 本期开奖生肖去重后，独特多样性数量为: 【{current_diversity}】"
    )
    if current_diversity <= 4:
        output.append(
            "   ==> 形态评估：生肖多样性较低（集中度高）；正式概率仍只采用已通过门禁的滚动特征。"
        )
    else:
        output.append(
            "   ==> 形态评估：生肖多样性较为分散；不会额外套用未经回测的连庄加减分。"
        )
    output.append(
        f"推演引擎生成时间 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )

    # 【🔴 第一板块：生肖多梯度组合推荐】
    output.append("【🔴 第一板块：生肖多梯度组合推荐】")
    output.append(
        f"  🔥 核心精选生肖组合 (重磅主攻) : {', '.join([f'【{z}】' for z in tier_hot])}"
    )
    output.append(
        f"  ⚖️ 稳健防守生肖组合 (次要防守) : {', '.join([f'【{z}】' for z in tier_mid])}"
    )
    deployed_kills = [
        item["target"] for item in top6_report["latest"]["hard_kill_candidates"]
    ]
    output.append(
        "  🛑 硬绝杀生肖 : "
        + (
            "、".join(f"【{zodiac}】" for zodiac in deployed_kills)
            if deployed_kills
            else "无（多查找器共识与双层零误杀门禁未同时通过）"
        )
    )
    output.append("  --------------------------------------------------")
    holdout = top6_report["holdout"]
    output.append(
        f"  📊 2024–2026隔离回测：去重生肖中5率 "
        f"{holdout['unique_hit5_eligible_rate']:.2%}；"
        f"7个号码位置覆盖至少5个 {holdout['ball_hit5_rate']:.2%}。"
    )
    output.append(
        f"  🎚️ F5轨迹断层开关：{'开启' if top6_report['f5_enabled'] else '关闭'}；"
        f"{top6_report['f5_effect_reason']}。"
    )
    output.append(
        f"  🧪 F5历史门禁：{'通过' if top6_report['f5_gate_passed'] else '未通过'}；"
        f"关闭Top6={'、'.join(top6_report['latest']['f5_off_top6'])}；"
        f"开启Top6={'、'.join(top6_report['latest']['f5_on_top6'])}。"
    )
    output.append(
        f"  🔗 F6/F7去偏关联："
        f"{'已通过门禁' if top6_report['f67_feature_deployed'] else '未通过门禁，未进入正式排名'}；"
        f"{top6_report['f67_gate_reason']}；不执行打包推荐或排除。"
    )
    joint = top6_report["joint_candidate_holdout_audit"]
    joint_reference = top6_report["joint_reference_holdout"]
    output.append(
        f"  🧩 F1–F7联合模型："
        f"{'已上线' if top6_report['joint_feature_deployed'] else '未上线'}；"
        f"隔离期中5 {joint['unique_hit5']}/{joint['eligible_periods']} "
        f"（现行 {joint_reference['unique_hit5']}/{joint_reference['eligible_periods']}）；"
        f"{top6_report['joint_gate_reason']}。"
    )
    output.append(
        f"  🛡️ F2硬绝杀门禁："
        f"{'开启' if top6_report['hard_kill_policy_deployed'] else '关闭'}；"
        "需至少3个独立查找器看空、2个强看空、无反向证据，"
        "并在验收期和隔离期各至少触发30次且零误杀。"
    )
    incremental = top6_report.get("incremental_update")
    if incremental:
        mode_label = {
            "full_rebuild": "全量初始化",
            "incremental_append": "只处理新增期",
            "cache_reused": "复用当前检查点",
        }.get(incremental["mode"], incremental["mode"])
        output.append(
            f"  ⚡ 数据更新模式：{mode_label}；"
            f"检查点 {incremental['previous_record_count']}→"
            f"{incremental['current_record_count']} 期；"
            f"追加校验={'通过' if incremental['append_validation_passed'] else '失败'}。"
        )
        for detail in incremental.get("appended_details", []):
            output.append(
                f"     新增第{detail['issue']}期 {detail['date']}："
                f"{detail['numbers']}；农历生肖年{detail['zodiac_year']}，"
                f"本命生肖【{detail['base_zodiac']}】。"
            )
    f3_latest = top6_report["latest"]["f3"]
    f3_holdout = top6_report["f3_diversity_holdout"]
    output.append(
        f"  🎲 下一期去重生肖数正式推定："
        f"{f3_latest['deployed_next_diversity']}种；"
        f"F3去重数候选隔离期精确率 {f3_holdout['exact_rate']:.2%}，"
        f"滚动众数基线 {f3_holdout['rolling_mode_baseline_exact_rate']:.2%}；"
        f"{'F3已上线' if top6_report['f3_diversity_feature_deployed'] else 'F3未过门禁，正式值使用滚动基线'}。"
    )
    output.append("  📊 下一期生肖出现概率与升降分解释：")
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
    ranking_lookup = {item["zodiac"]: item for item in probability_ranking}
    strength_report = top6_report["latest"]["signal_strength"]
    for z, score in sorted_zodiacs:
        item = ranking_lookup[z]
        baseline = item["components"]["baseline"]
        net_adjustment = item["probability"] - baseline
        drivers = [
            signal
            for signal in strength_report[z]
            if abs(signal["score_contribution"]) >= 0.00005
        ][:3]
        driver_text = "、".join(
            f"{feature_labels.get(signal['feature'], signal['feature'])}"
            f"{signal['score_contribution']:+.2%}"
            f"({tier_labels.get(signal['tier'], signal['tier'])})"
            for signal in drivers
        ) or "无显著调整"
        output.append(
            f"    * 【{z}】: {score:.2f}% | 基线 {baseline:.2%} | "
            f"净调整 {net_adjustment:+.2%} | {driver_text}"
        )

    # 【🔵 第二板块：号码精选矩阵推荐】
    output.append("\n【🔵 第二板块：号码精选矩阵推荐】")
    hot_nums = []
    for z in tier_hot:
        hot_nums.extend(zodiac_to_nums.get(z, []))
    hot_nums = sorted(list(set(hot_nums)))

    mid_nums = []
    for z in tier_mid:
        mid_nums.extend(zodiac_to_nums.get(z, []))
    mid_nums = sorted(list(set(mid_nums)))

    space_core = [15, 16, 17, 18]
    target_filter = [11, 23, 35, 47, 2, 14, 26, 38, 8, 20, 32, 44]
    premium_hot_nums = [n for n in hot_nums if n in space_core or n in target_filter]
    premium_hot_nums = sorted(list(set(premium_hot_nums)))

    output.append("  🎯 【主攻核心特码弹药库】(源于核心生肖，爆发率最高)：")
    output.append("    ==> " + " ".join([f"{n:02d}" for n in premium_hot_nums]))

    output.append("\n  🎯 【全盘防守特码大底】(核心生肖号源全开)：")
    output.append("    ==> " + " ".join([f"{n:02d}" for n in hot_nums]))

    output.append("\n  📐 【空间拦截定胆参考】(区间 10-19 绝不断档之黄金槽码)：")
    output.append("    ==> " + " ".join([f"{n:02d}" for n in space_core]))

    output.append("\n  🛡️ 【平稳防守兜底号源】(防守生肖对应号码)：")
    output.append("    ==> " + " ".join([f"{n:02d}" for n in mid_nums]))

    final_report = "\n".join(output)
    print(final_report)

    output_path = os.path.join(
        SCRIPT_DIR,
        "final_auto_prediction_f5_on.txt"
        if f5_enabled
        else "final_auto_prediction.txt",
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_report)
    print(
        f"\n[🎉 完美闭环] 严格滚动多特征新版预测已写入: {output_path}"
    )


if __name__ == "__main__":
    auto_engine_prediction()
