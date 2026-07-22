#!/usr/bin/env python3
"""GitHub Actions 每日同步脚本 — 拉取ETF份额数据，追加到 history.csv"""

import pandas as pd
import os, sys, warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
os.environ['TQDM_DISABLE'] = '1'

# ── Path setup ──
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from ntw.config import CORE_ETFS

DATA_DIR = os.path.join(BASE, "data")
HISTORY_CSV = os.path.join(DATA_DIR, "history.csv")
os.makedirs(DATA_DIR, exist_ok=True)

# ── AKShare fetch ──
def fetch_sse_shares(date_str):
    import akshare as ak
    try:
        df = ak.fund_etf_scale_sse(date=date_str)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"  [WARN] SSE数据获取失败 ({date_str}): {e}")
    return pd.DataFrame()

def fetch_spot_prices():
    import akshare as ak
    try:
        return ak.fund_etf_spot_em()
    except:
        return pd.DataFrame()


def main():
    # 使用昨日日期（T+1数据）
    yesterday = (datetime.now() - timedelta(days=1))
    if yesterday.weekday() >= 5:  # 周末跳过
        print(f"  {yesterday.strftime('%Y-%m-%d')} 是周末，跳过")
        return

    date_str = yesterday.strftime("%Y%m%d")
    print(f"同步日期: {date_str}")

    # 1. 获取上交所ETF份额
    sse_df = fetch_sse_shares(date_str)
    if sse_df.empty:
        print("  上交所数据为空，可能尚未更新（T+1延迟）")
        return

    # 2. 获取行情价格
    spot_df = fetch_spot_prices()

    # 3. 读取现有历史CSV
    if os.path.exists(HISTORY_CSV):
        history = pd.read_csv(HISTORY_CSV)
        history["trade_date"] = history["trade_date"].astype(str)
    else:
        history = pd.DataFrame()

    # 4. 检查是否已有今日数据
    if not history.empty:
        existing = history[history["trade_date"] == date_str]
        if not existing.empty:
            print(f"  {date_str} 数据已存在，跳过")
            return

    # 5. 上一次数据用于计算变化
    prev_shares = {}
    if not history.empty:
        latest_date = history["trade_date"].max()
        prev_data = history[history["trade_date"] == latest_date]
        for _, row in prev_data.iterrows():
            prev_shares[row["code"]] = row["shares"]

    # 6. 组装新记录
    new_records = []
    for etf in CORE_ETFS:
        shares = None
        price = 1.0

        # 从上交所数据提取份额
        if not sse_df.empty and etf.exchange == "SSE":
            match = sse_df[sse_df["基金代码"].astype(str) == etf.code]
            if not match.empty:
                shares = float(match.iloc[0]["基金份额"]) / 10000  # 份→万份

        if shares is None:
            continue

        # 从行情数据提取价格
        if not spot_df.empty:
            spot_match = spot_df[spot_df["代码"].astype(str) == etf.code]
            if not spot_match.empty:
                try:
                    price = float(spot_match.iloc[0].get("最新价", 1.0) or 1.0)
                except:
                    pass

        # 计算变化
        prev_share = prev_shares.get(etf.code)
        if prev_share is not None and prev_share > 0:
            change = shares - prev_share
            change_pct = round((change / prev_share) * 100, 2)
            est_flow = round(change * price / 10000, 2)
        else:
            change = 0.0
            change_pct = 0.0
            est_flow = 0.0

        # 信号判断（简略版）
        signal = "none"
        if change_pct > 5 and change > 10:
            signal = "entry"
        elif change_pct < -5 and abs(change) > 10:
            signal = "exit"

        new_records.append({
            "code": etf.code,
            "trade_date": date_str,
            "shares": shares,
            "price": price,
            "shares_change": change,
            "shares_change_pct": change_pct,
            "est_flow": est_flow,
            "signal": signal,
        })

    if not new_records:
        print("  无新数据")
        return

    # 确保字符串类型
    new_df = pd.DataFrame(new_records)
    new_df["code"] = new_df["code"].astype(str)
    new_df["trade_date"] = new_df["trade_date"].astype(str)

    if history.empty:
        history = new_df
    else:
        history["code"] = history["code"].astype(str)
        history["trade_date"] = history["trade_date"].astype(str)
        history = pd.concat([history, new_df], ignore_index=True)

    # 去重
    history = history.drop_duplicates(subset=["code", "trade_date"], keep="last")
    history = history.sort_values(["trade_date", "code"])

    history.to_csv(HISTORY_CSV, index=False, encoding="utf-8")
    print(f"  已追加 {len(new_records)} 条记录 ({date_str})")
    print(f"  历史总记录: {len(history)} 条")


if __name__ == "__main__":
    main()
