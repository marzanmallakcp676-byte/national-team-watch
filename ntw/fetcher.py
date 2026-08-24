"""数据获取层 — AKShare封装，获取ETF份额和行情数据"""

import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple
import warnings
import os
warnings.filterwarnings("ignore")

# 屏蔽 AKShare 的 tqdm 进度条输出
os.environ['TQDM_DISABLE'] = '1'

from .config import CORE_ETFS, ETF_MAP


def fetch_sse_etf_shares(target_date: Optional[str] = None, timeout: int = 20) -> pd.DataFrame:
    """
    获取上交所ETF当日份额数据（直接请求上交所接口）。

    不用 akshare.fund_etf_scale_sse 的原因：
    - 它对无数据日期（周末/当天未发布）会抛 KeyError 而不是返回空表；
    - 其内部 requests.get 未设超时，接口变慢时页面会无限挂起。

    Args:
        target_date: 日期字符串 'YYYYMMDD'，默认今天
        timeout: 请求超时秒数

    Returns:
        DataFrame with columns: 基金代码, 基金简称, ETF类型, 统计日期, 基金份额(份)
    """
    import requests

    if target_date is None:
        target_date = datetime.now().strftime("%Y%m%d")
    data_str = "-".join([target_date[:4], target_date[4:6], target_date[6:]])

    url = "https://query.sse.com.cn/commonQuery.do"
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
        "STAT_DATE": data_str,
    }
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/88.0.4324.150 Safari/537.36",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        data_json = r.json()
        rows = (data_json.get("result") or []) or (data_json.get("pageHelp", {}).get("data") or [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).rename(
            columns={
                "NUM": "序号",
                "SEC_CODE": "基金代码",
                "SEC_NAME": "基金简称",
                "ETF_TYPE": "ETF类型",
                "STAT_DATE": "统计日期",
                "TOT_VOL": "基金份额",
            }
        )
        # 与 akshare 行为一致：万份 → 份（调用方会再转回万份）
        df["基金份额"] = pd.to_numeric(df["基金份额"], errors="coerce") * 10000
        return df[["基金代码", "基金简称", "ETF类型", "统计日期", "基金份额"]]
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


def _build_core_etf_data(today_str: str, sse_df: pd.DataFrame, spot_df: pd.DataFrame) -> Dict[str, dict]:
    """把上交所份额表 + 全市场行情表组装成 {code: {shares, nav, price, fund_flow_main}}"""
    results = {}
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
        # 注意: 东财接口列名历史上有过变更（IOPV→IOPV实时估值、主力净流入→主力净流入-净额），新旧兼容
        if not spot_df.empty:
            try:
                spot_match = spot_df[spot_df["代码"].astype(str) == etf.code]
                if spot_match.empty:
                    spot_match = spot_df[spot_df["代码"].astype(str).str.contains(etf.code, na=False)]
                if not spot_match.empty:
                    row = spot_match.iloc[0]
                    data["price"] = float(row.get("最新价", 0) or 0)
                    data["nav"] = float(row.get("IOPV实时估值") or row.get("IOPV") or row.get("单位净值") or 0)
                    data["fund_flow_main"] = float(row.get("主力净流入-净额") or row.get("主力净流入") or 0)
            except Exception as e:
                print(f"  [WARN] 无法解析 {etf.code} 行情数据: {e}")

        results[etf.code] = data

    return results


def fetch_all_core_etf_data(target_date: Optional[str] = None) -> Dict[str, dict]:
    """
    获取所有核心ETF的当日关键数据

    Args:
        target_date: 目标日期 'YYYYMMDD'，默认今天

    Returns:
        {code: {"shares": 份额(万份), "nav": 净值, "price": 价格, "fund_flow": 资金流向}}
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y%m%d")

    sse_df = fetch_sse_etf_shares(target_date)
    spot_df = fetch_etf_spot_all()
    return _build_core_etf_data(target_date, sse_df, spot_df)


def fetch_latest_core_etf_data(start_date: Optional[str] = None,
                               max_back_days: int = 10) -> Tuple[Dict[str, dict], str]:
    """
    获取最近一个交易日的核心ETF数据（带自动回退）。

    上交所份额数据为 T+1 发布：周日/周一晚间及长假期间，当天（甚至昨天）的数据
    往往尚未发布。本函数从 start_date 向前逐日回退（自动跳过周末），
    直到找到第一个有份额数据的日期。

    Args:
        start_date: 起始日期 'YYYYMMDD'，默认今天
        max_back_days: 最多回退的自然日天数

    Returns:
        (data_dict, actual_date_str) — 全部回退失败时 actual_date 为 start_date，data 全为 None，
        由调用方降级处理
    """
    if start_date is None:
        start_date = datetime.now().strftime("%Y%m%d")

    start_dt = datetime.strptime(start_date, "%Y%m%d")

    # 行情数据与日期无关，只取一次
    spot_df = fetch_etf_spot_all()

    for back in range(max_back_days + 1):
        d = (start_dt - timedelta(days=back)).strftime("%Y%m%d")
        if (start_dt - timedelta(days=back)).weekday() >= 5:
            continue  # 周末不请求，节省时间
        sse_df = fetch_sse_etf_shares(d)
        if sse_df.empty:
            continue
        data = _build_core_etf_data(d, sse_df, spot_df)
        if any(v["shares"] is not None for v in data.values()):
            return data, d

    # 全部回退失败（长假/接口异常）：返回空数据，由调用方降级
    return _build_core_etf_data(start_date, pd.DataFrame(), spot_df), start_date


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
