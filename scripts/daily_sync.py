#!/usr/bin/env python3
"""GitHub Actions 每日同步脚本 — 拉取ETF份额数据，追加到 history.csv

晚间运行，交易日当天收盘后同步当日数据（T+0）。
- 自动回退：当天数据未发布时自动取最近交易日
- 更健壮的错误处理
- 支持手动指定日期范围
"""

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


# ── Helper: 获取目标同步日期列表 ──
def get_target_dates() -> list:
    """
    智能确定需要同步的日期。
    - 工作日：同步当天（T+0数据）
    - 周一：同步上周五 + 上周四（补周末缺口）
    返回日期字符串列表 ['YYYYMMDD', ...]
    """
    today = datetime.now()
    dates = []

    # 从今天开始查（晚间运行，当天数据已发布）
    check = today
    attempts = 0
    while attempts < 5:
        if check.weekday() < 5:  # 周一到周五
            dates.append(check.strftime("%Y%m%d"))
        check = check - timedelta(days=1)
        attempts += 1

    # 只保留最近的2个有效交易日（够cover周末）
    return dates[:2]


# ── AKShare fetch ──
def fetch_sse_shares(date_str):
    # 复用 ntw.fetcher 的稳健实现：带超时、无数据日期返回空表而不是抛 KeyError
    from ntw.fetcher import fetch_sse_etf_shares
    return fetch_sse_etf_shares(date_str)


def fetch_spot_prices():
    import akshare as ak
    try:
        return ak.fund_etf_spot_em()
    except Exception as e:
        print(f"  [WARN] 行情数据获取失败: {e}")
        return pd.DataFrame()


def load_history():
    """加载历史CSV，保证类型一致"""
    if os.path.exists(HISTORY_CSV):
        history = pd.read_csv(HISTORY_CSV)
        history["code"] = history["code"].astype(str)
        history["trade_date"] = history["trade_date"].astype(str)
        return history
    return pd.DataFrame()


def sync_date(date_str, history=None):
    """
    同步单个日期的ETF数据。
    返回: (new_records_count, updated_history_df or None)
    """
    if history is None:
        history = load_history()

    print(f"  同步日期: {date_str}")

    # 1. 检查是否已有该日期数据
    if not history.empty:
        existing = history[history["trade_date"] == date_str]
        if not existing.empty:
            # 检查是否全是零变化（说明上次同步有bug）
            all_zero = (existing["shares_change"] == 0).all()
            if not all_zero:
                print(f"    {date_str} 数据已存在且正常，跳过")
                return 0, None
            else:
                print(f"    {date_str} 数据存在但变化量为零，重新计算...")
                # 删除旧数据，重新同步
                history = history[history["trade_date"] != date_str]

    # 2. 获取上交所ETF份额
    sse_df = fetch_sse_shares(date_str)
    if sse_df.empty:
        print(f"    {date_str} 上交所数据为空（非交易日或T+1数据尚未发布）")
        return 0, None

    # 3. 获取行情价格
    spot_df = fetch_spot_prices()

    # 4. 找前一交易日数据用于计算变化
    prev_shares = {}
    if not history.empty:
        # 找严格早于当前日期的最大日期
        earlier = history[history["trade_date"] < date_str]
        if not earlier.empty:
            latest_prev_date = earlier["trade_date"].max()
            prev_data = history[history["trade_date"] == latest_prev_date]
            for _, row in prev_data.iterrows():
                prev_shares[row["code"]] = row["shares"]
            print(f"    前一交易日: {latest_prev_date}, {len(prev_shares)}只ETF可用作比较基准")
        else:
            print(f"    无更早日期的历史数据，无法计算变化量")
    else:
        print(f"    历史CSV为空，无法计算变化量")

    # 5. 组装新记录
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
                except Exception:
                    pass

        # 计算变化（使用严格的前一交易日数据）
        prev_share = prev_shares.get(etf.code)
        if prev_share is not None and prev_share > 0:
            change = round(shares - prev_share, 2)
            change_pct = round((change / prev_share) * 100, 2)
            est_flow = round(change * price / 10000, 2)
        else:
            change = 0.0
            change_pct = 0.0
            est_flow = 0.0

        # 信号判断
        signal = "none"
        if change_pct > 5 and abs(change) > 10:
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
        print(f"    无匹配的ETF数据")
        return 0, None

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

    # 去重 & 排序
    history = history.drop_duplicates(subset=["code", "trade_date"], keep="last")
    history = history.sort_values(["trade_date", "code"])

    return len(new_records), history


def main():
    target_dates = sorted(get_target_dates())  # 升序：从旧到新处理
    print(f"目标同步日期: {target_dates}")

    history = load_history()
    print(f"现有历史记录: {len(history)} 条")

    total_new = 0
    for date_str in target_dates:
        n, updated = sync_date(date_str, history)
        if updated is not None:
            history = updated
            total_new += n
        print()  # 空行分隔

    if total_new > 0:
        history.to_csv(HISTORY_CSV, index=False, encoding="utf-8")
        print(f"✅ 总计追加 {total_new} 条新记录")
        print(f"   历史总记录: {len(history)} 条")
        latest = history["trade_date"].max()
        print(f"   最新数据日期: {latest}")
    else:
        # 即使没新数据也保存（可能修复了零变化数据）
        history.to_csv(HISTORY_CSV, index=False, encoding="utf-8")
        print(f"ℹ️  无新数据追加，最新日期: {history['trade_date'].max() if not history.empty else 'N/A'}")


if __name__ == "__main__":
    main()
