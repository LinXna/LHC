import unittest
import tempfile
import json
import os
from zodiac_analyzer import ZodiacPatternAnalyzer  # 请替换为实际模块名

class TestLoadDataSorting(unittest.TestCase):
    def setUp(self):
        self.analyzer = ZodiacPatternAnalyzer(base_zodiac="马")

    def create_fake_json(self, dir_path, filename, issues):
        """创建一个假的 JSON 文件，包含乱序的 bodyList，每期仅有必要字段"""
        body = []
        for issue in issues:
            body.append(
                {
                    "issue": issue,
                    "preDrawCode": "1,2,3,4,5,6,7",  # 合法号码
                    "preDrawDate": "2024-01-01",
                }
            )
        data = {"result": {"data": {"bodyList": body}}}
        filepath = os.path.join(dir_path, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return filepath

    def test_global_sort_across_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 文件1：期号 1001, 1003
            self.create_fake_json(tmpdir, "file1.json", [1001, 1003])
            # 文件2：期号 1000, 1002
            self.create_fake_json(tmpdir, "file2.json", [1000, 1002])

            records = self.analyzer.load_json_data(data_dir=tmpdir)
            issues = [r["issue"] for r in records]

            # 验证长度
            self.assertEqual(len(issues), 4)
            # 验证严格升序
            self.assertEqual(issues, sorted(issues))
            # 验证与期望值一致
            self.assertEqual(issues, [1000, 1001, 1002, 1003])


if __name__ == "__main__":
    unittest.main()
