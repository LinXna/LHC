import requests
import json
import time
from datetime import datetime

# 配置
BASE_URL = "https://1680660.com/smallSix/findSmallSixHistory.do"
HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh-HK;q=0.9,zh;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://6hch.com",
    "Referer": "https://6hch.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# 如果需要携带 Cookie（假设你已经从浏览器复制了有效的 Cookie）
# 请将下面的字符串替换为实际的 Cookie 值
COOKIES = {
    # "sessionid": "your_session_id",  # 示例
}


def fetch_year_data(year):
    """请求指定年份的数据"""
    payload = {"year": str(year), "type": "1"}
    try:
        # 使用 Session 可以自动处理 Cookie（如需）
        session = requests.Session()
        # 如果设置了 COOKIES，则加载
        if COOKIES:
            session.cookies.update(COOKIES)

        response = session.post(BASE_URL, data=payload, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"请求 {year} 年数据失败: {e}")
        return None


def save_year_data(year, data):
    """将数据保存为 <year>.json"""
    filename = f"{year}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存 {year} 年数据到 {filename}")


def main():
    current_year = datetime.now().year
    # 获取最近20年（包含当前年）
    years = range(current_year, current_year - 20, -1)  # 2026, 2025, 2024, 2023, 2022

    for year in years:
        print(f"⏳ 正在获取 {year} 年的数据...")
        data = fetch_year_data(year)
        if data is not None:
            save_year_data(year, data)
        else:
            print(f"❌ 跳过 {year} 年（获取失败）")
        # 每次请求间隔1秒，避免过于频繁
        time.sleep(1)

    print("🎉 所有年份数据获取完成！")


if __name__ == "__main__":
    main()
