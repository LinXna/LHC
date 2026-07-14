import os
import json
import logging
import collections
from bisect import bisect_left
from itertools import combinations

logger = logging.getLogger(__name__)


class ZodiacPatternAnalyzer:
    # ----- 可配置常量（集中管理）-----
    EXT_PERIODS = 5  # 查找器4 未来观察期数
    MAX_LOOKBACK = 30  # 查找器4 最大回溯期数
    MIN_PERIODS = 4  # 执行统计分析的最小期数
    MAX_GAP_STAT = 30  # 时间轴规则最大统计间隔
    HOT_THRESHOLD = 0.12  # 通用联合统计热点阈值
    # --------------------------------

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
        if base_zodiac not in self.zodiac_order:
            raise ValueError(
                f"无效本命肖: {base_zodiac!r}，可选: {', '.join(self.zodiac_order)}"
            )
        self._zodiac_map_cache = {}
        self.zodiac_map = self._get_zodiac_map(base_zodiac)

    @staticmethod
    def _validate_draw_numbers(nums):
        if not isinstance(nums, list) or len(nums) != 7:
            return False
        try:
            normalized = [int(n) for n in nums]
        except (TypeError, ValueError):
            return False
        if len(set(normalized)) != 7:
            return False
        return all(1 <= n <= 49 for n in normalized)

    @staticmethod
    def get_base_zodiac_by_year(year_int):
        year_cycle = [
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
        return year_cycle[year_int % 12]

    @staticmethod
    def _safe_issue_key(record):
        """尝试获取有效期号，失败返回 None 表示丢弃"""
        issue = record.get("issue")
        if issue is None:
            return None
        try:
            return int(issue)
        except (ValueError, TypeError):
            logger.warning(f"期号格式严重异常，该条记录将被丢弃: {issue}")
            return None

    def _get_zodiac_map(self, base_zodiac):
        if base_zodiac not in self.zodiac_order:
            raise ValueError(
                f"无效本命肖: {base_zodiac!r}，可选: {', '.join(self.zodiac_order)}"
            )
        if base_zodiac not in self._zodiac_map_cache:
            self._zodiac_map_cache[base_zodiac] = self._build_map(base_zodiac)
        return self._zodiac_map_cache[base_zodiac]

    def _build_map(self, base_zodiac):
        idx = self.zodiac_order.index(base_zodiac)
        aligned = self.zodiac_order[idx:] + self.zodiac_order[:idx]
        return {i: aligned[(i - 1) % 12] for i in range(1, 50)}

    def load_json_data(self, file_path=None, data_dir="data"):
        all_records = []

        if not os.path.exists(data_dir):
            logger.error(f"数据目录不存在: {data_dir}")
            return []

        if not os.path.isdir(data_dir):
            logger.error(f"{data_dir} 不是一个目录")
            return []

        if file_path:
            target_files = [file_path]
        else:
            target_files = sorted(
                os.path.join(data_dir, f)
                for f in os.listdir(data_dir)
                if f.endswith(".json")
            )

        for path in target_files:
            file_records = []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    if not isinstance(payload, dict):
                        logger.warning(f"{path} 不是合法JSON对象")
                        continue

                    body_list = (
                        payload.get("result", {}).get("data", {}).get("bodyList", [])
                    )
                    if not isinstance(body_list, list):
                        logger.warning(f"{path} 中 bodyList 格式错误")
                        continue

                    for item in body_list:
                        try:
                            code_str = item.get("preDrawCode")
                            if not code_str:
                                continue
                            try:
                                nums = [
                                    int(x.strip())
                                    for x in code_str.split(",")
                                    if x.strip()
                                ]
                            except ValueError:
                                logger.warning(f"号码格式错误：{code_str}")
                                continue
                            if self._validate_draw_numbers(nums):
                                # 检查期号有效性
                                issue_key = self._safe_issue_key(item)
                                if issue_key is None:
                                    logger.warning(
                                        f"无效期号，丢弃该条记录: {item.get('issue')}"
                                    )
                                    continue
                                file_records.append(
                                    {
                                        "issue": issue_key,
                                        "date": item.get("preDrawDate"),
                                        "numbers": [int(n) for n in nums],
                                    }
                                )
                            else:
                                logger.warning(
                                    f"号码校验失败（需7个不重复1-49）：{code_str}"
                                )
                        except (KeyError, ValueError, TypeError) as e:
                            logger.warning(f"跳过异常记录：{e}")
                            continue

                file_records.sort(key=lambda x: x["issue"])
                all_records.extend(file_records)

            except FileNotFoundError:
                logger.warning(f"文件不存在，已跳过：{path}")
                continue
            except PermissionError:
                logger.warning(f"没有权限读取文件：{path}")
                continue
            except UnicodeDecodeError:
                logger.warning(f"文件编码错误：{path}")
                continue
            except json.JSONDecodeError as e:
                logger.warning(f"JSON格式错误：{path} ({e})")
                continue
            except OSError as e:
                logger.warning(f"读取文件失败：{path} ({e})")
                continue

        # 🔧 全局排序，确保跨文件记录按期号严格升序
        all_records.sort(key=lambda x: x["issue"])
        logger.info(f"成功加载 {len(all_records)} 条历史记录（已全局排序）")
        return all_records

    def build_zodiac_relation_rule(
        self, relation_source, size=2, hot_threshold=None, cold_zero=False
    ):
        if hot_threshold is None:
            hot_threshold = self.HOT_THRESHOLD

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

    def compute_patterns(self, sorted_records):
        if sorted_records is None:
            raise ValueError("sorted_records 不能为 None")
        if not isinstance(sorted_records, list):
            raise TypeError("sorted_records 必须是 list")
        if len(sorted_records) == 0:
            return {
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

        total_periods = len(sorted_records)
        if total_periods < self.MIN_PERIODS:
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
                "score": {},
            }

        history_data = []
        valid_records = []
        for record in sorted_records:
            if not isinstance(record, dict):
                continue
            nums = record.get("numbers")
            if not self._validate_draw_numbers(nums):
                continue
            history_data.append([int(n) for n in nums])
            valid_records.append(record)

        total_periods = len(history_data)
        if total_periods < self.MIN_PERIODS:
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
                "score": {},
            }

        zodiac_matrix = []
        aligned_records = []
        aligned_history = []
        for record, group in zip(valid_records, history_data):
            try:
                year = record.get("archive_year")
                if year is not None:
                    base = self.get_base_zodiac_by_year(int(year))
                    zmap = self._get_zodiac_map(base)
                else:
                    zmap = self.zodiac_map
                zodiac_matrix.append([zmap[n] for n in group])
                aligned_records.append(record)
                aligned_history.append(group)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"生肖映射失败，已跳过一条记录：{e}")
                continue

        valid_records = aligned_records
        history_data = aligned_history
        total_periods = len(zodiac_matrix)
        if total_periods < self.MIN_PERIODS:
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
                "score": {},
            }

        total_valid_p = max(total_periods - 1, 1)

        # =========================================================================
        # 查找器7：前三期轨迹回补规则
        # =========================================================================
        trace_disappear_pool = collections.defaultdict(list)
        for i in range(3, total_periods - 1):
            last1 = set(zodiac_matrix[i - 1])
            last2 = set(zodiac_matrix[i - 2])
            curr = set(zodiac_matrix[i])
            disappeared = (last1 & last2) - curr
            if not disappeared:
                continue
            next_period = zodiac_matrix[i + 1]
            for z in disappeared:
                trace_disappear_pool[z].extend(next_period)

        trace_recovery_hot = {}
        for z, pool in trace_disappear_pool.items():
            counts = collections.Counter(pool)
            total = len(pool)
            if total == 0:
                continue
            hot = []
            for name, cnt in counts.items():
                rate = cnt / total if total else 0
                if rate >= 0.10:
                    hot.append((name, cnt, rate))
            hot.sort(key=lambda x: x[2], reverse=True)
            trace_recovery_hot[z] = {"samples": total // 7, "hot": hot}

        # =========================================================================
        # 统一生肖评分池
        # =========================================================================
        zodiac_score = {
            z: {"score": 0, "reasons": [], "confidence": 0} for z in self.zodiac_order
        }

        def add_score(zodiac, score, reason, confidence=1):
            if zodiac not in zodiac_score:
                return
            zodiac_score[zodiac]["score"] += score
            zodiac_score[zodiac]["confidence"] += confidence
            zodiac_score[zodiac]["reasons"].append(reason)

        # =========================================================================
        # 1 & 2. 单生肖交叉 + 多对组合
        # =========================================================================
        diversity_history = [len(set(z_list)) for z_list in zodiac_matrix]
        rule1_detail = collections.defaultdict(list)
        rule1_pair_detail = collections.defaultdict(list)
        rule1_triplet_detail = collections.defaultdict(list)

        repeat_stats_by_div = collections.defaultdict(
            lambda: {
                "total_cases": 0,
                "repeated_cases": 0,
                "repeat_counts": collections.Counter(),
            }
        )

        for i in range(total_valid_p):
            curr_z_set = set(zodiac_matrix[i])
            curr_div = diversity_history[i]
            next_z_list = zodiac_matrix[i + 1]
            next_z_set = set(next_z_list)

            intersect = curr_z_set.intersection(next_z_set)
            intersect_cnt = len(intersect)
            repeat_stats_by_div[curr_div]["total_cases"] += 1
            if intersect_cnt > 0:
                repeat_stats_by_div[curr_div]["repeated_cases"] += 1
                repeat_stats_by_div[curr_div]["repeat_counts"][intersect_cnt] += 1

            for z in curr_z_set:
                rule1_detail[(curr_div, z)].extend(next_z_list)
            for z_pair in combinations(sorted(list(curr_z_set)), 2):
                rule1_pair_detail[(curr_div, z_pair)].extend(next_z_list)
            for z_triplet in combinations(sorted(list(curr_z_set)), 3):
                rule1_triplet_detail[(curr_div, z_triplet)].extend(next_z_list)

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

        rule1_pair_report = self.build_zodiac_relation_rule(
            rule1_pair_detail, size=2, hot_threshold=0.12, cold_zero=True
        )
        rule1_triplet_report = self.build_zodiac_relation_rule(
            rule1_triplet_detail, size=3, hot_threshold=0.12, cold_zero=True
        )

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
        # 4. 微观强力杀号过滤器
        # =========================================================================
        single_cross_kills = []
        for z_curr in self.zodiac_order:
            idx_list = [i for i in range(total_valid_p) if z_curr in zodiac_matrix[i]]
            if len(idx_list) < 20:
                continue
            next_pool = []
            for idx in idx_list:
                next_pool.extend(zodiac_matrix[idx + 1])
            next_total = len(next_pool)
            if next_total == 0:
                continue
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
        # 5. 十进制区间空间局限性矩阵（扩展版）
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
            num_count_dist = collections.Counter()

            for i in range(total_valid_p):
                curr_nums = history_data[i]
                next_nums = history_data[i + 1]
                in_range_nums = sorted([n for n in curr_nums if r_min <= n <= r_max])
                in_count = len(in_range_nums)
                num_count_dist[in_count] += 1

                if in_count == 2:
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

            rule3_report[r_label] = {
                "periods_with_two": r_trig_p,
                "num_count_distribution": dict(num_count_dist),
                "slots": dict(slots_linkage),
            }

        # =========================================================================
        # 6. 查找器 4：特码隔离特征矩阵（加入回溯窗口限制）
        # =========================================================================
        special_expanded_by_num = {}
        logger.info("正在深度解构 查找器 4（特码隔离特征矩阵）...")

        num_positions = collections.defaultdict(list)
        for i, nums in enumerate(history_data):
            for n in nums:
                num_positions[n].append(i)

        for target_idx in range(total_periods):
            if target_idx % max(1, total_periods // 10) == 0:
                percent = (target_idx / total_periods) * 100
                logger.debug("查找器4 特征矩阵进度 %.0f%%", percent)

            scan_limit = target_idx - self.EXT_PERIODS
            if scan_limit <= 0:
                continue

            for num in history_data[target_idx]:
                appear_count = 0
                bias_trigger_count = 0
                target_zodiac_pool = []

                odd_c = 0
                even_c = 0
                big_c = 0
                small_c = 0
                tail_dist = collections.defaultdict(int)
                total_future_numbers = 0

                positions = num_positions.get(num)
                if not positions:
                    continue
                cutoff = bisect_left(positions, scan_limit)
                start_pos = max(0, cutoff - self.MAX_LOOKBACK)
                recent_positions = positions[start_pos:cutoff]

                for hist_i in recent_positions:
                    appear_count += 1
                    f_zodiacs = []
                    f_nums = []
                    for offset in range(1, self.EXT_PERIODS + 1):
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

                    entry = (
                        num,
                        b_rate * 100,
                        b_rate,
                        most_z,
                        appear_count,
                        behavior_rule,
                    )
                    existing = special_expanded_by_num.get(num)
                    if existing is None or b_rate > existing[2]:
                        special_expanded_by_num[num] = entry

        special_expanded = list(special_expanded_by_num.values())
        special_expanded.sort(key=lambda x: x[1], reverse=True)
        logger.info("查找器4 特码隔离特征矩阵清洗完毕")

        # =========================================================================
        # 7. 查找器 7：三期轨迹回补矩阵
        # =========================================================================
        trace_recovery_matrix = {
            "prev1_missing": {},
            "prev2_missing": {},
            "prev3_missing": {},
            "multi_gap": {},
        }
        for gap_type, gap_size in [
            ("prev1_missing", 1),
            ("prev2_missing", 2),
            ("prev3_missing", 3),
        ]:
            trigger_pool = collections.defaultdict(list)
            for i in range(gap_size, total_valid_p):
                consecutive_set = set(zodiac_matrix[i - 1])
                for back in range(2, gap_size + 1):
                    consecutive_set &= set(zodiac_matrix[i - back])
                current_set = set(zodiac_matrix[i])
                next_set = set(zodiac_matrix[i + 1])
                missing_z = consecutive_set - current_set
                for z in missing_z:
                    trigger_pool[z].append(1 if z in next_set else 0)

            result = {}
            for z, values in trigger_pool.items():
                total = len(values)
                if total < 10:
                    continue
                result[z] = {
                    "trigger": total,
                    "recover": sum(values),
                    "rate": sum(values) / total,
                }
            trace_recovery_matrix[gap_type] = result

        multi_trigger = collections.defaultdict(list)
        for i in range(3, total_valid_p):
            consecutive_three = set(zodiac_matrix[i - 1])
            for back in range(2, 4):
                consecutive_three &= set(zodiac_matrix[i - back])
            current_set = set(zodiac_matrix[i])
            next_set = set(zodiac_matrix[i + 1])
            disappear = consecutive_three - current_set
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
        trace_recovery_matrix["multi_gap"] = multi_result

        # =========================================================================
        # 8. 查找器 6 保留空壳
        # =========================================================================
        combo_clash_rules = []

        # =========================================================================
        # 9. 查找器7：跨期时间轴引擎（限制最大间隔）
        # =========================================================================
        timeline_report = {}

        # 规则1 & 规则2
        timeline_rule1 = collections.defaultdict(lambda: {"trigger": 0, "return": 0})
        timeline_rule2 = collections.defaultdict(lambda: {"trigger": 0, "return": 0})
        for i in range(2, total_periods - 1):
            prev_set = set(zodiac_matrix[i - 1])
            curr_set = set(zodiac_matrix[i])
            next_set = set(zodiac_matrix[i + 1])
            for z in self.zodiac_order:
                if z in prev_set and z not in curr_set:
                    timeline_rule1[z]["trigger"] += 1
                    if z in next_set:
                        timeline_rule1[z]["return"] += 1
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

        # 规则3 & 规则4：限制间隔不超过 MAX_GAP_STAT
        timeline_gap_rule = collections.defaultdict(lambda: {"trigger": 0, "return": 0})
        for z in self.zodiac_order:
            gap = 0
            for i in range(total_periods - 1):
                curr_set = set(zodiac_matrix[i])
                next_set = set(zodiac_matrix[i + 1])
                if z not in curr_set:
                    gap += 1
                    stat_gap = min(gap, self.MAX_GAP_STAT)
                    timeline_gap_rule[stat_gap]["trigger"] += 1
                    if z in next_set:
                        timeline_gap_rule[stat_gap]["return"] += 1
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

        timeline_gap_finish = collections.defaultdict(
            lambda: {"trigger": 0, "return": 0}
        )
        for z in self.zodiac_order:
            gap = 0
            for i in range(total_periods):
                curr_set = set(zodiac_matrix[i])
                if z not in curr_set:
                    gap += 1
                else:
                    if gap > 0:
                        stat_gap = min(gap, self.MAX_GAP_STAT)
                        timeline_gap_finish[stat_gap]["trigger"] += 1
                        if i + 1 < total_periods and z in set(zodiac_matrix[i + 1]):
                            timeline_gap_finish[stat_gap]["return"] += 1
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
        # 10. 查找器 8：逆向追踪特征
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
            "latest_issue": valid_records[-1].get("issue") if valid_records else None,
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
            "trace_recovery": trace_recovery_matrix,
            "trace_recovery_hot": trace_recovery_hot,
            "zodiac_score": zodiac_score,
            "zodiac_ranking": ranking,
            "rule1_triplets": rule1_triplet_report,
            "timeline": timeline_report,
        }
