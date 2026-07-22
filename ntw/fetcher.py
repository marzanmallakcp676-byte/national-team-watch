"""数据获取层 — AKShare封装，获取ETF份额和行情数据"""

import pandas as pd
from datetime import datetime, date
from typing import Optional, Dict, List
import warnings
import os
warnings.filterwarnings("ignore")

# 屏蔽 AKShare 的 tqdm 进度条输出
os.environ['TQDM_DISABLE'] = '1'

from .config import CORE_ETFS, ETF_MAP


def fetch_sse_etf_shares(target_date: Optional[str] = None) -> pd.DataFrame:
    """
    获取上交所ETF当日份额数据

    Args:
        target_date: 日期字符串 'YYYYMMDD'，默认最新交易日

    Returns:
        DataFrame with columns: 基金代码, 基金简称, 份额(万份), ...
    """
    import akshare as ak

    if target_date is None:
        target_date = datetime.now().strftime("%Y%m%d")

    try:
        df = ak.fund_etf_scale_sse(date=target_date)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"  [WARN] 上交所份额数据获取失败 ({target_date}): {e}")

    return pd.DataFrame()


def fetch_etf_spot_all() -> pd.DataFrame:
    """获取全市场ETF实时行情（含IOPV、资金流指标）"""
    import akshare as ak
    try:
        df = ak.fund_etf_spot_em()
        return df
    except Exception as e:
        print(f"  [WARN] ETF实时行情获取失败: {e}")
        return pd.DataFrame()


def fetch_etf_hist(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取单只ETF历史日线数据

    Args:
        code: ETF交易代码
        start_date: 'YYYYMMDD'
        end_date: 'YYYYMMDD'
    """
    import akshare as ak
    try:
        # fund_etf_hist_em 使用 'YYYYMMDD' 格式的日期范围
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=""
        )
        return df
    except Exception as e:
        print(f"  [WARN] ETF {code} 历史数据获取失败: {e}")
        return pd.DataFrame()


def fetch_all_core_etf_data(target_date: Optional[str] = None) -> Dict[str, dict]:
    """
    获取所有核心ETF的当日关键数据

    Args:
        target_date: 目标日期 'YYYYMMDD'，默认今天

    Returns:
        {code: {"shares": 份额(万份), "nav": 净值, "price": 价格, "fund_flow": 资金流向}}
    """
    results = {}

    # 1. 获取上交所份额数据
    if target_date is None:
        today_str = datetime.now().strftime("%Y%m%d")
    else:
        today_str = target_date
    sse_df = fetch_sse_etf_shares(today_str)

    # 2. 获取全市场行情（含资金流）
    spot_df = fetch_etf_spot_all()

    # 3. 组装数据
    for etf in CORE_ETFS:
        data = {"code": etf.code, "name": etf.name, "exchange": etf.exchange,
                "shares": None, "nav": None, "price": None, "fund_flow_main": None}

        # 从份额数据中提取 (上交所)
        # fund_etf_scale_sse columns: 序号, 基金代码, 基金简称, ETF类型, 统计日期, 基金份额
        if not sse_df.empty and etf.exchange == "SSE":
            try:
                match = sse_df[sse_df["基金代码"].astype(str) == etf.code]
                if match.empty:
                    match = sse_df[sse_df["基金代码"].astype(str).str.contains(etf.code, na=False)]
                if not match.empty:
                    row = match.iloc[0]
                    # 基金份额 单位是 份，转换为万份
                    raw_shares = float(row["基金份额"])
                    data["shares"] = raw_shares / 10000  # 份 → 万份
            except Exception as e:
                print(f"  [WARN] 无法解析 {etf.code} 份额数据: {e}")

        # 从行情数据中提取 (全市场)
        if not spot_df.empty:
            try:
                spot_match = spot_df[spot_df["代码"].astype(str) == etf.code]
                if spot_match.empty:
                    spot_match = spot_df[spot_df["代码"].astype(str).str.contains(etf.code, na=False)]
                if not spot_match.empty:
                    row = spot_match.iloc[0]
                    data["price"] = float(row.get("最新价", 0) or 0)
                    data["nav"] = float(row.get("IOPV", 0) or row.get("单位净值", 0) or 0)
                    data["fund_flow_main"] = float(row.get("主力净流入", 0) or 0)
            except Exception as e:
                print(f"  [WARN] 无法解析 {etf.code} 行情数据: {e}")

        results[etf.code] = data

    return results


def estimate_fund_flow(shares_change: float, avg_price: float) -> float:
    """
    根据份额变化估算资金流向（亿元）

    Args:
        shares_change: 份额变化量（万份）
        avg_price: 平均成交价格

    Returns:
        估算资金净流入/流出金额（亿元）
    """
    if shares_change is None or avg_price is None or avg_price == 0:
        return 0.0
    # 份额(万份) * 价格(元) / 10000 = 亿元
    return round(shares_change * avg_price / 10000, 2)
