import os
import json
import logging
import collections
import math
import hashlib
import pickle
from bisect import bisect_left
from datetime import datetime
from itertools import combinations, product

logger = logging.getLogger(__name__)


class ZodiacPatternAnalyzer:
    TOP6_MODEL_VERSION = "top6_joint_ablation_consensus_v8_1"
    ELEMENT_ORDER = ("金", "木", "水", "火", "土")
    ZODIAC_ELEMENTS = {
        "鼠": "水", "牛": "土", "虎": "木", "兔": "木",
        "龙": "土", "蛇": "火", "马": "火", "羊": "土",
        "猴": "金", "鸡": "金", "狗": "土", "猪": "水",
    }
    ZODIAC_YIN_YANG = {
        "鼠": "阳", "牛": "阴", "虎": "阳", "兔": "阴",
        "龙": "阳", "蛇": "阴", "马": "阳", "羊": "阴",
        "猴": "阳", "鸡": "阴", "狗": "阳", "猪": "阴",
    }
    ZODIAC_ANIMAL_CLASS = {
        zodiac: ("家禽" if zodiac in {"牛", "马", "羊", "鸡", "狗", "猪"} else "野兽")
        for zodiac in ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
    }
    # ----- 可配置常量（集中管理）-----
    EXT_PERIODS = 5  # 查找器4 未来观察期数
    MAX_LOOKBACK = 30  # 查找器4 最大回溯期数
    MIN_PERIODS = 4  # 执行统计分析的最小期数
    MAX_GAP_STAT = 30  # 时间轴规则最大统计间隔
    HOT_THRESHOLD = 0.12  # 通用联合统计热点阈值
    LUNAR_NEW_YEAR_DATES = {
        2009: "2009-01-26",
        2010: "2010-02-14",
        2011: "2011-02-03",
        2012: "2012-01-23",
        2013: "2013-02-10",
        2014: "2014-01-31",
        2015: "2015-02-19",
        2016: "2016-02-08",
        2017: "2017-01-28",
        2018: "2018-02-16",
        2019: "2019-02-05",
        2020: "2020-01-25",
        2021: "2021-02-12",
        2022: "2022-02-01",
        2023: "2023-01-22",
        2024: "2024-02-10",
        2025: "2025-01-29",
        2026: "2026-02-17",
    }
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

    @classmethod
    def get_zodiac_year_by_date(cls, draw_date):
        """按农历正月初一判断一期开奖结果所属的生肖年。"""
        if isinstance(draw_date, str):
            parsed = datetime.strptime(draw_date, "%Y-%m-%d").date()
        elif hasattr(draw_date, "year"):
            parsed = draw_date
        else:
            raise ValueError(f"无效开奖日期: {draw_date!r}")
        boundary_text = cls.LUNAR_NEW_YEAR_DATES.get(parsed.year)
        if boundary_text is None:
            raise ValueError(f"缺少 {parsed.year} 年农历正月初一日期配置")
        boundary = datetime.strptime(boundary_text, "%Y-%m-%d").date()
        return parsed.year if parsed >= boundary else parsed.year - 1

    @classmethod
    def get_base_zodiac_by_date(cls, draw_date):
        return cls.get_base_zodiac_by_year(cls.get_zodiac_year_by_date(draw_date))

    def get_zodiac_map_by_date(self, draw_date):
        return self._get_zodiac_map(self.get_base_zodiac_by_date(draw_date))

    @staticmethod
    def _record_sort_key(record):
        date_text = record.get("date") or "0000-00-00"
        year = record.get("archive_year", 0)
        issue = record.get("issue", 0)
        return date_text, int(year or 0), int(issue or 0)

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

    def load_json_data(self, file_path=None, data_dir="data_verified"):
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
                and len(os.path.splitext(f)[0]) == 4
                and os.path.splitext(f)[0].isdigit()
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
                                draw_date = item.get("preDrawDate")
                                zodiac_year = self.get_zodiac_year_by_date(draw_date)
                                file_records.append(
                                    {
                                        "issue": issue_key,
                                        "date": draw_date,
                                        "numbers": [int(n) for n in nums],
                                        "archive_year": int(draw_date[:4]),
                                        "zodiac_year": zodiac_year,
                                        "base_zodiac": self.get_base_zodiac_by_year(
                                            zodiac_year
                                        ),
                                    }
                                )
                            else:
                                logger.warning(
                                    f"号码校验失败（需7个不重复1-49）：{code_str}"
                                )
                        except (KeyError, ValueError, TypeError) as e:
                            logger.warning(f"跳过异常记录：{e}")
                            continue

                file_records.sort(key=self._record_sort_key)
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

        # 全局按开奖日期、年份、期号排序，不能只按期号跨年混排。
        all_records.sort(key=self._record_sort_key)
        logger.info(f"成功加载 {len(all_records)} 条历史记录（已全局排序）")
        return all_records

    @staticmethod
    def _record_digest(records):
        digest = hashlib.sha256()
        for record in records:
            digest.update(
                json.dumps(
                    {
                        "issue": record["issue"],
                        "date": record["date"],
                        "numbers": record["numbers"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        return digest.hexdigest()

    def save_incremental_state(self, path, records, state):
        package = {
            "model_version": self.TOP6_MODEL_VERSION,
            "record_count": len(records),
            "record_digest": self._record_digest(records),
            "latest_record": {
                "issue": records[-1]["issue"],
                "date": records[-1]["date"],
                "numbers": records[-1]["numbers"],
            },
            "state": state,
        }
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        temporary_path = path + ".tmp"
        with open(temporary_path, "wb") as handle:
            pickle.dump(package, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)

    def load_incremental_state(self, path, records):
        if not os.path.isfile(path):
            return None, "missing"
        try:
            with open(path, "rb") as handle:
                package = pickle.load(handle)
        except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError):
            return None, "unreadable"
        if not isinstance(package, dict):
            return None, "invalid_package"
        if package.get("model_version") != self.TOP6_MODEL_VERSION:
            return None, "model_changed"
        record_count = package.get("record_count")
        if not isinstance(record_count, int) or record_count <= 0:
            return None, "invalid_count"
        if record_count > len(records):
            return None, "history_shortened"
        if package.get("record_digest") != self._record_digest(records[:record_count]):
            return None, "historical_data_changed"
        state = package.get("state")
        if not isinstance(state, dict) or state.get("record_count") != record_count:
            return None, "invalid_state"
        return state, ("current" if record_count == len(records) else "append_only")

    def build_or_update_incremental_state(self, records, path, warmup=200):
        state, cache_status = self.load_incremental_state(path, records)
        previous_count = state["record_count"] if state else 0
        appended_details = []
        if state is not None and previous_count < len(records):
            previous_key = self._record_sort_key(records[previous_count - 1])
            for record in records[previous_count:]:
                if not self._validate_draw_numbers(record.get("numbers")):
                    raise ValueError("增量记录号码必须是7个不重复的1-49号码")
                current_key = self._record_sort_key(record)
                if current_key <= previous_key:
                    raise ValueError("新增开奖记录不是严格追加，必须全量重建")
                zodiac_year = self.get_zodiac_year_by_date(record.get("date"))
                base_zodiac = self.get_base_zodiac_by_year(zodiac_year)
                if record.get("zodiac_year") != zodiac_year:
                    raise ValueError("新增记录的农历生肖年份校验失败")
                if record.get("base_zodiac") != base_zodiac:
                    raise ValueError("新增记录的本命生肖校验失败")
                appended_details.append(
                    {
                        "issue": record["issue"],
                        "date": record["date"],
                        "numbers": list(record["numbers"]),
                        "zodiac_year": zodiac_year,
                        "base_zodiac": base_zodiac,
                    }
                )
                previous_key = current_key
        if state is None:
            contexts, rows, state = self._walk_forward_feature_rows(
                records, warmup=warmup, return_state=True
            )
            mode = "full_rebuild"
        elif previous_count == len(records):
            contexts, rows = state["contexts"], state["rows"]
            mode = "cache_reused"
        else:
            contexts, rows, state = self._walk_forward_feature_rows(
                records,
                warmup=warmup,
                state=state,
                return_state=True,
            )
            mode = "incremental_append"
        if mode != "cache_reused":
            self.save_incremental_state(path, records, state)
        return contexts, rows, state, {
            "mode": mode,
            "cache_status": cache_status,
            "previous_record_count": previous_count,
            "current_record_count": len(records),
            "appended_records": len(records) - previous_count if previous_count else len(records),
            "append_validation_passed": True,
            "appended_details": appended_details,
        }

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

    @staticmethod
    def _jaccard(left, right):
        union = set(left) | set(right)
        return len(set(left) & set(right)) / len(union) if union else 1.0

    def _build_ranking_contexts(self, records):
        contexts = []
        for record in sorted(records, key=self._record_sort_key):
            nums = record.get("numbers")
            draw_date = record.get("date")
            if not self._validate_draw_numbers(nums) or not draw_date:
                continue
            zmap = self.get_zodiac_map_by_date(draw_date)
            zodiacs = tuple(zmap[int(number)] for number in nums)
            counts = collections.Counter(zodiacs)
            unique_zodiacs = set(zodiacs)
            base = self.get_base_zodiac_by_date(draw_date)
            element_counts = collections.Counter(
                self.ZODIAC_ELEMENTS[zodiac] for zodiac in unique_zodiacs
            )
            yin_count = sum(
                self.ZODIAC_YIN_YANG[zodiac] == "阴" for zodiac in unique_zodiacs
            )
            domestic_count = sum(
                self.ZODIAC_ANIMAL_CLASS[zodiac] == "家禽"
                for zodiac in unique_zodiacs
            )
            contexts.append(
                {
                    "record": record,
                    "date": draw_date,
                    "zodiacs": zodiacs,
                    "set": frozenset(zodiacs),
                    "counts": counts,
                    "diversity": len(counts),
                    "special": zodiacs[-1],
                    "base": base,
                    "special_is_base": zodiacs[-1] == base,
                    "special_repeated": zodiacs[-1] in zodiacs[:-1],
                    "element_counts": tuple(
                        element_counts[element] for element in self.ELEMENT_ORDER
                    ),
                    "elements_present": tuple(
                        element
                        for element in self.ELEMENT_ORDER
                        if element_counts[element] > 0
                    ),
                    "yin_count": yin_count,
                    "yang_count": len(unique_zodiacs) - yin_count,
                    "domestic_count": domestic_count,
                    "wild_count": len(unique_zodiacs) - domestic_count,
                }
            )
        return contexts

    def _context_similarity(self, contexts, anchor, current):
        anchor_ctx = contexts[anchor]
        current_ctx = contexts[current]
        current_set_similarity = self._jaccard(anchor_ctx["set"], current_ctx["set"])
        diversity_similarity = max(
            0.0,
            1.0 - abs(anchor_ctx["diversity"] - current_ctx["diversity"]) / 4.0,
        )
        previous_similarity = self._jaccard(
            contexts[anchor - 1]["set"], contexts[current - 1]["set"]
        )
        anchor_overlap = len(anchor_ctx["set"] & contexts[anchor - 1]["set"])
        current_overlap = len(current_ctx["set"] & contexts[current - 1]["set"])
        overlap_similarity = max(0.0, 1.0 - abs(anchor_overlap - current_overlap) / 7.0)
        sequence_similarity = sum(
            max(
                0.0,
                1.0
                - abs(
                    contexts[anchor - offset]["diversity"]
                    - contexts[current - offset]["diversity"]
                )
                / 4.0,
            )
            for offset in range(3)
        ) / 3.0
        multiplicity_difference = sum(
            abs(anchor_ctx["counts"].get(zodiac, 0) - current_ctx["counts"].get(zodiac, 0))
            for zodiac in self.zodiac_order
        )
        multiplicity_similarity = max(0.0, 1.0 - multiplicity_difference / 14.0)
        return (
            0.40 * current_set_similarity
            + 0.10 * diversity_similarity
            + 0.20 * previous_similarity
            + 0.10 * overlap_similarity
            + 0.15 * sequence_similarity
            + 0.05 * multiplicity_similarity
        )

    def _prototype_probabilities(self, contexts, current, baseline):
        candidates = []
        # anchor + 1 必须已经开奖；因此最多只能使用 current - 1。
        for anchor in range(2, current):
            score = self._context_similarity(contexts, anchor, current)
            candidates.append((score, anchor))
        if not candidates:
            return dict(baseline), {"candidates": 0, "selected": 0, "min_score": 0, "max_score": 0}
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected_count = max(5, math.ceil(len(candidates) * 0.05))
        selected = candidates[:selected_count]
        weighted_hits = collections.Counter()
        total_weight = 0.0
        for score, anchor in selected:
            weight = max(score, 0.01) ** 2
            total_weight += weight
            for zodiac in contexts[anchor + 1]["set"]:
                weighted_hits[zodiac] += weight
        alpha = 3.0
        probabilities = {
            zodiac: (weighted_hits[zodiac] + alpha * baseline[zodiac])
            / (total_weight + alpha)
            for zodiac in self.zodiac_order
        }
        return probabilities, {
            "candidates": len(candidates),
            "selected": len(selected),
            "min_score": selected[-1][0],
            "max_score": selected[0][0],
        }

    def _bucket_probabilities(self, bucket, baseline, alpha):
        if not bucket:
            return dict(baseline)
        samples, hits = bucket[:2]
        return {
            zodiac: (hits[zodiac] + alpha * baseline[zodiac]) / (samples + alpha)
            for zodiac in self.zodiac_order
        }

    @staticmethod
    def _update_bucket(store, key, outcome_set):
        if key not in store:
            store[key] = [0, collections.Counter()]
        store[key][0] += 1
        for zodiac in outcome_set:
            store[key][1][zodiac] += 1

    def _update_interaction_stats(self, store, anchor_context, outcome_set):
        ordered = [zodiac for zodiac in self.zodiac_order if zodiac in anchor_context["set"]]
        anchor_year = int(anchor_context["date"][:4])
        for size in range(1, len(ordered) + 1):
            for combo in combinations(ordered, size):
                if combo not in store:
                    store[combo] = [0, collections.Counter(), set(), {}]
                store[combo][0] += 1
                store[combo][2].add(anchor_year)
                yearly = store[combo][3]
                if anchor_year not in yearly:
                    yearly[anchor_year] = [0, collections.Counter()]
                yearly[anchor_year][0] += 1
                for zodiac in outcome_set:
                    store[combo][1][zodiac] += 1
                    yearly[anchor_year][1][zodiac] += 1

    def _update_f4_stats(self, store, anchor_context, outcome_context):
        """累计特码状态及“特码+其他生肖”逐级组合对下一期的影响。"""
        anchor_year = int(anchor_context["date"][:4])
        special = anchor_context["special"]
        others = [
            zodiac
            for zodiac in self.zodiac_order
            if zodiac in anchor_context["set"] and zodiac != special
        ]
        keys = [
            ("special", special),
            (
                "state",
                anchor_context["special_is_base"],
                anchor_context["special_repeated"],
                anchor_context["diversity"],
            ),
        ]
        for other_size in range(len(others) + 1):
            for other_combo in combinations(others, other_size):
                keys.append(
                    (
                        "combo",
                        special,
                        anchor_context["special_is_base"],
                        anchor_context["special_repeated"],
                        other_combo,
                    )
                )

        for key in keys:
            if key not in store:
                store[key] = [
                    0,
                    collections.Counter(),
                    set(),
                    {},
                    collections.Counter(),
                ]
            bucket = store[key]
            bucket[0] += 1
            bucket[2].add(anchor_year)
            bucket[4][outcome_context["diversity"]] += 1
            if anchor_year not in bucket[3]:
                bucket[3][anchor_year] = [0, collections.Counter()]
            bucket[3][anchor_year][0] += 1
            for zodiac in outcome_context["set"]:
                bucket[1][zodiac] += 1
                bucket[3][anchor_year][1][zodiac] += 1

    def _f3_state_keys(self, context):
        diversity = context["diversity"]
        return [
            {
                "key": (
                    "exact",
                    context["element_counts"],
                    context["yin_count"],
                    context["domestic_count"],
                    diversity,
                ),
                "label": "五行计数+阴阳+家禽野兽精确态",
                "minimum_samples": 8,
                "minimum_years": 4,
                "alpha": 15.0,
                "pseudo_size": 4,
                "specificity": 1.60,
            },
            {
                "key": (
                    "presence",
                    context["elements_present"],
                    context["yin_count"],
                    context["domestic_count"],
                    diversity,
                ),
                "label": "五行覆盖+阴阳+家禽野兽",
                "minimum_samples": 15,
                "minimum_years": 5,
                "alpha": 20.0,
                "pseudo_size": 3,
                "specificity": 1.45,
            },
            {
                "key": (
                    "coarse",
                    len(context["elements_present"]),
                    context["yin_count"],
                    context["domestic_count"],
                    diversity,
                ),
                "label": "五行数量+阴阳+家禽野兽",
                "minimum_samples": 25,
                "minimum_years": 6,
                "alpha": 25.0,
                "pseudo_size": 3,
                "specificity": 1.35,
            },
            {
                "key": ("element", context["element_counts"], diversity),
                "label": "五行计数",
                "minimum_samples": 30,
                "minimum_years": 6,
                "alpha": 30.0,
                "pseudo_size": 2,
                "specificity": 1.25,
            },
            {
                "key": ("yin_yang", context["yin_count"], diversity),
                "label": "阴阳分组",
                "minimum_samples": 60,
                "minimum_years": 8,
                "alpha": 45.0,
                "pseudo_size": 1,
                "specificity": 1.10,
            },
            {
                "key": ("animal", context["domestic_count"], diversity),
                "label": "家禽野兽分组",
                "minimum_samples": 60,
                "minimum_years": 8,
                "alpha": 45.0,
                "pseudo_size": 1,
                "specificity": 1.10,
            },
        ]

    def _update_f3_stats(self, store, anchor_context, outcome_context):
        anchor_year = int(anchor_context["date"][:4])
        for descriptor in self._f3_state_keys(anchor_context):
            key = descriptor["key"]
            if key not in store:
                store[key] = [
                    0,
                    collections.Counter(),
                    set(),
                    {},
                    collections.Counter(),
                ]
            bucket = store[key]
            bucket[0] += 1
            bucket[2].add(anchor_year)
            bucket[4][outcome_context["diversity"]] += 1
            if anchor_year not in bucket[3]:
                bucket[3][anchor_year] = [0, collections.Counter()]
            bucket[3][anchor_year][0] += 1
            for zodiac in outcome_context["set"]:
                bucket[1][zodiac] += 1
                bucket[3][anchor_year][1][zodiac] += 1

    def _f5_state_descriptors(self, contexts, index, zodiac):
        bits = tuple(
            int(zodiac in contexts[position]["set"])
            for position in range(index - 2, index + 1)
        )
        gap = 0
        for position in range(index, -1, -1):
            if zodiac in contexts[position]["set"]:
                break
            gap += 1
        streak = 0
        for position in range(index, -1, -1):
            if zodiac not in contexts[position]["set"]:
                break
            streak += 1
        gap = min(gap, 8)
        streak = min(streak, 4)
        return [
            {
                "key": ("exact", bits, gap, streak),
                "label": "三期轨迹+空窗+连开精确态",
                "minimum_samples": 20,
                "minimum_years": 5,
                "alpha": 20.0,
                "pseudo_size": 3,
                "specificity": 1.45,
            },
            {
                "key": ("bits", bits),
                "label": "三期出现断档轨迹",
                "minimum_samples": 40,
                "minimum_years": 6,
                "alpha": 30.0,
                "pseudo_size": 2,
                "specificity": 1.30,
            },
            {
                "key": ("gap", gap),
                "label": "连续空窗长度",
                "minimum_samples": 80,
                "minimum_years": 8,
                "alpha": 50.0,
                "pseudo_size": 1,
                "specificity": 1.10,
            },
            {
                "key": ("streak", streak),
                "label": "连续出现长度",
                "minimum_samples": 80,
                "minimum_years": 8,
                "alpha": 50.0,
                "pseudo_size": 1,
                "specificity": 1.10,
            },
        ], {"bits": list(bits), "gap": gap, "streak": streak}

    def _update_f5_stats(self, store, contexts, anchor, outcome_context):
        if anchor < 2:
            return
        anchor_year = int(contexts[anchor]["date"][:4])
        for zodiac in self.zodiac_order:
            descriptors, _ = self._f5_state_descriptors(contexts, anchor, zodiac)
            for descriptor in descriptors:
                store_key = (zodiac, descriptor["key"])
                if store_key not in store:
                    store[store_key] = [0, collections.Counter(), set(), {}]
                bucket = store[store_key]
                bucket[0] += 1
                bucket[2].add(anchor_year)
                if anchor_year not in bucket[3]:
                    bucket[3][anchor_year] = [0, collections.Counter()]
                bucket[3][anchor_year][0] += 1
                if zodiac in outcome_context["set"]:
                    bucket[1][zodiac] += 1
                    bucket[3][anchor_year][1][zodiac] += 1

    @staticmethod
    def _interaction_thresholds(size):
        minimum_samples = {1: 80, 2: 30, 3: 12, 4: 6, 5: 3, 6: 2, 7: 2}
        minimum_years = {1: 8, 2: 6, 3: 4, 4: 3, 5: 2, 6: 2, 7: 2}
        alpha = {1: 60.0, 2: 35.0, 3: 20.0, 4: 12.0, 5: 8.0, 6: 6.0, 7: 6.0}
        return minimum_samples[size], minimum_years[size], alpha[size]

    def _interaction_year_stability(
        self,
        target,
        size,
        samples,
        hits,
        yearly,
        year_baselines,
        overall_delta,
    ):
        """检查组合信号是否跨年份同向，并执行逐年剔除压力测试。"""
        direction = 1 if overall_delta >= 0 else -1
        minimum_year_samples = 4 if size == 1 else 3 if size <= 3 else 2
        minimum_stable_years = {1: 8, 2: 6, 3: 4, 4: 3, 5: 3, 6: 3, 7: 3}[size]
        yearly_details = []
        same_years = opposite_years = neutral_years = 0
        same_weight = informative_weight = 0

        baseline_total_samples = sum(bucket[0] for bucket in year_baselines.values())
        baseline_total_hits = sum(bucket[1][target] for bucket in year_baselines.values())
        for year, (year_samples, year_hits) in sorted(yearly.items()):
            baseline_bucket = year_baselines.get(year)
            if not baseline_bucket or baseline_bucket[0] == 0:
                continue
            target_hits = year_hits[target]
            year_rate = target_hits / year_samples
            year_baseline_rate = baseline_bucket[1][target] / baseline_bucket[0]
            year_delta = year_rate - year_baseline_rate
            informative = year_samples >= minimum_year_samples
            if not informative or abs(year_delta) < 0.01:
                relation = "neutral"
                neutral_years += int(informative)
            elif year_delta * direction > 0:
                relation = "same"
                same_years += 1
                same_weight += year_samples
                informative_weight += year_samples
            else:
                relation = "opposite"
                opposite_years += 1
                informative_weight += year_samples
            yearly_details.append(
                {
                    "year": year,
                    "samples": year_samples,
                    "hits": target_hits,
                    "rate": year_rate,
                    "year_baseline_rate": year_baseline_rate,
                    "delta": year_delta,
                    "informative": informative,
                    "relation": relation,
                }
            )

        directional_years = same_years + opposite_years
        year_direction_ratio = (
            same_years / directional_years if directional_years else 0.0
        )
        weighted_direction_ratio = (
            same_weight / informative_weight if informative_weight else 0.0
        )
        year_sample_counts = [bucket[0] for bucket in yearly.values() if bucket[0] > 0]
        max_year_share = max(year_sample_counts) / samples if year_sample_counts else 1.0
        concentration = sum((count / samples) ** 2 for count in year_sample_counts)
        effective_years = 1.0 / concentration if concentration else 0.0

        loo_same = loo_tests = 0
        for year, (year_samples, year_hits) in yearly.items():
            remaining_samples = samples - year_samples
            remaining_baseline_samples = baseline_total_samples - year_baselines[year][0]
            if remaining_samples <= 0 or remaining_baseline_samples <= 0:
                continue
            remaining_rate = (hits[target] - year_hits[target]) / remaining_samples
            remaining_baseline_rate = (
                baseline_total_hits - year_baselines[year][1][target]
            ) / remaining_baseline_samples
            loo_delta = remaining_rate - remaining_baseline_rate
            loo_tests += 1
            loo_same += int(loo_delta * direction > 0)
        loo_direction_ratio = loo_same / loo_tests if loo_tests else 0.0

        share_limit = 0.40 if size <= 3 else 0.50
        failure_reasons = []
        if abs(overall_delta) < 0.025:
            failure_reasons.append("总偏差不足2.5%")
        if directional_years < minimum_stable_years:
            failure_reasons.append("有效方向年份不足")
        if year_direction_ratio < 0.60:
            failure_reasons.append("同向年份比例不足60%")
        if weighted_direction_ratio < 0.65:
            failure_reasons.append("年度样本加权同向率不足65%")
        if loo_direction_ratio < 0.80:
            failure_reasons.append("留一年同向率不足80%")
        if max_year_share > share_limit:
            failure_reasons.append("单一年份样本占比过高")
        if effective_years < max(2.5, minimum_stable_years * 0.65):
            failure_reasons.append("有效年份数不足")
        stability_passed = not failure_reasons
        coverage_factor = min(1.0, effective_years / minimum_stable_years)
        concentration_factor = min(1.0, (1.0 - max_year_share) / 0.70)
        stability_score = (
            weighted_direction_ratio
            * loo_direction_ratio
            * coverage_factor
            * concentration_factor
        )
        if not stability_passed:
            stability_score = 0.0
        return {
            "stability_passed": stability_passed,
            "stability_failure_reasons": failure_reasons,
            "stability_score": stability_score,
            "minimum_year_samples": minimum_year_samples,
            "minimum_stable_years": minimum_stable_years,
            "same_direction_years": same_years,
            "opposite_direction_years": opposite_years,
            "neutral_years": neutral_years,
            "year_direction_ratio": year_direction_ratio,
            "weighted_direction_ratio": weighted_direction_ratio,
            "loo_direction_ratio": loo_direction_ratio,
            "max_year_sample_share": max_year_share,
            "effective_years": effective_years,
            "yearly_details": yearly_details,
        }

    def _conditional_interaction_probabilities(
        self, current_context, store, baseline, year_baselines
    ):
        ordered = [zodiac for zodiac in self.zodiac_order if zodiac in current_context["set"]]
        candidates_by_target = collections.defaultdict(list)
        searched_by_size = collections.Counter()
        eligible_by_size = collections.Counter()
        stable_by_size = collections.Counter()
        all_candidate_rules = []

        for size in range(len(ordered), 0, -1):
            minimum_samples, minimum_years, alpha = self._interaction_thresholds(size)
            for combo in combinations(ordered, size):
                searched_by_size[size] += 1
                bucket = store.get(combo)
                if not bucket:
                    continue
                samples, hits, years, yearly = bucket
                if samples < minimum_samples or len(years) < minimum_years:
                    continue
                eligible_by_size[size] += 1
                reliability = samples / (samples + alpha)
                cross_year = min(1.0, len(years) / 8.0)
                specificity = 1.0 + 0.15 * (size - 1)
                for target in self.zodiac_order:
                    raw_hits = hits[target]
                    raw_rate = raw_hits / samples
                    smoothed = (raw_hits + alpha * baseline[target]) / (samples + alpha)
                    delta = smoothed - baseline[target]
                    low, high = self._wilson_interval(raw_hits, samples)
                    standard_error = math.sqrt(
                        max(
                            baseline[target] * (1.0 - baseline[target]) / samples,
                            1e-12,
                        )
                    )
                    z_score = (raw_rate - baseline[target]) / standard_error
                    p_value = math.erfc(abs(z_score) / math.sqrt(2.0))
                    lift = raw_rate / baseline[target] if baseline[target] > 0 else 1.0
                    stability = self._interaction_year_stability(
                        target,
                        size,
                        samples,
                        hits,
                        yearly,
                        year_baselines,
                        delta,
                    )
                    evidence_score = abs(delta) * reliability * cross_year * specificity
                    stable_evidence_score = evidence_score * stability["stability_score"]
                    interval_separates = (
                        low > baseline[target] + 0.03
                        or high < baseline[target] - 0.03
                    )
                    strong = (
                        stability["stability_passed"]
                        and
                        samples >= max(20, minimum_samples * 2)
                        and len(years) >= 8
                        and abs(delta) >= 0.05
                        and interval_separates
                    )
                    rule = (
                        {
                            "target": target,
                            "combo": list(combo),
                            "size": size,
                            "samples": samples,
                            "years": len(years),
                            "hits": raw_hits,
                            "raw_rate": raw_rate,
                            "smoothed_rate": smoothed,
                            "baseline_rate": baseline[target],
                            "delta": delta,
                            "wilson95_low": low,
                            "wilson95_high": high,
                            "lift_after_marginal": lift,
                            "z_score": z_score,
                            "p_value": p_value,
                            "strength": "strong" if strong else "weak",
                            "evidence_score": evidence_score,
                            "stable_evidence_score": stable_evidence_score,
                            **stability,
                        }
                    )
                    candidates_by_target[target].append(rule)
                    all_candidate_rules.append(rule)
                    if stability["stability_passed"]:
                        stable_by_size[size] += 1

        sorted_for_fdr = sorted(all_candidate_rules, key=lambda item: item["p_value"])
        running_q = 1.0
        total_tests = len(sorted_for_fdr)
        for reverse_index in range(total_tests - 1, -1, -1):
            rank = reverse_index + 1
            rule = sorted_for_fdr[reverse_index]
            running_q = min(running_q, rule["p_value"] * total_tests / rank)
            rule["fdr_q_value"] = min(1.0, running_q)
            interval_separates_marginal = (
                rule["wilson95_low"] > rule["baseline_rate"]
                or rule["wilson95_high"] < rule["baseline_rate"]
            )
            rejection_reasons = []
            if not rule["stability_passed"]:
                rejection_reasons.append("跨年份不稳定")
            if abs(rule["delta"]) < 0.025:
                rejection_reasons.append("扣除边际热度后偏差不足2.5%")
            if rule["fdr_q_value"] > 0.10:
                rejection_reasons.append("多重检验FDR未通过")
            if not interval_separates_marginal:
                rejection_reasons.append("置信区间未脱离边际概率")
            rule["debiased_passed"] = not rejection_reasons
            rule["debiased_rejection_reasons"] = rejection_reasons
            rule["debiased_evidence_score"] = (
                rule["stable_evidence_score"] * (1.0 - rule["fdr_q_value"])
                if rule["debiased_passed"]
                else 0.0
            )

        probabilities = dict(baseline)
        stable_probabilities = dict(baseline)
        debiased_probabilities = dict(baseline)
        selected_rules = {}
        selected_stable_rules = {}
        selected_debiased_rules = {}
        for target in self.zodiac_order:
            candidates = candidates_by_target.get(target, [])
            if not candidates:
                continue
            # 每个目标只选择一条条件规则，防止同一批历史锚点在多个子组合中重复加分。
            selected = max(
                candidates,
                key=lambda item: (
                    item["evidence_score"],
                    item["size"],
                    item["samples"],
                ),
            )
            probabilities[target] = selected["smoothed_rate"]
            selected_rules[target] = selected

            stable_candidates = [
                item for item in candidates if item["stability_passed"]
            ]
            if stable_candidates:
                stable_selected = max(
                    stable_candidates,
                    key=lambda item: (
                        item["stable_evidence_score"],
                        item["size"],
                        item["samples"],
                    ),
                )
                stable_probabilities[target] = baseline[target] + (
                    stable_selected["delta"] * stable_selected["stability_score"]
                )
                selected_stable_rules[target] = stable_selected

            debiased_candidates = [
                item for item in candidates if item.get("debiased_passed")
            ]
            if debiased_candidates:
                debiased_selected = max(
                    debiased_candidates,
                    key=lambda item: (
                        item["debiased_evidence_score"],
                        item["size"],
                        item["samples"],
                    ),
                )
                debiased_probabilities[target] = baseline[target] + (
                    debiased_selected["delta"]
                    * debiased_selected["stability_score"]
                    * (1.0 - debiased_selected["fdr_q_value"])
                )
                selected_debiased_rules[target] = debiased_selected

        return probabilities, stable_probabilities, debiased_probabilities, {
            "selected_rules": selected_rules,
            "selected_stable_rules": selected_stable_rules,
            "selected_debiased_rules": selected_debiased_rules,
            "multiple_testing": {
                "method": "Benjamini-Hochberg",
                "fdr_threshold": 0.10,
                "tests": total_tests,
            },
            "searched_combinations_by_size": {
                str(size): count for size, count in sorted(searched_by_size.items(), reverse=True)
            },
            "eligible_combinations_by_size": {
                str(size): count for size, count in sorted(eligible_by_size.items(), reverse=True)
            },
            "stable_target_rules_by_size": {
                str(size): count for size, count in sorted(stable_by_size.items(), reverse=True)
            },
        }

    def _update_pair_cooccurrence(self, store, outcome_set):
        store["samples"] += 1
        ordered = [zodiac for zodiac in self.zodiac_order if zodiac in outcome_set]
        for zodiac in ordered:
            store["individual"][zodiac] += 1
        for pair in combinations(ordered, 2):
            store["pairs"][pair] += 1

    def _pair_independence_audit(self, current_context, store):
        samples = store["samples"]
        if samples <= 0:
            return []
        ordered = [
            zodiac for zodiac in self.zodiac_order if zodiac in current_context["set"]
        ]
        audits = []
        for left, right in combinations(ordered, 2):
            left_rate = store["individual"][left] / samples
            right_rate = store["individual"][right] / samples
            observed_rate = store["pairs"][(left, right)] / samples
            expected_rate = left_rate * right_rate
            lift = observed_rate / expected_rate if expected_rate > 0 else 1.0
            leverage = observed_rate - expected_rate
            denominator = math.sqrt(
                max(left_rate * (1 - left_rate) * right_rate * (1 - right_rate), 1e-12)
            )
            phi = leverage / denominator
            audits.append(
                {
                    "pair": [left, right],
                    "samples": samples,
                    "cooccurrences": store["pairs"][(left, right)],
                    "observed_rate": observed_rate,
                    "expected_independent_rate": expected_rate,
                    "lift": lift,
                    "leverage": leverage,
                    "phi": phi,
                    "association": (
                        "residual_positive"
                        if lift >= 1.08 and phi >= 0.05
                        else "residual_negative"
                        if lift <= 0.92 and phi <= -0.05
                        else "explained_by_marginals"
                    ),
                }
            )
        audits.sort(key=lambda item: abs(item["phi"]), reverse=True)
        return audits

    @staticmethod
    def _diversity_bucket_probabilities(bucket, baseline, alpha):
        if not bucket:
            return dict(baseline)
        samples = bucket[0]
        counts = bucket[4]
        return {
            diversity: (counts[diversity] + alpha * baseline[diversity])
            / (samples + alpha)
            for diversity in baseline
        }

    def _f4_special_probabilities(
        self,
        current_context,
        store,
        baseline,
        year_baselines,
        diversity_baseline,
    ):
        """计算本命状态、重复状态及特码组合对下一期的候选影响。"""
        special = current_context["special"]
        identity_key = ("special", special)
        state_key = (
            "state",
            current_context["special_is_base"],
            current_context["special_repeated"],
            current_context["diversity"],
        )
        identity_bucket = store.get(identity_key)
        state_bucket = store.get(state_key)
        identity_probs = self._bucket_probabilities(identity_bucket, baseline, alpha=40.0)
        state_probs = self._bucket_probabilities(state_bucket, baseline, alpha=30.0)

        others = [
            zodiac
            for zodiac in self.zodiac_order
            if zodiac in current_context["set"] and zodiac != special
        ]
        candidates_by_target = collections.defaultdict(list)
        diversity_candidates = []
        searched_by_size = collections.Counter()
        eligible_by_size = collections.Counter()
        stable_by_size = collections.Counter()
        for other_size in range(len(others), -1, -1):
            total_size = other_size + 1
            minimum_samples, minimum_years, alpha = self._interaction_thresholds(
                total_size
            )
            for other_combo in combinations(others, other_size):
                searched_by_size[total_size] += 1
                key = (
                    "combo",
                    special,
                    current_context["special_is_base"],
                    current_context["special_repeated"],
                    other_combo,
                )
                bucket = store.get(key)
                if not bucket:
                    continue
                samples, hits, years, yearly, _ = bucket
                if samples < minimum_samples or len(years) < minimum_years:
                    continue
                eligible_by_size[total_size] += 1
                reliability = samples / (samples + alpha)
                cross_year = min(1.0, len(years) / 8.0)
                specificity = 1.0 + 0.18 * (total_size - 1)
                for target in self.zodiac_order:
                    raw_hits = hits[target]
                    raw_rate = raw_hits / samples
                    smoothed = (raw_hits + alpha * baseline[target]) / (samples + alpha)
                    delta = smoothed - baseline[target]
                    low, high = self._wilson_interval(raw_hits, samples)
                    stability = self._interaction_year_stability(
                        target,
                        total_size,
                        samples,
                        hits,
                        yearly,
                        year_baselines,
                        delta,
                    )
                    evidence_score = (
                        abs(delta) * reliability * cross_year * specificity
                    )
                    stable_evidence_score = (
                        evidence_score * stability["stability_score"]
                    )
                    rule = {
                        "target": target,
                        "special": special,
                        "other_combo": list(other_combo),
                        "combo": [special, *other_combo],
                        "size": total_size,
                        "special_is_base": current_context["special_is_base"],
                        "special_repeated": current_context["special_repeated"],
                        "samples": samples,
                        "years": len(years),
                        "hits": raw_hits,
                        "raw_rate": raw_rate,
                        "smoothed_rate": smoothed,
                        "baseline_rate": baseline[target],
                        "delta": delta,
                        "wilson95_low": low,
                        "wilson95_high": high,
                        "evidence_score": evidence_score,
                        "stable_evidence_score": stable_evidence_score,
                        **stability,
                    }
                    candidates_by_target[target].append(rule)
                    if stability["stability_passed"]:
                        stable_by_size[total_size] += 1

                diversity_probs = self._diversity_bucket_probabilities(
                    bucket, diversity_baseline, alpha
                )
                diversity_shift = sum(
                    abs(diversity_probs[value] - diversity_baseline[value])
                    for value in diversity_baseline
                )
                diversity_candidates.append(
                    {
                        "special": special,
                        "other_combo": list(other_combo),
                        "combo": [special, *other_combo],
                        "size": total_size,
                        "special_is_base": current_context["special_is_base"],
                        "special_repeated": current_context["special_repeated"],
                        "samples": samples,
                        "years": len(years),
                        "probabilities": diversity_probs,
                        "evidence_score": diversity_shift
                        * reliability
                        * cross_year
                        * specificity,
                    }
                )

        combo_probs = dict(baseline)
        selected_rules = {}
        selected_raw_rules = {}
        for target in self.zodiac_order:
            candidates = candidates_by_target.get(target, [])
            if not candidates:
                continue
            selected_raw_rules[target] = max(
                candidates,
                key=lambda item: (
                    item["evidence_score"],
                    item["size"],
                    item["samples"],
                ),
            )
            stable_candidates = [
                item for item in candidates if item["stability_passed"]
            ]
            if not stable_candidates:
                continue
            selected = max(
                stable_candidates,
                key=lambda item: (
                    item["stable_evidence_score"],
                    item["size"],
                    item["samples"],
                ),
            )
            combo_probs[target] = baseline[target] + (
                selected["delta"] * selected["stability_score"]
            )
            selected_rules[target] = selected

        f4_probabilities = {
            zodiac: 0.35 * identity_probs[zodiac]
            + 0.25 * state_probs[zodiac]
            + 0.40 * combo_probs[zodiac]
            for zodiac in self.zodiac_order
        }
        identity_diversity = self._diversity_bucket_probabilities(
            identity_bucket, diversity_baseline, alpha=40.0
        )
        state_diversity = self._diversity_bucket_probabilities(
            state_bucket, diversity_baseline, alpha=30.0
        )
        selected_diversity_rule = (
            max(
                diversity_candidates,
                key=lambda item: (
                    item["evidence_score"],
                    item["size"],
                    item["samples"],
                ),
            )
            if diversity_candidates
            else None
        )
        combo_diversity = (
            selected_diversity_rule["probabilities"]
            if selected_diversity_rule
            else diversity_baseline
        )
        diversity_probabilities = {
            value: 0.35 * identity_diversity[value]
            + 0.25 * state_diversity[value]
            + 0.40 * combo_diversity[value]
            for value in diversity_baseline
        }
        predicted_diversity = max(
            diversity_probabilities,
            key=lambda value: (diversity_probabilities[value], value),
        )
        baseline_predicted_diversity = max(
            diversity_baseline,
            key=lambda value: (diversity_baseline[value], value),
        )
        return f4_probabilities, {
            "special": special,
            "special_is_base": current_context["special_is_base"],
            "special_repeated": current_context["special_repeated"],
            "current_diversity": current_context["diversity"],
            "identity_samples": identity_bucket[0] if identity_bucket else 0,
            "state_samples": state_bucket[0] if state_bucket else 0,
            "selected_raw_rules": selected_raw_rules,
            "selected_stable_rules": selected_rules,
            "searched_combinations_by_size": {
                str(size): count
                for size, count in sorted(searched_by_size.items(), reverse=True)
            },
            "eligible_combinations_by_size": {
                str(size): count
                for size, count in sorted(eligible_by_size.items(), reverse=True)
            },
            "stable_target_rules_by_size": {
                str(size): count
                for size, count in sorted(stable_by_size.items(), reverse=True)
            },
            "next_diversity_probabilities": diversity_probabilities,
            "predicted_next_diversity": predicted_diversity,
            "baseline_next_diversity_probabilities": diversity_baseline,
            "baseline_predicted_next_diversity": baseline_predicted_diversity,
            "expected_next_diversity": sum(
                value * probability
                for value, probability in diversity_probabilities.items()
            ),
            "selected_diversity_rule": selected_diversity_rule,
        }

    def _f3_attribute_probabilities(
        self,
        current_context,
        store,
        baseline,
        year_baselines,
        diversity_baseline,
    ):
        candidates_by_target = collections.defaultdict(list)
        diversity_candidates = []
        eligible_states = []
        for descriptor in self._f3_state_keys(current_context):
            bucket = store.get(descriptor["key"])
            if not bucket:
                continue
            samples, hits, years, yearly, _ = bucket
            if (
                samples < descriptor["minimum_samples"]
                or len(years) < descriptor["minimum_years"]
            ):
                continue
            eligible_states.append(descriptor["label"])
            alpha = descriptor["alpha"]
            reliability = samples / (samples + alpha)
            cross_year = min(1.0, len(years) / 8.0)
            for target in self.zodiac_order:
                raw_hits = hits[target]
                raw_rate = raw_hits / samples
                smoothed = (raw_hits + alpha * baseline[target]) / (samples + alpha)
                delta = smoothed - baseline[target]
                low, high = self._wilson_interval(raw_hits, samples)
                stability = self._interaction_year_stability(
                    target,
                    descriptor["pseudo_size"],
                    samples,
                    hits,
                    yearly,
                    year_baselines,
                    delta,
                )
                evidence_score = (
                    abs(delta)
                    * reliability
                    * cross_year
                    * descriptor["specificity"]
                )
                candidates_by_target[target].append(
                    {
                        "target": target,
                        "state_type": descriptor["key"][0],
                        "state_label": descriptor["label"],
                        "samples": samples,
                        "years": len(years),
                        "hits": raw_hits,
                        "raw_rate": raw_rate,
                        "smoothed_rate": smoothed,
                        "baseline_rate": baseline[target],
                        "delta": delta,
                        "wilson95_low": low,
                        "wilson95_high": high,
                        "evidence_score": evidence_score,
                        "stable_evidence_score": (
                            evidence_score * stability["stability_score"]
                        ),
                        **stability,
                    }
                )
            diversity_probs = self._diversity_bucket_probabilities(
                bucket, diversity_baseline, alpha
            )
            diversity_shift = sum(
                abs(diversity_probs[value] - diversity_baseline[value])
                for value in diversity_baseline
            )
            diversity_candidates.append(
                {
                    "state_type": descriptor["key"][0],
                    "state_label": descriptor["label"],
                    "samples": samples,
                    "years": len(years),
                    "probabilities": diversity_probs,
                    "evidence_score": diversity_shift
                    * reliability
                    * cross_year
                    * descriptor["specificity"],
                }
            )

        probabilities = dict(baseline)
        selected_raw_rules = {}
        selected_stable_rules = {}
        for target in self.zodiac_order:
            candidates = candidates_by_target.get(target, [])
            if not candidates:
                continue
            selected_raw_rules[target] = max(
                candidates,
                key=lambda item: (item["evidence_score"], item["samples"]),
            )
            stable_candidates = [
                item for item in candidates if item["stability_passed"]
            ]
            if not stable_candidates:
                continue
            selected = max(
                stable_candidates,
                key=lambda item: (
                    item["stable_evidence_score"],
                    item["samples"],
                ),
            )
            probabilities[target] = baseline[target] + (
                selected["delta"] * selected["stability_score"]
            )
            selected_stable_rules[target] = selected

        selected_diversity_rule = (
            max(
                diversity_candidates,
                key=lambda item: (item["evidence_score"], item["samples"]),
            )
            if diversity_candidates
            else None
        )
        diversity_probabilities = (
            selected_diversity_rule["probabilities"]
            if selected_diversity_rule
            else diversity_baseline
        )
        predicted_diversity = max(
            diversity_probabilities,
            key=lambda value: (diversity_probabilities[value], value),
        )
        baseline_predicted_diversity = max(
            diversity_baseline,
            key=lambda value: (diversity_baseline[value], value),
        )
        return probabilities, {
            "profile": {
                "element_counts": {
                    element: current_context["element_counts"][index]
                    for index, element in enumerate(self.ELEMENT_ORDER)
                },
                "elements_present": list(current_context["elements_present"]),
                "yin_count": current_context["yin_count"],
                "yang_count": current_context["yang_count"],
                "domestic_count": current_context["domestic_count"],
                "wild_count": current_context["wild_count"],
            },
            "eligible_states": eligible_states,
            "selected_raw_rules": selected_raw_rules,
            "selected_stable_rules": selected_stable_rules,
            "next_diversity_probabilities": diversity_probabilities,
            "predicted_next_diversity": predicted_diversity,
            "baseline_next_diversity_probabilities": diversity_baseline,
            "baseline_predicted_next_diversity": baseline_predicted_diversity,
            "expected_next_diversity": sum(
                value * probability
                for value, probability in diversity_probabilities.items()
            ),
            "selected_diversity_rule": selected_diversity_rule,
        }

    def _f5_trajectory_probabilities(
        self, contexts, current, store, baseline, year_baselines
    ):
        probabilities = dict(baseline)
        states = {}
        selected_raw_rules = {}
        selected_stable_rules = {}
        for zodiac in self.zodiac_order:
            descriptors, state = self._f5_state_descriptors(contexts, current, zodiac)
            states[zodiac] = state
            candidates = []
            for descriptor in descriptors:
                bucket = store.get((zodiac, descriptor["key"]))
                if not bucket:
                    continue
                samples, hits, years, yearly = bucket
                if (
                    samples < descriptor["minimum_samples"]
                    or len(years) < descriptor["minimum_years"]
                ):
                    continue
                alpha = descriptor["alpha"]
                raw_hits = hits[zodiac]
                raw_rate = raw_hits / samples
                smoothed = (raw_hits + alpha * baseline[zodiac]) / (samples + alpha)
                delta = smoothed - baseline[zodiac]
                low, high = self._wilson_interval(raw_hits, samples)
                stability = self._interaction_year_stability(
                    zodiac,
                    descriptor["pseudo_size"],
                    samples,
                    hits,
                    yearly,
                    year_baselines,
                    delta,
                )
                reliability = samples / (samples + alpha)
                cross_year = min(1.0, len(years) / 8.0)
                evidence_score = (
                    abs(delta)
                    * reliability
                    * cross_year
                    * descriptor["specificity"]
                )
                candidates.append(
                    {
                        "target": zodiac,
                        "state_type": descriptor["key"][0],
                        "state_label": descriptor["label"],
                        "state": state,
                        "samples": samples,
                        "years": len(years),
                        "hits": raw_hits,
                        "raw_rate": raw_rate,
                        "smoothed_rate": smoothed,
                        "baseline_rate": baseline[zodiac],
                        "delta": delta,
                        "wilson95_low": low,
                        "wilson95_high": high,
                        "evidence_score": evidence_score,
                        "stable_evidence_score": (
                            evidence_score * stability["stability_score"]
                        ),
                        **stability,
                    }
                )
            if not candidates:
                continue
            selected_raw_rules[zodiac] = max(
                candidates,
                key=lambda item: (item["evidence_score"], item["samples"]),
            )
            stable_candidates = [
                item for item in candidates if item["stability_passed"]
            ]
            if not stable_candidates:
                continue
            selected = max(
                stable_candidates,
                key=lambda item: (
                    item["stable_evidence_score"],
                    item["samples"],
                ),
            )
            probabilities[zodiac] = baseline[zodiac] + (
                selected["delta"] * selected["stability_score"]
            )
            selected_stable_rules[zodiac] = selected
        return probabilities, {
            "states": states,
            "selected_raw_rules": selected_raw_rules,
            "selected_stable_rules": selected_stable_rules,
        }

    @staticmethod
    def _wilson_interval(successes, total, z=1.959963984540054):
        if total <= 0:
            return 0.0, 1.0
        proportion = successes / total
        denominator = 1 + z * z / total
        centre = proportion + z * z / (2 * total)
        margin = z * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        return (centre - margin) / denominator, (centre + margin) / denominator

    @staticmethod
    def _signal_tier(delta, weak_threshold=0.0125, strong_threshold=0.025):
        if delta >= strong_threshold:
            return "strong_positive"
        if delta >= weak_threshold:
            return "weak_positive"
        if delta <= -strong_threshold:
            return "strong_negative"
        if delta <= -weak_threshold:
            return "weak_negative"
        return "neutral"

    def _finder_consensus(
        self,
        target,
        features,
        prototype_meta,
        conditional_meta,
        f3_meta,
        f4_meta,
        f5_meta,
    ):
        """把同一查找器内部证据合并后再计票，避免重复加分。"""
        baseline = features["baseline"]
        f1_parts = [
            features[name] - baseline
            for name in ("diversity", "sequence", "prototype")
        ]
        signals = {
            "F1_cross_sequence_prototype": {
                "delta": sum(f1_parts) / len(f1_parts),
                "available": prototype_meta.get("selected", 0) >= 5,
                "internal_negative_votes": sum(delta <= -0.0125 for delta in f1_parts),
                "internal_positive_votes": sum(delta >= 0.0125 for delta in f1_parts),
            }
        }
        meta_sources = (
            (
                "F2_conditional",
                "stable_conditional",
                conditional_meta.get("selected_stable_rules", {}),
            ),
            ("F3_attributes", "f3_attributes", f3_meta.get("selected_stable_rules", {})),
            ("F4_special", "f4_special", f4_meta.get("selected_stable_rules", {})),
            ("F5_trajectory", "f5_trajectory", f5_meta.get("selected_stable_rules", {})),
            (
                "F67_debiased",
                "f67_debiased",
                conditional_meta.get("selected_debiased_rules", {}),
            ),
        )
        for finder, feature_name, selected_rules in meta_sources:
            signals[finder] = {
                "delta": features[feature_name] - baseline,
                "available": target in selected_rules,
            }
        for signal in signals.values():
            signal["tier"] = (
                self._signal_tier(signal["delta"])
                if signal["available"]
                else "unavailable"
            )
        f1_signal = signals["F1_cross_sequence_prototype"]
        if f1_signal["internal_negative_votes"] and f1_signal["internal_positive_votes"]:
            f1_signal["tier"] = "conflicted"
        elif f1_signal["internal_negative_votes"] < 2 and f1_signal["tier"] in {
            "strong_negative",
            "weak_negative",
        }:
            f1_signal["tier"] = "neutral"

        available = {
            finder: signal for finder, signal in signals.items() if signal["available"]
        }
        negative = [
            finder
            for finder, signal in available.items()
            if signal["tier"] in {"strong_negative", "weak_negative"}
        ]
        strong_negative = [
            finder
            for finder, signal in available.items()
            if signal["tier"] == "strong_negative"
        ]
        positive = [
            finder
            for finder, signal in available.items()
            if signal["tier"] in {"strong_positive", "weak_positive"}
        ]
        conflicted = [
            finder
            for finder, signal in available.items()
            if signal["tier"] == "conflicted"
        ]
        f2_rule = conditional_meta.get("selected_stable_rules", {}).get(target)
        f2_strict = bool(
            f2_rule
            and signals["F2_conditional"]["tier"] == "strong_negative"
            and f2_rule["samples"] >= 30
            and f2_rule["years"] >= 10
            and f2_rule["wilson95_high"] <= 0.20
        )
        hard_kill_eligible = bool(
            f2_strict
            and len(negative) >= 3
            and len(strong_negative) >= 2
            and not positive
            and not conflicted
        )
        return {
            "target": target,
            "signals": signals,
            "available_finders": list(available),
            "negative_finders": negative,
            "strong_negative_finders": strong_negative,
            "positive_finders": positive,
            "conflicted_finders": conflicted,
            "f2_strict_evidence": f2_strict,
            "hard_kill_eligible": hard_kill_eligible,
        }

    @staticmethod
    def _compact_historical_feature_row(row):
        """旧期只保留重算指标所需字段；最新期仍保留完整解释元数据。"""
        compact = {
            key: row[key]
            for key in (
                "current_index",
                "current_date",
                "target_date",
                "target_set",
                "target_zodiacs",
                "current_set",
                "features",
                "hard_kill_candidates",
            )
        }
        compact["f3"] = {
            key: row["f3"][key]
            for key in (
                "predicted_next_diversity",
                "baseline_predicted_next_diversity",
            )
        }
        compact["f4"] = {
            key: row["f4"][key]
            for key in (
                "predicted_next_diversity",
                "baseline_predicted_next_diversity",
            )
        }
        return compact

    def _walk_forward_feature_rows(
        self, records, warmup=200, state=None, return_state=False
    ):
        if state is None:
            contexts = self._build_ranking_contexts(records)
            baseline_samples = 0
            baseline_hits = collections.Counter()
            diversity_stats = {}
            sequence_stats = {}
            special_stats = {}
            special_state_stats = {}
            interaction_stats = {}
            interaction_year_baselines = {}
            f4_stats = {}
            f3_stats = {}
            f5_stats = {}
            pair_cooccurrence = {
                "samples": 0,
                "individual": collections.Counter(),
                "pairs": collections.Counter(),
            }
            baseline_diversity_counts = collections.Counter()
            rows = []
            start_current = 1
        else:
            if state.get("warmup") != warmup:
                raise ValueError("增量状态的warmup参数与当前模型不一致")
            previous_count = state.get("record_count", 0)
            if previous_count > len(records):
                raise ValueError("增量状态记录数超过当前数据记录数")
            contexts = list(state["contexts"])
            if len(contexts) != previous_count:
                raise ValueError("增量状态中的上下文数量不一致")
            if previous_count < len(records):
                contexts.extend(
                    self._build_ranking_contexts(records[previous_count:])
                )
            baseline_samples = state["baseline_samples"]
            baseline_hits = state["baseline_hits"]
            diversity_stats = state["diversity_stats"]
            sequence_stats = state["sequence_stats"]
            special_stats = state["special_stats"]
            special_state_stats = state["special_state_stats"]
            interaction_stats = state["interaction_stats"]
            interaction_year_baselines = state["interaction_year_baselines"]
            f4_stats = state["f4_stats"]
            f3_stats = state["f3_stats"]
            f5_stats = state["f5_stats"]
            pair_cooccurrence = state["pair_cooccurrence"]
            baseline_diversity_counts = state["baseline_diversity_counts"]
            rows = list(state["rows"])
            start_current = previous_count

        for current in range(start_current, len(contexts)):
            if (
                rows
                and rows[-1]["current_index"] == current - 1
                and rows[-1]["target_set"] is None
            ):
                rows[-1]["target_date"] = contexts[current]["date"]
                rows[-1]["target_set"] = contexts[current]["set"]
                rows[-1]["target_zodiacs"] = contexts[current]["zodiacs"]
            anchor = current - 1
            outcome_set = contexts[current]["set"]
            baseline_samples += 1
            baseline_diversity_counts[contexts[current]["diversity"]] += 1
            self._update_pair_cooccurrence(pair_cooccurrence, outcome_set)
            for zodiac in outcome_set:
                baseline_hits[zodiac] += 1

            anchor_ctx = contexts[anchor]
            anchor_year = int(anchor_ctx["date"][:4])
            self._update_bucket(interaction_year_baselines, anchor_year, outcome_set)
            self._update_bucket(diversity_stats, anchor_ctx["diversity"], outcome_set)
            self._update_bucket(special_stats, anchor_ctx["special"], outcome_set)
            special_state_key = (
                anchor_ctx["special_is_base"],
                anchor_ctx["special_repeated"],
                anchor_ctx["diversity"],
            )
            self._update_bucket(special_state_stats, special_state_key, outcome_set)
            self._update_interaction_stats(interaction_stats, anchor_ctx, outcome_set)
            self._update_f4_stats(f4_stats, anchor_ctx, contexts[current])
            self._update_f3_stats(f3_stats, anchor_ctx, contexts[current])
            self._update_f5_stats(f5_stats, contexts, anchor, contexts[current])
            if anchor >= 2:
                sequence_key = tuple(
                    contexts[anchor - offset]["diversity"] for offset in (2, 1, 0)
                )
                self._update_bucket(sequence_stats, sequence_key, outcome_set)

            if current < warmup or current < 2:
                continue

            baseline = {
                zodiac: (baseline_hits[zodiac] + 1) / (baseline_samples + 2)
                for zodiac in self.zodiac_order
            }
            current_ctx = contexts[current]
            diversity = self._bucket_probabilities(
                diversity_stats.get(current_ctx["diversity"]), baseline, alpha=30.0
            )
            current_sequence = tuple(
                contexts[current - offset]["diversity"] for offset in (2, 1, 0)
            )
            sequence = self._bucket_probabilities(
                sequence_stats.get(current_sequence), baseline, alpha=20.0
            )
            special_by_zodiac = self._bucket_probabilities(
                special_stats.get(current_ctx["special"]), baseline, alpha=30.0
            )
            current_special_state = (
                current_ctx["special_is_base"],
                current_ctx["special_repeated"],
                current_ctx["diversity"],
            )
            special_by_state = self._bucket_probabilities(
                special_state_stats.get(current_special_state), baseline, alpha=25.0
            )
            special = {
                zodiac: 0.65 * special_by_zodiac[zodiac]
                + 0.35 * special_by_state[zodiac]
                for zodiac in self.zodiac_order
            }
            prototype, prototype_meta = self._prototype_probabilities(
                contexts, current, baseline
            )
            conditional, stable_conditional, f67_debiased, conditional_meta = (
                self._conditional_interaction_probabilities(
                    current_ctx,
                    interaction_stats,
                    baseline,
                    interaction_year_baselines,
                )
            )
            diversity_baseline = {
                value: (baseline_diversity_counts[value] + 1)
                / (baseline_samples + 5)
                for value in range(3, 8)
            }
            f4_special, f4_meta = self._f4_special_probabilities(
                current_ctx,
                f4_stats,
                baseline,
                interaction_year_baselines,
                diversity_baseline,
            )
            f3_attributes, f3_meta = self._f3_attribute_probabilities(
                current_ctx,
                f3_stats,
                baseline,
                interaction_year_baselines,
                diversity_baseline,
            )
            f5_trajectory, f5_meta = self._f5_trajectory_probabilities(
                contexts,
                current,
                f5_stats,
                baseline,
                interaction_year_baselines,
            )
            features = {
                zodiac: {
                    "baseline": baseline[zodiac],
                    "diversity": diversity[zodiac],
                    "sequence": sequence[zodiac],
                    "prototype": prototype[zodiac],
                    "special": special[zodiac],
                    "conditional": conditional[zodiac],
                    "stable_conditional": stable_conditional[zodiac],
                    "f4_special": f4_special[zodiac],
                    "f3_attributes": f3_attributes[zodiac],
                    "f5_trajectory": f5_trajectory[zodiac],
                    "f67_debiased": f67_debiased[zodiac],
                }
                for zodiac in self.zodiac_order
            }
            finder_consensus = {}
            hard_kill_candidates = []
            for target in self.zodiac_order:
                consensus = self._finder_consensus(
                    target,
                    features[target],
                    prototype_meta,
                    conditional_meta,
                    f3_meta,
                    f4_meta,
                    f5_meta,
                )
                finder_consensus[target] = consensus
                if consensus["hard_kill_eligible"]:
                    hard_kill_candidates.append(
                        {
                            **consensus,
                            "status": "candidate_only_requires_policy_gate",
                        }
                    )
            target = contexts[current + 1] if current + 1 < len(contexts) else None
            rows.append(
                {
                    "current_index": current,
                    "current_date": current_ctx["date"],
                    "target_date": target["date"] if target else None,
                    "target_set": target["set"] if target else None,
                    "target_zodiacs": target["zodiacs"] if target else None,
                    "current_set": current_ctx["set"],
                    "features": features,
                    "prototype": prototype_meta,
                    "conditional": conditional_meta,
                    "f4": f4_meta,
                    "f3": f3_meta,
                    "f5": f5_meta,
                    "f67_pair_audit": self._pair_independence_audit(
                        current_ctx, pair_cooccurrence
                    ),
                    "finder_consensus": finder_consensus,
                    "hard_kill_candidates": hard_kill_candidates,
                }
            )
        cached_rows = [
            self._compact_historical_feature_row(row)
            for row in rows[:-1]
        ]
        if rows:
            cached_rows.append(rows[-1])
        state_out = {
            "warmup": warmup,
            "record_count": len(records),
            "contexts": contexts,
            "baseline_samples": baseline_samples,
            "baseline_hits": baseline_hits,
            "diversity_stats": diversity_stats,
            "sequence_stats": sequence_stats,
            "special_stats": special_stats,
            "special_state_stats": special_state_stats,
            "interaction_stats": interaction_stats,
            "interaction_year_baselines": interaction_year_baselines,
            "f4_stats": f4_stats,
            "f3_stats": f3_stats,
            "f5_stats": f5_stats,
            "pair_cooccurrence": pair_cooccurrence,
            "baseline_diversity_counts": baseline_diversity_counts,
            "rows": cached_rows,
        }
        if return_state:
            return contexts, rows, state_out
        return contexts, rows

    def _rank_feature_row(self, row, weights, hard_kill_enabled=False):
        hard_kills = (
            {item["target"] for item in row["hard_kill_candidates"]}
            if hard_kill_enabled
            else set()
        )
        scored = []
        for order, zodiac in enumerate(self.zodiac_order):
            components = row["features"][zodiac]
            score = sum(weights[name] * components[name] for name in weights)
            if zodiac in hard_kills:
                score = -1.0
            scored.append((score, -order, zodiac))
        scored.sort(reverse=True)
        return [zodiac for _, _, zodiac in scored[:6]], scored

    def _evaluate_feature_rows(self, rows, weights, hard_kill_enabled=False):
        hit_distribution = collections.Counter()
        ball_hit_distribution = collections.Counter()
        yearly = collections.defaultdict(lambda: {"periods": 0, "eligible": 0, "hit5": 0, "ball_hit5": 0, "hit_sum": 0})
        total = eligible = hit5 = ball_hit5 = unique_sum = ball_sum = 0
        for row in rows:
            if row["target_set"] is None:
                continue
            top6, _ = self._rank_feature_row(
                row, weights, hard_kill_enabled=hard_kill_enabled
            )
            top6_set = set(top6)
            unique_hits = len(top6_set & set(row["target_set"]))
            ball_hits = sum(zodiac in top6_set for zodiac in row["target_zodiacs"])
            target_diversity = len(row["target_set"])
            is_eligible = target_diversity >= 5
            total += 1
            eligible += int(is_eligible)
            hit5 += int(unique_hits >= 5)
            ball_hit5 += int(ball_hits >= 5)
            unique_sum += unique_hits
            ball_sum += ball_hits
            hit_distribution[unique_hits] += 1
            ball_hit_distribution[ball_hits] += 1
            year = int(row["target_date"][:4])
            stat = yearly[year]
            stat["periods"] += 1
            stat["eligible"] += int(is_eligible)
            stat["hit5"] += int(unique_hits >= 5)
            stat["ball_hit5"] += int(ball_hits >= 5)
            stat["hit_sum"] += unique_hits

        low, high = self._wilson_interval(hit5, eligible)
        yearly_report = {}
        for year, stat in sorted(yearly.items()):
            yearly_report[str(year)] = {
                **stat,
                "hit5_eligible_rate": stat["hit5"] / stat["eligible"] if stat["eligible"] else 0.0,
                "ball_hit5_rate": stat["ball_hit5"] / stat["periods"] if stat["periods"] else 0.0,
                "average_unique_hits": stat["hit_sum"] / stat["periods"] if stat["periods"] else 0.0,
            }
        return {
            "periods": total,
            "eligible_periods": eligible,
            "impossible_periods": total - eligible,
            "unique_hit5": hit5,
            "unique_hit5_all_rate": hit5 / total if total else 0.0,
            "unique_hit5_eligible_rate": hit5 / eligible if eligible else 0.0,
            "unique_hit5_eligible_wilson95": [low, high],
            "ball_hit5": ball_hit5,
            "ball_hit5_rate": ball_hit5 / total if total else 0.0,
            "average_unique_hits": unique_sum / total if total else 0.0,
            "average_ball_hits": ball_sum / total if total else 0.0,
            "unique_hit_distribution": {str(key): value for key, value in sorted(hit_distribution.items())},
            "ball_hit_distribution": {str(key): value for key, value in sorted(ball_hit_distribution.items())},
            "yearly": yearly_report,
        }

    @staticmethod
    def _evaluate_diversity_feature(rows, feature_key):
        total = exact = within_one = 0
        baseline_exact = baseline_within_one = 0
        absolute_error = 0
        baseline_absolute_error = 0
        predicted_distribution = collections.Counter()
        baseline_predicted_distribution = collections.Counter()
        actual_distribution = collections.Counter()
        for row in rows:
            if row["target_set"] is None:
                continue
            predicted = row[feature_key]["predicted_next_diversity"]
            baseline_predicted = row[feature_key]["baseline_predicted_next_diversity"]
            actual = len(row["target_set"])
            total += 1
            exact += int(predicted == actual)
            within_one += int(abs(predicted - actual) <= 1)
            absolute_error += abs(predicted - actual)
            baseline_exact += int(baseline_predicted == actual)
            baseline_within_one += int(abs(baseline_predicted - actual) <= 1)
            baseline_absolute_error += abs(baseline_predicted - actual)
            predicted_distribution[predicted] += 1
            baseline_predicted_distribution[baseline_predicted] += 1
            actual_distribution[actual] += 1
        return {
            "periods": total,
            "exact_hits": exact,
            "exact_rate": exact / total if total else 0.0,
            "within_one_hits": within_one,
            "within_one_rate": within_one / total if total else 0.0,
            "mean_absolute_error": absolute_error / total if total else 0.0,
            "rolling_mode_baseline_exact_hits": baseline_exact,
            "rolling_mode_baseline_exact_rate": baseline_exact / total if total else 0.0,
            "rolling_mode_baseline_within_one_rate": (
                baseline_within_one / total if total else 0.0
            ),
            "rolling_mode_baseline_mean_absolute_error": (
                baseline_absolute_error / total if total else 0.0
            ),
            "predicted_distribution": {
                str(key): value for key, value in sorted(predicted_distribution.items())
            },
            "actual_distribution": {
                str(key): value for key, value in sorted(actual_distribution.items())
            },
            "rolling_mode_baseline_predicted_distribution": {
                str(key): value
                for key, value in sorted(baseline_predicted_distribution.items())
            },
        }

    @staticmethod
    def _weight_grid(feature_names, units=4):
        for values in product(range(units + 1), repeat=len(feature_names)):
            if sum(values) != units:
                continue
            yield {
                name: value / units for name, value in zip(feature_names, values)
            }

    @staticmethod
    def _joint_weight_allowed(weights):
        """限制同源特征总权重，防止一个查找器拆成多列后重复加分。"""
        family_weights = {
            "F1": sum(
                weights.get(name, 0.0)
                for name in ("diversity", "sequence", "prototype")
            ),
            "F2": weights.get("stable_conditional", 0.0),
            "F3": weights.get("f3_attributes", 0.0),
            "F4": weights.get("special", 0.0) + weights.get("f4_special", 0.0),
            "F5": weights.get("f5_trajectory", 0.0),
            "F67": weights.get("f67_debiased", 0.0),
        }
        caps = {"F1": 0.75, "F2": 0.25, "F3": 0.25, "F4": 0.25, "F5": 0.25, "F67": 0.25}
        return all(family_weights[name] <= caps[name] for name in family_weights)

    @staticmethod
    def _renormalize_weights(weights):
        positive = {name: value for name, value in weights.items() if value > 0}
        total = sum(positive.values())
        if not total:
            return {}
        return {name: value / total for name, value in positive.items()}

    @staticmethod
    def _pearson(values_a, values_b):
        if len(values_a) != len(values_b) or len(values_a) < 2:
            return 0.0
        mean_a = sum(values_a) / len(values_a)
        mean_b = sum(values_b) / len(values_b)
        covariance = sum(
            (value_a - mean_a) * (value_b - mean_b)
            for value_a, value_b in zip(values_a, values_b)
        )
        variance_a = sum((value - mean_a) ** 2 for value in values_a)
        variance_b = sum((value - mean_b) ** 2 for value in values_b)
        if variance_a <= 0 or variance_b <= 0:
            return 0.0
        return covariance / math.sqrt(variance_a * variance_b)

    def _feature_dependency_audit(self, rows, feature_names):
        vectors = {name: [] for name in feature_names}
        for row in rows:
            for zodiac in self.zodiac_order:
                baseline = row["features"][zodiac]["baseline"]
                for name in feature_names:
                    vectors[name].append(row["features"][zodiac][name] - baseline)
        pairs = []
        for first, second in combinations(feature_names, 2):
            correlation = self._pearson(vectors[first], vectors[second])
            pairs.append(
                {
                    "features": [first, second],
                    "correlation": correlation,
                    "overlap_level": (
                        "high_overlap"
                        if abs(correlation) >= 0.80
                        else "moderate_overlap"
                        if abs(correlation) >= 0.55
                        else "low_overlap"
                    ),
                }
            )
        pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)
        return pairs

    def _build_ablation_report(self, validation, holdout, reference_weights, feature_names):
        leave_one_out = []
        for removed in reference_weights:
            weights = self._renormalize_weights(
                {
                    name: value
                    for name, value in reference_weights.items()
                    if name != removed
                }
            )
            if not weights:
                continue
            leave_one_out.append(
                {
                    "removed": removed,
                    "weights": weights,
                    "validation": self._evaluate_feature_rows(validation, weights),
                    "holdout": self._evaluate_feature_rows(holdout, weights),
                }
            )

        add_one_in = []
        for added in feature_names:
            if reference_weights.get(added, 0.0) > 0:
                continue
            weights = {
                name: value * 0.75 for name, value in reference_weights.items()
            }
            weights[added] = weights.get(added, 0.0) + 0.25
            weights = self._renormalize_weights(weights)
            if not self._joint_weight_allowed(weights):
                continue
            add_one_in.append(
                {
                    "added": added,
                    "weights": weights,
                    "validation": self._evaluate_feature_rows(validation, weights),
                    "holdout": self._evaluate_feature_rows(holdout, weights),
                }
            )
        return {
            "reference_weights": reference_weights,
            "reference_validation": self._evaluate_feature_rows(
                validation, reference_weights
            ),
            "reference_holdout": self._evaluate_feature_rows(holdout, reference_weights),
            "leave_one_out": leave_one_out,
            "add_one_in": add_one_in,
        }

    def _evaluate_hard_kill_policy(self, rows):
        triggers = false_kills = correct_exclusions = 0
        yearly = collections.defaultdict(
            lambda: {"triggers": 0, "false_kills": 0, "correct_exclusions": 0}
        )
        for row in rows:
            if row["target_set"] is None:
                continue
            target_set = set(row["target_set"])
            year = str(row["target_date"][:4])
            for candidate in row["hard_kill_candidates"]:
                triggers += 1
                yearly[year]["triggers"] += 1
                if candidate["target"] in target_set:
                    false_kills += 1
                    yearly[year]["false_kills"] += 1
                else:
                    correct_exclusions += 1
                    yearly[year]["correct_exclusions"] += 1
        low, high = self._wilson_interval(false_kills, triggers)
        return {
            "triggers": triggers,
            "false_kills": false_kills,
            "correct_exclusions": correct_exclusions,
            "false_kill_rate": false_kills / triggers if triggers else 0.0,
            "false_kill_wilson95": [low, high],
            "yearly": dict(sorted(yearly.items())),
        }

    def _latest_strength_report(self, row, weights):
        report = {}
        for zodiac in self.zodiac_order:
            baseline = row["features"][zodiac]["baseline"]
            components = []
            for feature, weight in weights.items():
                delta = row["features"][zodiac][feature] - baseline
                components.append(
                    {
                        "feature": feature,
                        "weight": weight,
                        "delta": delta,
                        "tier": self._signal_tier(delta),
                        "score_contribution": weight * delta,
                    }
                )
            components.sort(
                key=lambda item: abs(item["score_contribution"]), reverse=True
            )
            report[zodiac] = components
        return report

    @staticmethod
    def _random_top6_expected(rows):
        denominator = math.comb(12, 6)
        probabilities = []
        for row in rows:
            if row["target_set"] is None or len(row["target_set"]) < 5:
                continue
            diversity = len(row["target_set"])
            probability = sum(
                math.comb(diversity, hits)
                * math.comb(12 - diversity, 6 - hits)
                / denominator
                for hits in range(5, min(6, diversity) + 1)
                if 0 <= 6 - hits <= 12 - diversity
            )
            probabilities.append(probability)
        return sum(probabilities) / len(probabilities) if probabilities else 0.0

    def build_walk_forward_top6_report(
        self,
        records,
        warmup=200,
        weight_tuning_cutoff="2021-12-31",
        validation_cutoff="2023-12-31",
        f5_enabled=False,
        precomputed=None,
        cached_selection=None,
    ):
        """严格逐期回测并生成下一期Top6；任何预测都只使用当时已知数据。"""
        if precomputed is None:
            contexts, rows = self._walk_forward_feature_rows(records, warmup=warmup)
        else:
            contexts, rows = precomputed
        completed_rows = [row for row in rows if row["target_set"] is not None]
        tuning = [
            row
            for row in completed_rows
            if row["target_date"] <= weight_tuning_cutoff
        ]
        validation = [
            row
            for row in completed_rows
            if weight_tuning_cutoff < row["target_date"] <= validation_cutoff
        ]
        holdout = [
            row for row in completed_rows if row["target_date"] > validation_cutoff
        ]
        if not tuning or not validation or not holdout:
            first_split = max(1, int(len(completed_rows) * 0.65))
            second_split = max(first_split + 1, int(len(completed_rows) * 0.80))
            tuning = completed_rows[:first_split]
            validation = completed_rows[first_split:second_split]
            holdout = completed_rows[second_split:]

        feature_names = [
            "baseline",
            "diversity",
            "sequence",
            "prototype",
            "special",
            "f67_debiased",
        ]
        if f5_enabled:
            feature_names.append("f5_trajectory")
        joint_feature_names = [
            "baseline",
            "diversity",
            "sequence",
            "prototype",
            "special",
            "stable_conditional",
            "f3_attributes",
            "f4_special",
            "f67_debiased",
        ]
        if f5_enabled:
            joint_feature_names.append("f5_trajectory")
        selection_reusable = bool(
            cached_selection
            and cached_selection.get("model_version") == self.TOP6_MODEL_VERSION
            and cached_selection.get("weight_tuning_cutoff") == weight_tuning_cutoff
            and cached_selection.get("validation_cutoff") == validation_cutoff
            and cached_selection.get("f5_enabled") is bool(f5_enabled)
            and cached_selection.get("candidate_weights")
            and cached_selection.get("joint_candidate_weights")
        )
        if selection_reusable:
            best_weights = cached_selection["candidate_weights"]
            best_metrics = self._evaluate_feature_rows(tuning, best_weights)
        else:
            best_weights = None
            best_metrics = None
            best_objective = None
            for weights in self._weight_grid(feature_names):
                if weights["f67_debiased"] <= 0:
                    continue
                metrics = self._evaluate_feature_rows(tuning, weights)
                concentration = sum(value * value for value in weights.values())
                objective = (
                    metrics["unique_hit5_eligible_rate"],
                    metrics["average_unique_hits"],
                    metrics["ball_hit5_rate"],
                    -concentration,
                )
                if best_objective is None or objective > best_objective:
                    best_objective = objective
                    best_weights = weights
                    best_metrics = metrics

        frequency_weights = {name: float(name == "baseline") for name in feature_names}
        official_weights = {
            "sequence": 0.25,
            "prototype": 0.50,
            "special": 0.25,
        }
        f5_audit_weights = {
            "sequence": 0.25,
            "prototype": 0.50,
            "f5_trajectory": 0.25,
        }
        previous_stage_weights = f5_audit_weights if f5_enabled else official_weights
        f3_audit_weights = {
            "baseline": 0.50,
            "sequence": 0.25,
            "f3_attributes": 0.25,
        }
        f3_candidate_validation = self._evaluate_feature_rows(
            validation, f3_audit_weights
        )
        f3_candidate_holdout = self._evaluate_feature_rows(
            holdout, f3_audit_weights
        )
        f4_audit_weights = {
            "baseline": 0.25,
            "prototype": 0.25,
            "special": 0.25,
            "f4_special": 0.25,
        }
        f4_candidate_validation = self._evaluate_feature_rows(
            validation, f4_audit_weights
        )
        f4_candidate_holdout = self._evaluate_feature_rows(
            holdout, f4_audit_weights
        )
        f5_candidate_validation = self._evaluate_feature_rows(
            validation, f5_audit_weights
        )
        f5_candidate_holdout = self._evaluate_feature_rows(
            holdout, f5_audit_weights
        )
        f5_off_validation = self._evaluate_feature_rows(validation, official_weights)
        f5_off_holdout = self._evaluate_feature_rows(holdout, official_weights)
        f5_validation_gate = (
            f5_candidate_validation["unique_hit5_eligible_rate"]
            >= f5_off_validation["unique_hit5_eligible_rate"] + 0.005
            and f5_candidate_validation["average_unique_hits"]
            >= f5_off_validation["average_unique_hits"] - 0.01
            and f5_candidate_validation["ball_hit5_rate"]
            >= f5_off_validation["ball_hit5_rate"] - 0.01
        )
        f5_holdout_gate = (
            f5_candidate_holdout["unique_hit5_eligible_rate"]
            >= f5_off_holdout["unique_hit5_eligible_rate"]
            and f5_candidate_holdout["average_unique_hits"]
            >= f5_off_holdout["average_unique_hits"] - 0.01
            and f5_candidate_holdout["ball_hit5_rate"]
            >= f5_off_holdout["ball_hit5_rate"] - 0.01
        )
        f5_gate_passed = f5_validation_gate and f5_holdout_gate
        candidate_validation = self._evaluate_feature_rows(validation, best_weights)
        previous_validation = self._evaluate_feature_rows(
            validation, previous_stage_weights
        )
        candidate_holdout = self._evaluate_feature_rows(holdout, best_weights)
        previous_stage_holdout = self._evaluate_feature_rows(
            holdout, previous_stage_weights
        )
        validation_gate_passed = (
            best_weights["f67_debiased"] > 0
            and candidate_validation["unique_hit5_eligible_rate"]
            >= previous_validation["unique_hit5_eligible_rate"] + 0.005
            and candidate_validation["average_unique_hits"]
            >= previous_validation["average_unique_hits"] - 0.01
            and candidate_validation["ball_hit5_rate"]
            >= previous_validation["ball_hit5_rate"] - 0.01
        )
        final_holdout_gate_passed = (
            candidate_holdout["unique_hit5_eligible_rate"]
            >= previous_stage_holdout["unique_hit5_eligible_rate"]
            and candidate_holdout["average_unique_hits"]
            >= previous_stage_holdout["average_unique_hits"] - 0.01
            and candidate_holdout["ball_hit5_rate"]
            >= previous_stage_holdout["ball_hit5_rate"] - 0.01
        )
        f67_feature_deployed = (
            validation_gate_passed and final_holdout_gate_passed
        )
        stage_reference_weights = (
            best_weights if f67_feature_deployed else previous_stage_weights
        )

        if selection_reusable:
            joint_candidate_weights = cached_selection["joint_candidate_weights"]
            joint_candidate_tuning = self._evaluate_feature_rows(
                tuning, joint_candidate_weights
            )
        else:
            joint_candidate_weights = None
            joint_candidate_tuning = None
            joint_objective = None
            for weights in self._weight_grid(joint_feature_names):
                if not self._joint_weight_allowed(weights):
                    continue
                metrics = self._evaluate_feature_rows(tuning, weights)
                distance = sum(
                    abs(weights.get(name, 0.0) - stage_reference_weights.get(name, 0.0))
                    for name in set(weights) | set(stage_reference_weights)
                )
                concentration = sum(value * value for value in weights.values())
                objective = (
                    metrics["unique_hit5_eligible_rate"],
                    metrics["average_unique_hits"],
                    metrics["ball_hit5_rate"],
                    -distance,
                    -concentration,
                )
                if joint_objective is None or objective > joint_objective:
                    joint_objective = objective
                    joint_candidate_weights = self._renormalize_weights(weights)
                    joint_candidate_tuning = metrics

        joint_reference_validation = self._evaluate_feature_rows(
            validation, stage_reference_weights
        )
        joint_reference_holdout = self._evaluate_feature_rows(
            holdout, stage_reference_weights
        )
        joint_candidate_validation = self._evaluate_feature_rows(
            validation, joint_candidate_weights
        )
        joint_candidate_holdout = self._evaluate_feature_rows(
            holdout, joint_candidate_weights
        )
        joint_validation_gate = (
            joint_candidate_validation["unique_hit5_eligible_rate"]
            >= joint_reference_validation["unique_hit5_eligible_rate"] + 0.005
            and joint_candidate_validation["average_unique_hits"]
            >= joint_reference_validation["average_unique_hits"] - 0.01
            and joint_candidate_validation["ball_hit5_rate"]
            >= joint_reference_validation["ball_hit5_rate"] - 0.01
        )
        joint_holdout_gate = (
            joint_candidate_holdout["unique_hit5_eligible_rate"]
            >= joint_reference_holdout["unique_hit5_eligible_rate"]
            and joint_candidate_holdout["average_unique_hits"]
            >= joint_reference_holdout["average_unique_hits"] - 0.01
            and joint_candidate_holdout["ball_hit5_rate"]
            >= joint_reference_holdout["ball_hit5_rate"] - 0.01
        )
        joint_feature_deployed = joint_validation_gate and joint_holdout_gate
        deployed_weights = (
            joint_candidate_weights
            if joint_feature_deployed
            else stage_reference_weights
        )

        hard_kill_validation = self._evaluate_hard_kill_policy(validation)
        hard_kill_holdout = self._evaluate_hard_kill_policy(holdout)
        hard_kill_validation_ranking = self._evaluate_feature_rows(
            validation, deployed_weights, hard_kill_enabled=True
        )
        hard_kill_holdout_ranking = self._evaluate_feature_rows(
            holdout, deployed_weights, hard_kill_enabled=True
        )
        no_kill_validation_ranking = self._evaluate_feature_rows(
            validation, deployed_weights
        )
        no_kill_holdout_ranking = self._evaluate_feature_rows(
            holdout, deployed_weights
        )
        hard_kill_evidence_gate = (
            hard_kill_validation["triggers"] >= 30
            and hard_kill_validation["false_kills"] == 0
            and hard_kill_holdout["triggers"] >= 30
            and hard_kill_holdout["false_kills"] == 0
        )
        hard_kill_performance_gate = (
            hard_kill_validation_ranking["unique_hit5_eligible_rate"]
            >= no_kill_validation_ranking["unique_hit5_eligible_rate"]
            and hard_kill_validation_ranking["average_unique_hits"]
            >= no_kill_validation_ranking["average_unique_hits"]
            and hard_kill_validation_ranking["ball_hit5_rate"]
            >= no_kill_validation_ranking["ball_hit5_rate"]
            and hard_kill_holdout_ranking["unique_hit5_eligible_rate"]
            >= no_kill_holdout_ranking["unique_hit5_eligible_rate"]
            and hard_kill_holdout_ranking["average_unique_hits"]
            >= no_kill_holdout_ranking["average_unique_hits"]
            and hard_kill_holdout_ranking["ball_hit5_rate"]
            >= no_kill_holdout_ranking["ball_hit5_rate"]
        )
        hard_kill_policy_deployed = (
            hard_kill_evidence_gate and hard_kill_performance_gate
        )
        deployed_tuning = self._evaluate_feature_rows(
            tuning, deployed_weights, hard_kill_enabled=hard_kill_policy_deployed
        )
        holdout_metrics = self._evaluate_feature_rows(
            holdout, deployed_weights, hard_kill_enabled=hard_kill_policy_deployed
        )
        frequency_holdout = self._evaluate_feature_rows(holdout, frequency_weights)
        all_metrics = self._evaluate_feature_rows(
            completed_rows,
            deployed_weights,
            hard_kill_enabled=hard_kill_policy_deployed,
        )
        ablation_report = self._build_ablation_report(
            validation, holdout, deployed_weights, joint_feature_names
        )
        dependency_audit = self._feature_dependency_audit(
            tuning, joint_feature_names
        )
        f4_diversity_validation = self._evaluate_diversity_feature(validation, "f4")
        f4_diversity_holdout = self._evaluate_diversity_feature(holdout, "f4")
        f4_diversity_validation_gate = (
            f4_diversity_validation["exact_rate"]
            >= f4_diversity_validation["rolling_mode_baseline_exact_rate"] + 0.005
            and f4_diversity_validation["mean_absolute_error"]
            <= f4_diversity_validation["rolling_mode_baseline_mean_absolute_error"]
        )
        f4_diversity_holdout_gate = (
            f4_diversity_holdout["exact_rate"]
            >= f4_diversity_holdout["rolling_mode_baseline_exact_rate"]
            and f4_diversity_holdout["mean_absolute_error"]
            <= f4_diversity_holdout["rolling_mode_baseline_mean_absolute_error"]
        )
        f4_diversity_feature_deployed = (
            f4_diversity_validation_gate and f4_diversity_holdout_gate
        )
        f3_diversity_validation = self._evaluate_diversity_feature(validation, "f3")
        f3_diversity_holdout = self._evaluate_diversity_feature(holdout, "f3")
        f3_diversity_validation_gate = (
            f3_diversity_validation["exact_rate"]
            >= f3_diversity_validation["rolling_mode_baseline_exact_rate"] + 0.005
            and f3_diversity_validation["mean_absolute_error"]
            <= f3_diversity_validation["rolling_mode_baseline_mean_absolute_error"]
        )
        f3_diversity_holdout_gate = (
            f3_diversity_holdout["exact_rate"]
            >= f3_diversity_holdout["rolling_mode_baseline_exact_rate"]
            and f3_diversity_holdout["mean_absolute_error"]
            <= f3_diversity_holdout["rolling_mode_baseline_mean_absolute_error"]
        )
        f3_diversity_feature_deployed = (
            f3_diversity_validation_gate and f3_diversity_holdout_gate
        )

        latest_row = rows[-1]
        latest_top6, latest_scored = self._rank_feature_row(
            latest_row,
            deployed_weights,
            hard_kill_enabled=hard_kill_policy_deployed,
        )
        latest_f5_off_top6, _ = self._rank_feature_row(
            latest_row, official_weights
        )
        latest_f5_on_top6, _ = self._rank_feature_row(
            latest_row, f5_audit_weights
        )
        ranking = []
        for score, _, zodiac in latest_scored:
            ranking.append(
                {
                    "zodiac": zodiac,
                    "probability": score,
                    "in_top6": zodiac in latest_top6,
                    "components": latest_row["features"][zodiac],
                }
            )
        latest_f4 = dict(latest_row["f4"])
        latest_f4["deployed_next_diversity"] = (
            latest_f4["predicted_next_diversity"]
            if f4_diversity_feature_deployed
            else latest_f4["baseline_predicted_next_diversity"]
        )
        latest_f4["deployed_next_diversity_probabilities"] = (
            latest_f4["next_diversity_probabilities"]
            if f4_diversity_feature_deployed
            else latest_f4["baseline_next_diversity_probabilities"]
        )
        latest_f3 = dict(latest_row["f3"])
        latest_f3["deployed_next_diversity"] = (
            latest_f3["predicted_next_diversity"]
            if f3_diversity_feature_deployed
            else latest_f3["baseline_predicted_next_diversity"]
        )
        latest_f3["deployed_next_diversity_probabilities"] = (
            latest_f3["next_diversity_probabilities"]
            if f3_diversity_feature_deployed
            else latest_f3["baseline_next_diversity_probabilities"]
        )

        raw_diversity_counts = collections.Counter(
            context["diversity"] for context in contexts[1:]
        )
        theoretically_possible = sum(
            count for diversity, count in raw_diversity_counts.items() if diversity >= 5
        )
        return {
            "model_version": self.TOP6_MODEL_VERSION,
            "definition": "Top6与下一期去重生肖集合交集不少于5；另报7个号码位置覆盖不少于5",
            "no_future_leakage": True,
            "incremental_selection_reused": selection_reusable,
            "source_snapshot": {
                "record_count": len(records),
                "first_date": records[0]["date"],
                "latest_date": records[-1]["date"],
                "latest_issue": records[-1]["issue"],
                "latest_numbers": records[-1]["numbers"],
            },
            "warmup_periods": warmup,
            "weight_tuning_cutoff": weight_tuning_cutoff,
            "validation_cutoff": validation_cutoff,
            "development": deployed_tuning,
            "candidate_tuning": best_metrics,
            "candidate_validation": candidate_validation,
            "previous_stage_validation": previous_validation,
            "holdout": holdout_metrics,
            "candidate_holdout_audit": candidate_holdout,
            "frequency_baseline_holdout": frequency_holdout,
            "previous_stage_holdout": previous_stage_holdout,
            "random_top6_expected_hit5_eligible_rate": self._random_top6_expected(
                holdout
            ),
            "all_walk_forward": all_metrics,
            "weights": deployed_weights,
            "candidate_weights": best_weights,
            "joint_candidate_weights": joint_candidate_weights,
            "joint_candidate_tuning": joint_candidate_tuning,
            "joint_candidate_validation": joint_candidate_validation,
            "joint_candidate_holdout_audit": joint_candidate_holdout,
            "joint_reference_validation": joint_reference_validation,
            "joint_reference_holdout": joint_reference_holdout,
            "joint_validation_gate_passed": joint_validation_gate,
            "joint_holdout_gate_passed": joint_holdout_gate,
            "joint_feature_deployed": joint_feature_deployed,
            "joint_gate_reason": (
                "联合模型通过验收期与最终隔离期，已进入正式排名"
                if joint_feature_deployed
                else (
                    "联合模型通过2022-2023验收，但在2024-2026最终隔离期退化"
                    if joint_validation_gate
                    else "联合模型未同时改善验收期中5率、平均命中和号码位置覆盖"
                )
            ),
            "weight_family_caps": {
                "F1": 0.75,
                "F2": 0.25,
                "F3": 0.25,
                "F4": 0.25,
                "F5": 0.25,
                "F67": 0.25,
            },
            "ablation": ablation_report,
            "feature_dependency_audit": dependency_audit,
            "hard_kill_policy_deployed": hard_kill_policy_deployed,
            "hard_kill_evidence_gate_passed": hard_kill_evidence_gate,
            "hard_kill_performance_gate_passed": hard_kill_performance_gate,
            "hard_kill_validation": hard_kill_validation,
            "hard_kill_holdout_audit": hard_kill_holdout,
            "hard_kill_validation_ranking": hard_kill_validation_ranking,
            "hard_kill_holdout_ranking": hard_kill_holdout_ranking,
            "hard_kill_policy": {
                "required_independent_negative_finders": 3,
                "required_strong_negative_finders": 2,
                "requires_strict_f2": True,
                "positive_evidence_veto": True,
                "minimum_validation_triggers": 30,
                "minimum_holdout_triggers": 30,
                "allowed_false_kills": 0,
            },
            "f5_enabled": bool(f5_enabled),
            "f5_active": bool(f5_enabled),
            "f5_gate_passed": f5_gate_passed,
            "f5_candidate_weights": f5_audit_weights,
            "f5_candidate_validation": f5_candidate_validation,
            "f5_candidate_holdout_audit": f5_candidate_holdout,
            "f5_off_validation": f5_off_validation,
            "f5_off_holdout": f5_off_holdout,
            "f5_gate_reason": (
                "F5通过验收期和最终隔离期"
                if f5_gate_passed
                else (
                    "F5通过2022-2023验收，但最终隔离期退化"
                    if f5_validation_gate
                    else "F5未同时改善验收期中5率、平均命中和号码位置覆盖"
                )
            ),
            "f5_effect_reason": (
                "开关已开启，F5正在影响本次排名"
                + ("，且已通过门禁" if f5_gate_passed else "；这是未过门禁的人工对照模式")
                if f5_enabled
                else "开关已关闭，正式排名完全不使用F5"
            ),
            "f67_feature_deployed": f67_feature_deployed,
            "f67_gate_reason": (
                "F6/F7去偏关联通过验收期和最终隔离期，已进入正式排名"
                if f67_feature_deployed
                else (
                    "F6/F7通过2022-2023验收，但最终隔离期退化；拒绝上线"
                    if validation_gate_passed
                    else "F6/F7未同时改善验收期中5率、平均命中和号码位置覆盖；拒绝上线"
                )
            ),
            "f67_packaging_disabled": True,
            "f3_feature_deployed": False,
            "f3_candidate_weights": f3_audit_weights,
            "f3_candidate_validation": f3_candidate_validation,
            "f3_candidate_holdout_audit": f3_candidate_holdout,
            "f3_gate_reason": (
                "上一阶段F3属性分组特征未通过门禁，继续仅作审计"
            ),
            "f4_feature_deployed": False,
            "f4_candidate_weights": f4_audit_weights,
            "f4_candidate_validation": f4_candidate_validation,
            "f4_candidate_holdout_audit": f4_candidate_holdout,
            "stability_feature_deployed": False,
            "interaction_feature_deployed": False,
            "validation_gate_passed": validation_gate_passed,
            "final_holdout_gate_passed": final_holdout_gate_passed,
            "f4_gate_reason": (
                "上一阶段F4特码组合特征未通过门禁，继续仅作审计"
            ),
            "stability_gate_reason": (
                "上一阶段跨年份稳定条件特征未通过门禁，继续仅作审计"
            ),
            "interaction_gate_reason": (
                "跨年份稳定条件特征未通过上一阶段门禁，继续仅作审计"
            ),
            "f4_diversity_feature_deployed": f4_diversity_feature_deployed,
            "f4_diversity_validation_gate_passed": f4_diversity_validation_gate,
            "f4_diversity_holdout_gate_passed": f4_diversity_holdout_gate,
            "f4_diversity_gate_reason": (
                "F4去重数同时超过滚动众数基线并通过最终隔离期，已上线"
                if f4_diversity_feature_deployed
                else "F4去重数未稳定超过滚动众数基线，仅保留审计"
            ),
            "f4_diversity_validation": f4_diversity_validation,
            "f4_diversity_holdout": f4_diversity_holdout,
            "f3_diversity_feature_deployed": f3_diversity_feature_deployed,
            "f3_diversity_validation_gate_passed": f3_diversity_validation_gate,
            "f3_diversity_holdout_gate_passed": f3_diversity_holdout_gate,
            "f3_diversity_gate_reason": (
                "F3去重数同时超过滚动众数基线并通过最终隔离期，已上线"
                if f3_diversity_feature_deployed
                else "F3去重数未稳定超过滚动众数基线，仅保留审计"
            ),
            "f3_diversity_validation": f3_diversity_validation,
            "f3_diversity_holdout": f3_diversity_holdout,
            "latest": {
                "current_date": latest_row["current_date"],
                "top6": latest_top6,
                "f5_off_top6": latest_f5_off_top6,
                "f5_on_top6": latest_f5_on_top6,
                "ranking": ranking,
                "prototype": latest_row["prototype"],
                "conditional": latest_row["conditional"],
                "f4": latest_f4,
                "f3": latest_f3,
                "f5": latest_row["f5"],
                "f67_pair_audit": latest_row["f67_pair_audit"],
                "finder_consensus": latest_row["finder_consensus"],
                "signal_strength": self._latest_strength_report(
                    latest_row, deployed_weights
                ),
                "hard_kill_candidates": (
                    latest_row["hard_kill_candidates"]
                    if hard_kill_policy_deployed
                    else []
                ),
                "hard_kill_audit_candidates": latest_row["hard_kill_candidates"],
            },
            "logical_ceiling": {
                "total_periods": len(contexts) - 1,
                "periods_with_at_least_5_unique": theoretically_possible,
                "all_period_max_rate": theoretically_possible / (len(contexts) - 1),
                "diversity_counts": {str(key): value for key, value in sorted(raw_diversity_counts.items())},
            },
        }

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
                draw_date = record.get("date")
                if draw_date:
                    zmap = self.get_zodiac_map_by_date(draw_date)
                elif record.get("base_zodiac"):
                    zmap = self._get_zodiac_map(record["base_zodiac"])
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
