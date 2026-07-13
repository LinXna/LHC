import os
import json
import logging
import collections
from itertools import combinations

logger = logging.getLogger(__name__)

# =========================
# 分析器全局常量
# =========================

# 一期开奖号码数量（6个正码 + 1个特别号）
DRAW_SIZE = 7

# 十二生肖数量
ZODIAC_COUNT = 12

# 合法号码范围
MIN_NUMBER = 1
MAX_NUMBER = 49

# 查找器7最少需要历史期数
MIN_HISTORY_PERIODS = 4

# 热门阈值（10%）
HOT_RATE_THRESHOLD = 0.10

# 默认返回结构
EMPTY_RULE_RESULT = {}

EMPTY_RESULT = {
    "total": 0,
    "rule1": {},
    "rule2": {},
    "rule3": {},
    "rule4": {},
    "rule5": {},
    "rule6": {},
    "rule7": {},
    "score": {},
}

class ZodiacPatternAnalyzer:
    def __init__(self, base_zodiac="马"):
        self.zodiac_order = [
            "马",
            "蛇",
            "龙",
            "兔",
            "虎",
            "牛",
            "鼠",
            "猪",
            "狗",
            "鸡",
            "猴",
            "羊",
        ]
        self.zodiac_cycle = self.zodiac_order  # 补齐循环别名
        self.zodiac_map = self._build_map(base_zodiac)

    def _build_map(self, base_zodiac):
        idx = self.zodiac_order.index(base_zodiac)
        aligned = self.zodiac_order[idx:] + self.zodiac_order[:idx]
        return {i: aligned[(i - 1) % 12] for i in range(MIN_NUMBER, MAX_NUMBER + 1)}

    def load_json_data(self, file_path=None, data_dir="data"):

        all_records = []

        # 如果指定文件，只读取指定文件
        if file_path:
            target_files = [file_path]

        else:
            if not os.path.exists(data_dir):
                return []

            target_files = [
                os.path.join(data_dir, f)
                for f in os.listdir(data_dir)
                if f.endswith(".json")
            ]

        for path in target_files:

            try:
                with open(path, "r", encoding="utf-8") as f:

                    payload = json.load(f)

                    body_list = (
                        payload.get("result", {}).get("data", {}).get("bodyList", [])
                    )

                    for item in body_list:

                        code_str = item.get("preDrawCode")

                        if not code_str:
                            continue

                        nums = [
                            int(x.strip()) for x in code_str.split(",") if x.strip()
                        ]

                        if len(nums) == 7:

                            all_records.append(
                                {
                                    "issue": item.get("issue"),
                                    "date": item.get("preDrawDate"),
                                    "numbers": nums,
                                }
                            )

            except Exception as e:
                print(f"【警告】读取文件 {path} 错误: {e}")

            # 统一按照期号排序
            all_records.sort(
                key=lambda x: int(x["issue"]) if x["issue"] is not None else 0
            )

        return all_records

    # 增加通用联合统计函数
    def build_zodiac_relation_rule(
        self, relation_source, size=2, hot_threshold=0.12, cold_zero=False
    ):

        result = {}

        for (div_cnt, relation), next_list in relation_source.items():

            counts = collections.Counter(next_list)

            total = len(next_list)

            if total == 0:
                continue

            hot = [
                (z, c, c / total)
                for z, c in counts.items()
                if c / total >= hot_threshold
            ]

            hot.sort(key=lambda x: x[1], reverse=True)

            if cold_zero:

                cold = [
                    (z, counts.get(z, 0), 0)
                    for z in self.zodiac_order
                    if counts.get(z, 0) == 0
                ]

            else:

                cold = [
                    (z, counts.get(z, 0), counts.get(z, 0) / total)
                    for z in self.zodiac_order
                    if counts.get(z, 0) / total < 0.05
                ]

            result[(div_cnt, relation)] = {
                "periods": total // 7,
                "hot": hot,
                "cold": cold,
            }

        return result

    # 🌟 名字锁死为 compute_patterns，彻底解决报错！
    def compute_patterns(self, sorted_records):
        if not sorted_records:
            return {}

        total_periods = len(sorted_records)

        if total_periods < MIN_HISTORY_PERIODS:
            return {
                "total": total_periods,
                "warning": "历史数据不足，无法执行统计分析。",
                "rule1": {},
                "rule2": {},
                "rule3": {},
                "rule4": {},
                "rule5": {},
                "rule6": {},
                "rule7": {},
                "rule1_pairs": {},
                "rule1_triplets": {},
                "rule2_kills": [],
                "rule3_report": {},
                "top_special_expanded": [],
                "top_15_pairs": [],
                "bottom_15_pairs": [],
                "combo_linkage": [],
                "reverse_trace": [],
                "trace_recovery": {},
                "zodiac_score": {},
                "zodiac_ranking": [],
                "timeline": {},
                "score": {},
            }

        history_data = []

        for record in sorted_records:
            if not isinstance(record, dict):
                continue
            nums = record.get("numbers")
            if not isinstance(nums, list):
                continue
            if len(nums) != DRAW_SIZE:
                continue
            history_data.append(nums)

        # 重新统计有效数据数量
        total_periods = len(history_data)

        if total_periods < MIN_HISTORY_PERIODS:
            return {
                "total": total_periods,
                "warning": "有效历史数据不足，无法执行统计分析。",
                "rule1": {},
                "rule2": {},
                "rule3": {},
                "rule4": {},
                "rule5": {},
                "rule6": {},
                "rule7": {},
                "rule1_pairs": {},
                "rule1_triplets": {},
                "rule2_kills": [],
                "rule3_report": {},
                "top_special_expanded": [],
                "top_15_pairs": [],
                "bottom_15_pairs": [],
                "combo_linkage": [],
                "reverse_trace": [],
                "trace_recovery": {},
                "zodiac_score": {},
                "zodiac_ranking": [],
                "timeline": {},
                "score": {},
            }

        # 基础生肖矩阵转化
        zodiac_matrix = []

        for group in history_data:
            try:
                zodiac_matrix.append([self.zodiac_map[n] for n in group])
            except (KeyError, TypeError) as e:
                logger.warning(f"生肖映射失败，已跳过一条记录：{e}")
                continue

        # 再次确认生肖矩阵数据足够
        total_periods = len(zodiac_matrix)

        if total_periods < MIN_HISTORY_PERIODS:
            return {
                "total": total_periods,
                "warning": "有效生肖数据不足，无法执行统计分析。",
                "rule1": {},
                "rule2": {},
                "rule3": {},
                "rule4": {},
                "rule5": {},
                "rule6": {},
                "rule7": {},
                "rule1_pairs": {},
                "rule1_triplets": {},
                "rule2_kills": [],
                "rule3_report": {},
                "top_special_expanded": [],
                "top_15_pairs": [],
                "bottom_15_pairs": [],
                "combo_linkage": [],
                "reverse_trace": [],
                "trace_recovery": {},
                "zodiac_score": {},
                "zodiac_ranking": [],
                "timeline": {},
                "score": {},
            }

        total_valid_p = max(total_periods - 1, 1)

        # =========================================================================
        # 查找器7：前三期轨迹回补规则
        # =========================================================================

        trace_recovery = collections.defaultdict(list)

        for i in range(MIN_HISTORY_PERIODS - 1, total_periods - 1):

            last1 = set(zodiac_matrix[i - 1])
            last2 = set(zodiac_matrix[i - 2])
            last3 = set(zodiac_matrix[i - 3])
            curr = set(zodiac_matrix[i])

            # 前两期连续出现，本期消失
            disappeared = (last1 & last2) - curr

            if not disappeared:
                continue

            next_period = zodiac_matrix[i + 1]

            for z in disappeared:
                trace_recovery[z].extend(next_period)

        trace_recovery_report = {}

        for z, pool in trace_recovery.items():

            counts = collections.Counter(pool)

            total = len(pool)

            if total == 0:
                continue

            hot = []

            for name, cnt in counts.items():

                rate = cnt / total

                if rate >= HOT_RATE_THRESHOLD:

                    hot.append((name, cnt, rate))

            hot.sort(key=lambda x: x[2], reverse=True)

            trace_recovery_report[z] = {"samples": total // 7, "hot": hot}

        # =========================================================================
        # 统一生肖评分池（V6.2）
        # =========================================================================

        zodiac_score = {
            z: {
                "score": 0,
                "reasons": [],
                "confidence": 0,
            }
            for z in self.zodiac_order
        }

        def add_score(zodiac, score, reason, confidence=1):
            """统一加权接口"""

            if zodiac not in zodiac_score:
                return

            zodiac_score[zodiac]["score"] += score
            zodiac_score[zodiac]["confidence"] += confidence
            zodiac_score[zodiac]["reasons"].append(reason)

        # =========================================================================
        # 1 & 2. 查找器 1 升级：单生肖交叉 + 二次生肖对高阶联合联合排查
        # =========================================================================
        diversity_history = [len(set(z_list)) for z_list in zodiac_matrix]
        # 🌟 新增：多生肖对高阶交叉大池
        rule1_detail = collections.defaultdict(list)
        rule1_pair_detail = collections.defaultdict(list)
        rule1_triplet_detail = collections.defaultdict(list)

        # 📈 【严谨升级项】：精密拆解大底
        repeat_stats_by_div = collections.defaultdict(
            lambda: {
                "total_cases": 0,
                "repeated_cases": 0,
                "repeat_counts": {1: 0, 2: 0, 3: 0, 4: 0},
            }
        )

        for i in range(total_valid_p):
            curr_z_set = set(zodiac_matrix[i])
            curr_div = diversity_history[i]
            next_z_list = zodiac_matrix[i + 1]
            next_z_set = set(next_z_list)

            # 统计重号大底规律
            intersect = curr_z_set.intersection(next_z_set)
            intersect_cnt = len(intersect)

            repeat_stats_by_div[curr_div]["total_cases"] += 1
            if intersect_cnt > 0:
                repeat_stats_by_div[curr_div]["repeated_cases"] += 1
                if intersect_cnt in repeat_stats_by_div[curr_div]["repeat_counts"]:
                    repeat_stats_by_div[curr_div]["repeat_counts"][intersect_cnt] += 1

            # A. 单生肖交叉
            for z in curr_z_set:
                rule1_detail[(curr_div, z)].extend(next_z_list)

            # B. 🌟 核心增补两两组合
            for z_pair in combinations(sorted(list(curr_z_set)), 2):
                rule1_pair_detail[(curr_div, z_pair)].extend(next_z_list)

            # C. 三生肖联合规则
            for z_triplet in combinations(sorted(list(curr_z_set)), 3):
                rule1_triplet_detail[(curr_div, z_triplet)].extend(next_z_list)
        # 整理单生肖报告
        rule1_report = {}
        for (div_cnt, z), nxt_list in rule1_detail.items():
            counts = collections.Counter(nxt_list)
            total_next = len(nxt_list)
            hot_z = [
                (zn, c, c / total_next)
                for zn, c in counts.items()
                if (c / total_next) >= 0.10
            ]
            hot_z.sort(key=lambda x: x[1], reverse=True)

            # 高频生肖加分
            for z_name, cnt, pct in hot_z:

                if pct >= 0.15:
                    add_score(z_name, 3, f"查找器1 高频({pct:.1%})", total_next // 7)

                elif pct >= 0.10:
                    add_score(z_name, 2, f"查找器1 热点({pct:.1%})", total_next // 7)

            cold_z = [
                (z_all, counts.get(z_all, 0), counts.get(z_all, 0) / total_next)
                for z_all in self.zodiac_order
                if (counts.get(z_all, 0) / total_next) < 0.05
            ]
            cold_z.sort(key=lambda x: x[2])

            # ===== 冰点减分 =====
            for z_name, cnt, pct in cold_z:

                if pct == 0:

                    add_score(z_name, -4, "查找器1 绝对冰点", total_next // 7)

                elif pct < 0.03:

                    add_score(z_name, -2, f"查找器1 冷门({pct:.1%})", total_next // 7)

            morphology_type = "正常形态"
            if div_cnt <= 3:
                morphology_type = "低多样性聚集形态"
            elif div_cnt >= 6:
                morphology_type = "高多样性饱和形态"

            rule1_report[f"当期多样性[{div_cnt}种生肖]且含【{z}】"] = {
                "periods": total_next // 7,
                "morphology": morphology_type,
                "hot": hot_z,
                "cold": cold_z,
            }

        # 整理高阶生肖对报告
        rule1_pair_report = self.build_zodiac_relation_rule(
            rule1_pair_detail, size=2, hot_threshold=0.12, cold_zero=True
        )

        rule1_triplet_report = self.build_zodiac_relation_rule(
            rule1_triplet_detail, size=3, hot_threshold=0.12, cold_zero=True
        )

        # 📊 注入升级后的1~4细分字典
        diversity_repeat_rule = {
            div: {
                "total_occur": stat["total_cases"],
                "repeat_rate": (
                    stat["repeated_cases"] / stat["total_cases"]
                    if stat["total_cases"] > 0
                    else 0.0
                ),
                "repeat_counts": stat["repeat_counts"],
            }
            for div, stat in repeat_stats_by_div.items()
        }

        # =========================================================================
        # 3. 基础伴生矩阵
        # =========================================================================
        pair_period_dist = collections.Counter()
        for g in zodiac_matrix:
            for pair in combinations(sorted(list(set(g))), 2):
                pair_period_dist[pair] += 1
        top_15_pairs = [
            (pair, freq, freq / total_periods)
            for pair, freq in pair_period_dist.most_common(15)
        ]
        bottom_15_pairs = [
            (pair, freq, freq / total_periods)
            for pair, freq in pair_period_dist.most_common()[:-16:-1]
        ]

        # =========================================================================
        # 4. 查找器 2：微观强力杀号过滤器
        # =========================================================================
        single_cross_kills = []

        for z_curr in self.zodiac_order:

            idx_list = [i for i in range(total_valid_p) if z_curr in zodiac_matrix[i]]

            # 样本不足，不进入杀号池
            if len(idx_list) < 20:
                continue

            next_pool = []

            for idx in idx_list:
                next_pool.extend(zodiac_matrix[idx + 1])

            # 下一期生肖总数量
            next_total = len(next_pool)

            if next_total == 0:
                continue

            # 统计下一期生肖频次
            counts = collections.Counter(next_pool)

            for z_next in self.zodiac_order:

                prob = counts.get(z_next, 0) / next_total

                if prob <= 0.05:

                    single_cross_kills.append(
                        {
                            "curr": z_curr,
                            "kill": z_next,
                            "prob": prob,
                            "trigger_p": len(idx_list),
                        }
                    )

        single_cross_kills.sort(key=lambda x: (x["prob"], -x["trigger_p"]))

        # =========================================================================
        # 5. 查找器 3：十进制区间空间局限性矩阵
        # =========================================================================
        ranges_config = {
            "0-9": (1, 9),
            "10-19": (10, 19),
            "20-29": (20, 29),
            "30-39": (30, 39),
            "40-49": (40, 49),
        }
        rule3_report = {}
        for r_label, (r_min, r_max) in ranges_config.items():
            r_trig_p = 0
            slots_linkage = collections.defaultdict(
                lambda: {
                    "total": 0,
                    "in_range": 0,
                    "out_greater": 0,
                    "out_less": 0,
                    "no_hit": 0,
                }
            )
            for i in range(total_valid_p):
                curr_nums = history_data[i]
                next_nums = history_data[i + 1]
                in_range_nums = sorted([n for n in curr_nums if r_min <= n <= r_max])
                if len(in_range_nums) == 2:
                    r_trig_p += 1
                    n1, n2 = in_range_nums[0], in_range_nums[1]
                    available_in = [n for n in range(n1 + 1, n2)]
                    available_greater = [n for n in range(n2 + 1, r_max + 1)]
                    available_less = [n for n in range(r_min, n1)]
                    slots_count = len(available_in)
                    slots_linkage[slots_count]["total"] += 1
                    hit_nums = [n for n in next_nums if r_min <= n <= r_max]
                    if not hit_nums:
                        slots_linkage[slots_count]["no_hit"] += 1
                    else:
                        is_in = any(h_n in available_in for h_n in hit_nums)
                        is_greater = any(h_n in available_greater for h_n in hit_nums)
                        is_less = any(h_n in available_less for h_n in hit_nums)
                        if is_in:
                            slots_linkage[slots_count]["in_range"] += 1
                        if is_greater:
                            slots_linkage[slots_count]["out_greater"] += 1
                        if is_less:
                            slots_linkage[slots_count]["out_less"] += 1
                        if not (is_in or is_greater or is_less):
                            slots_linkage[slots_count]["no_hit"] += 1
            rule3_report[r_label] = {"periods": r_trig_p, "slots": dict(slots_linkage)}

        # =========================================================================
        # 6. 查找器 4 升级：引入动态时间轴数据隔离（加入实时进度条打印）
        # =========================================================================
        special_expanded = []
        EXT_PERIODS = 5

        print("\n⏳ 正在深度解构 查找器 4（特码隔离特征矩阵）...")

        # 优化：提前转换为集合，加速查找速度
        history_sets = [set(nums) for nums in history_data]
        for target_idx in range(total_periods):
                # 📢 增加进度打印：每处理 10% 的数据就给你汇报一次，让你知道程序活得好好的
                if target_idx % max(1, total_periods // 10) == 0:
                    percent = (target_idx / total_periods) * 100
                    print(
                        f"   [进度反馈] 特征矩阵已洗出 {percent:.0f}% ... 引擎正常轰鸣中"
                    )

                curr_nums_set = history_data[target_idx]
                for num in curr_nums_set:
                    appear_count = 0
                    bias_trigger_count = 0
                    target_zodiac_pool = []

                    odd_c = 0
                    even_c = 0
                    big_c = 0
                    small_c = 0
                    tail_dist = collections.defaultdict(int)
                    total_future_numbers = 0

                    # 限制向后扫描的边界
                    # 时间隔离：
                    # 当前样本只能使用它之前已经发生的数据
                    scan_limit = target_idx - EXT_PERIODS

                    if scan_limit <= 0:
                        continue
                    for hist_i in range(scan_limit):
                        # 优化：哈希集合查找，远快于原始的 in list
                        if num in history_sets[hist_i]:
                            appear_count += 1

                            # 批量抽取未来 5 期的生肖和号码
                            f_zodiacs = []
                            f_nums = []
                            for offset in range(1, EXT_PERIODS + 1):
                                f_zodiacs.extend(zodiac_matrix[hist_i + offset])
                                f_nums.extend(history_data[hist_i + offset])

                            z_counts = collections.Counter(f_zodiacs)
                            top_z, top_zc = (
                                z_counts.most_common(1)[0] if z_counts else ("无", 0)
                            )
                            if top_zc >= 6:
                                bias_trigger_count += 1
                                target_zodiac_pool.append(top_z)

                            for fn in f_nums:
                                total_future_numbers += 1
                                if fn % 2 == 0:
                                    even_c += 1
                                else:
                                    odd_c += 1
                                if fn >= 25:
                                    big_c += 1
                                else:
                                    small_c += 1
                                tail_dist[fn % 10] += 1

                    if appear_count >= 1:
                        b_rate = bias_trigger_count / appear_count
                        most_z = (
                            collections.Counter(target_zodiac_pool).most_common(1)[0][0]
                            if target_zodiac_pool
                            else "无"
                        )
                        tot_fn = total_future_numbers if total_future_numbers > 0 else 1

                        top_tails = sorted(
                            tail_dist.items(), key=lambda x: x[1], reverse=True
                        )[:2]

                        behavior_rule = {
                            "odd_ratio": round((odd_c / tot_fn) * 100, 1),
                            "big_ratio": round((big_c / tot_fn) * 100, 1),
                            "hot_tails": [f"{t}尾" for t, _ in top_tails],
                        }

                        if not any(x[0] == num for x in special_expanded):
                            special_expanded.append(
                                (
                                    num,
                                    b_rate * 100,
                                    b_rate,
                                    most_z,
                                    appear_count,
                                    behavior_rule,
                                )
                            )

        special_expanded.sort(key=lambda x: x[1], reverse=True)
        print("   [进度反馈] 100% 毫无保留！特码隔离特征矩阵全部清洗完毕。")

        # =========================================================================
        # 7. 查找器 7：前三期生肖轨迹断层回补矩阵
        # =========================================================================

        print("\n⏳ 正在深度解构 查找器 7（三期生肖轨迹回补矩阵）...")

        trace_recovery = {
            "prev1_missing": {},
            "prev2_missing": {},
            "prev3_missing": {},
            "multi_gap": {},
        }

        # -------------------------------
        # 规则1:
        # 上一期出现，本期消失 -> 下一期回补概率
        # -------------------------------

        for gap_type, gap_size in [
            ("prev1_missing", 1),
            ("prev2_missing", 2),
            ("prev3_missing", 3),
        ]:

            trigger_pool = collections.defaultdict(list)

            for i in range(gap_size, total_valid_p):

                history_z = []

                # 收集前 N 期
                for back in range(1, gap_size + 1):
                    history_z.extend(zodiac_matrix[i - back])

                current_set = set(zodiac_matrix[i])
                next_set = set(zodiac_matrix[i + 1])

                # 前N期出现，但是当前消失
                missing_z = set(history_z) - current_set

                for z in missing_z:
                    trigger_pool[z].append(1 if z in next_set else 0)

            result = {}

            for z, values in trigger_pool.items():

                total = len(values)

                if total < 10:
                    continue

                hit = sum(values)

                result[z] = {"trigger": total, "recover": hit, "rate": hit / total}

            trace_recovery[gap_type] = result

        # -------------------------------
        # 规则2:
        # 前三期累计出现，本期全部消失
        # -------------------------------

        multi_trigger = collections.defaultdict(list)

        for i in range(3, total_valid_p):

            prev_three = []

            for back in range(1, 4):
                prev_three.extend(zodiac_matrix[i - back])

            prev_set = set(prev_three)

            current_set = set(zodiac_matrix[i])

            next_set = set(zodiac_matrix[i + 1])

            disappear = prev_set - current_set

            for z in disappear:

                multi_trigger[z].append(1 if z in next_set else 0)

        multi_result = {}

        for z, values in multi_trigger.items():

            total = len(values)

            if total < 10:
                continue

            multi_result[z] = {
                "trigger": total,
                "recover": sum(values),
                "rate": sum(values) / total,
            }

        trace_recovery["multi_gap"] = multi_result

        print("   [进度反馈] 查找器7 三期轨迹回补矩阵完成。")

        # =========================================================================
        # 7. 查找器 6 深度关闭
        # =========================================================================
        combo_clash_rules = []

        # =========================================================================
        # 7. 查找器7：跨期时间轴演化引擎（V2）
        # =========================================================================

        timeline_report = {}

        # ----------------------------------------------------------
        # 规则1：上一期出现 -> 本期断档 -> 下一期是否回补
        # ----------------------------------------------------------

        timeline_rule1 = collections.defaultdict(
            lambda: {
                "trigger": 0,
                "return": 0,
            }
        )

        # ----------------------------------------------------------
        # 规则2：连续2期出现 -> 本期断档 -> 下一期是否回补
        # ----------------------------------------------------------

        timeline_rule2 = collections.defaultdict(
            lambda: {
                "trigger": 0,
                "return": 0,
            }
        )

        for i in range(2, total_periods - 1):

            prev_set = set(zodiac_matrix[i - 1])
            curr_set = set(zodiac_matrix[i])
            next_set = set(zodiac_matrix[i + 1])

            for z in self.zodiac_order:

                # 上一期有，本期没有
                if z in prev_set and z not in curr_set:

                    timeline_rule1[z]["trigger"] += 1

                    if z in next_set:
                        timeline_rule1[z]["return"] += 1

                # 连续2期都有，本期断档
                if (
                    z in set(zodiac_matrix[i - 2])
                    and z in prev_set
                    and z not in curr_set
                ):

                    timeline_rule2[z]["trigger"] += 1

                    if z in next_set:
                        timeline_rule2[z]["return"] += 1

        timeline_report["prev_miss_return"] = {}

        for z, stat in timeline_rule1.items():

            if stat["trigger"] == 0:
                continue

            timeline_report["prev_miss_return"][z] = {
                "trigger": stat["trigger"],
                "return": stat["return"],
                "return_rate": stat["return"] / stat["trigger"],
            }

        timeline_report["double_keep_break"] = {}

        for z, stat in timeline_rule2.items():

            if stat["trigger"] == 0:
                continue

            timeline_report["double_keep_break"][z] = {
                "trigger": stat["trigger"],
                "return": stat["return"],
                "return_rate": stat["return"] / stat["trigger"],
            }

        # ----------------------------------------------------------
        # 规则3：连续空窗N期 -> 下一期是否回补（修正版）
        # ----------------------------------------------------------

        timeline_gap_rule = collections.defaultdict(
            lambda: {
                "trigger": 0,
                "return": 0,
            }
        )

        for z in self.zodiac_order:

            gap = 0

            for i in range(total_periods - 1):

                curr_set = set(zodiac_matrix[i])
                next_set = set(zodiac_matrix[i + 1])

                if z not in curr_set:

                    gap += 1

                    timeline_gap_rule[gap]["trigger"] += 1

                    if z in next_set:
                        timeline_gap_rule[gap]["return"] += 1

                else:

                    gap = 0

        timeline_report["gap_return"] = {}

        for gap, stat in sorted(timeline_gap_rule.items()):

            if stat["trigger"] == 0:
                continue

            timeline_report["gap_return"][gap] = {
                "trigger": stat["trigger"],
                "return": stat["return"],
                "return_rate": stat["return"] / stat["trigger"],
            }

        # ----------------------------------------------------------
        # 规则4：连续缺席N期之后真正回补概率（新增）
        # ----------------------------------------------------------

        timeline_gap_finish = collections.defaultdict(
            lambda: {
                "trigger": 0,
                "return": 0,
            }
        )

        for z in self.zodiac_order:

            gap = 0

            for i in range(total_periods):

                curr_set = set(zodiac_matrix[i])

                if z not in curr_set:

                    gap += 1

                else:

                    if gap > 0:

                        timeline_gap_finish[gap]["trigger"] += 1
                        timeline_gap_finish[gap]["return"] += 1

                    gap = 0

        timeline_report["gap_finish"] = {}

        for gap, stat in sorted(timeline_gap_finish.items()):

            if stat["trigger"] == 0:
                continue

            timeline_report["gap_finish"][gap] = {
                "trigger": stat["trigger"],
                "return": stat["return"],
                "return_rate": stat["return"] / stat["trigger"],
            }
        # =========================================================================
        # 8. 查找器 8：逆向追踪特征
        # =========================================================================
        reverse_trace_report = []
        hot_groups = [p for p, freq in pair_period_dist.items() if freq >= 3]
        for h_pair in hot_groups:
            target_indices = [
                idx
                for idx in range(1, total_periods)
                if set(h_pair).issubset(set(zodiac_matrix[idx]))
            ]
            if target_indices:
                prev_z_pool = []
                for idx in target_indices:
                    prev_z_pool.extend(zodiac_matrix[idx - 1])
                prev_counts = collections.Counter(prev_z_pool)
                trace_hits = [
                    (z, c / len(target_indices))
                    for z, c in prev_counts.items()
                    if (c / len(target_indices)) >= 0.75
                ]
                if trace_hits:
                    reverse_trace_report.append(
                        {
                            "pair": h_pair,
                            "trig": len(target_indices),
                            "hints": trace_hits,
                        }
                    )

        ranking = sorted(
            zodiac_score.items(), key=lambda x: x[1]["score"], reverse=True
        )

        return {
            "total": total_periods,
            "latest_issue": sorted_records[-1]["issue"],
            "rule1": rule1_report,
            "rule1_pairs": rule1_pair_report,
            "diversity_repeat_rule": diversity_repeat_rule,
            "rule2_kills": single_cross_kills[:20],
            "rule3_report": rule3_report,
            "top_special_expanded": special_expanded[:15],
            "top_15_pairs": top_15_pairs,
            "bottom_15_pairs": bottom_15_pairs,
            "combo_linkage": combo_clash_rules,
            "reverse_trace": reverse_trace_report,
            "trace_recovery": trace_recovery,
            "zodiac_score": zodiac_score,
            "zodiac_ranking": ranking,
            "trace_recovery": trace_recovery_report,
            "rule1_triplets": rule1_triplet_report,
            "timeline": timeline_report,
        }
