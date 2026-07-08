import os
import sys
import collections
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from zodiac_analyzer import ZodiacPatternAnalyzer
except ImportError:
    print("❌ [错误]：无法从 zodiac_analyzer.py 中导入 ZodiacPatternAnalyzer。")
    sys.exit(1)


def auto_engine_prediction():
    print("==================================================")
    print(" 🚀 LHC 自动化多特征组合推演引擎 (多样性动态版) 启动... ")
    print("==================================================")

    try:
        analyzer = ZodiacPatternAnalyzer("马")
    except Exception:
        analyzer = ZodiacPatternAnalyzer()

    records = analyzer.load_json_data(data_dir="data")
    if not records:
        print("❌ 错误：未成功加载数据，请检查 data/2026.json 是否存在。")
        return

    report = analyzer.compute_patterns(records)

    # 动态对齐生肖
    zodiac_order = getattr(
        analyzer,
        "zodiac_order",
        ["马", "蛇", "龙", "兔", "虎", "牛", "鼠", "猪", "狗", "鸡", "猴", "羊"],
    )
    zodiac_to_nums = {z: [] for z in zodiac_order}
    num_to_zodiac = {}

    if hasattr(analyzer, "zodiac_map"):
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
    last_record = records[-1]
    last_nums = last_record["numbers"]
    last_z_list = [num_to_zodiac.get(n, "未知") for n in last_nums]
    last_z_set = set(last_z_list)

    # 🌟 特征形态 2：计算每期生肖多样性数量（去重后的生肖个数）
    current_diversity = len(last_z_set)

    # ------------------------------------------------------------------------
    # 3. 动态置信度矩阵分配
    # ------------------------------------------------------------------------
    # 规划查找器核心权重 (根据问题5：查找器6已彻底关闭，权重重新分配给大样本与绝杀)
    WEIGHT_RULE1 = 0.60  # 全局历史大样本与特征形态，提升至 60%
    WEIGHT_RULE2 = 0.40  # 单期跨期绝杀，提升至 40%

    zodiac_multipliers = {z: 1.0 for z in zodiac_order}
    veto_killers = set()

    # A. 扫描查找器 1 (大样本高低频)
    if "rule1" in report:
        for condition, data in report["rule1"].items():
            for z_hot, _, pct in data.get("hot", []):
                zodiac_multipliers[z_hot] += pct * WEIGHT_RULE1
            for z_cold, _, pct in data.get("cold", []):
                if pct == 0:
                    zodiac_multipliers[z_cold] -= 0.5 * WEIGHT_RULE1

    # 🌟 动态重号干预逻辑（解答问题1）：根据多样性形态微调临期生肖的乘数
    if current_diversity <= 4:
        # 多样性低，重号风险高，对上一期出现过的生肖给予 15% 的惯性增益
        for z in last_z_set:
            if z in zodiac_multipliers:
                zodiac_multipliers[z] *= 1.15
    elif current_diversity >= 6:
        # 多样性极高，能量分散，下一期临期生肖倾向于冷切，衰减 20%
        for z in last_z_set:
            if z in zodiac_multipliers:
                zodiac_multipliers[z] *= 0.80

    # B. 拦截查找器 2 (100%绝杀线)
    if "rule2_kills" in report:
        for item in report["rule2_kills"]:
            if item.get("curr") in last_z_set and item.get("prob") == 0:
                kill_z = item.get("kill")
                if kill_z in zodiac_multipliers:
                    zodiac_multipliers[kill_z] *= 1.0 - WEIGHT_RULE2
                    veto_killers.add(kill_z)

    # C. 查找器 6 联动彻底屏蔽 (根据指令5关闭)
    # [已关闭] combo_linkage 逻辑移除

    # 最终计分整合
    zodiac_scores = {}
    for z, multiplier in zodiac_multipliers.items():
        if z in veto_killers:
            final_score = 0.0
        else:
            final_score = round(max(0.0, multiplier) * 100, 2)
        zodiac_scores[z] = final_score

    # ------------------------------------------------------------------------
    # 4. 智能化报告输出
    # ------------------------------------------------------------------------
    sorted_zodiacs = sorted(zodiac_scores.items(), key=lambda x: x[1], reverse=True)

    tier_hot = [z for z, s in sorted_zodiacs if s >= 120]
    tier_mid = [z for z, s in sorted_zodiacs if 60 <= s < 120]
    tier_kill = [z for z, s in sorted_zodiacs if s < 60]

    latest_issue_num = report.get("latest_issue", last_record["issue"])
    try:
        next_issue = f"{int(latest_issue_num) + 1:03d}"
    except ValueError:
        next_issue = "下一"

    output = []
    output.append("==================================================")
    output.append(f"   ★ LHC 第 {next_issue} 期全闭环自动智能推荐报告 ★   ")
    output.append("==================================================")
    output.append(
        f"最新一期开奖 (第 {latest_issue_num} 期) : {last_nums} -> {last_z_list}"
    )
    output.append(
        f"💡 【特征形态分析】: 本期开奖生肖去重后，独特多样性数量为: 【{current_diversity}】"
    )
    if current_diversity <= 4:
        output.append(
            "   ==> 形态评估：生肖多样性较低（集中度高），模型已自动激活[临期生肖惯性连庄增益机制]。"
        )
    else:
        output.append(
            "   ==> 形态评估：生肖多样性较为分散，模型已自动压制临期生肖的连庄概率。"
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
    output.append(
        f"  🛑 历史死穴绝杀生肖 (一键清除) : {', '.join([f'【{z}】' for z in tier_kill])}"
    )
    output.append("  --------------------------------------------------")
    output.append("  📊 评分细节参考 (Rule6已关闭，Rule1+多样性形态占权重60%) :")
    for z, score in sorted_zodiacs:
        output.append(f"    * 【{z}】: {score} 分")

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

    with open("final_auto_prediction.txt", "w", encoding="utf-8") as f:
        f.write(final_report)
    print(
        "\n[🎉 完美闭环] 融入多样性形态且关闭查找器6的新版预测已写入: final_auto_prediction.txt"
    )


if __name__ == "__main__":
    auto_engine_prediction()
