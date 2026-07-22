"""国家队信号分析引擎"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from .config import CORE_ETFS, ETF_MAP, SIGNAL_THRESHOLDS
from .fetcher import fetch_all_core_etf_data, fetch_sse_etf_shares, estimate_fund_flow
from .db import (
    save_etf_shares, save_daily_change, save_signal,
    get_etf_history, get_daily_changes, get_signals,
    get_latest_trade_date, get_all_latest_shares, init_db
)


@dataclass
class ETFChange:
    """单只ETF日变化"""
    code: str
    name: str
    shares: float           # 当前份额（万份）
    shares_change: float    # 日变化量（万份）
    shares_change_pct: float  # 日变化率（%）
    price: float            # 收盘价
    est_flow: float         # 估算资金流（亿元）
    signal: str = "none"    # entry/exit/none


@dataclass
class DayAnalysis:
    """单日分析结果"""
    trade_date: str
    etf_changes: List[ETFChange] = field(default_factory=list)
    total_est_flow: float = 0.0       # 合计估算资金流（亿元）
    entry_count: int = 0               # 触发入场信号的ETF数
    exit_count: int = 0                # 触发离场信号的ETF数
    national_team_signal: str = "none" # none/entry/exit/rotation
    signal_description: str = ""


def analyze_daily_data(trade_date: str) -> DayAnalysis:
    """
    分析单日数据，判断国家队信号

    Args:
        trade_date: 交易日 'YYYY-MM-DD'
    """
    init_db()
    analysis = DayAnalysis(trade_date=trade_date)

    # 1. 获取当日数据
    date_str = trade_date.replace("-", "")
    current_data = fetch_all_core_etf_data(target_date=date_str)

    # 2. 获取前一日份额（从DB中取）
    prev_date = _get_prev_trade_date(trade_date)
    prev_shares = {}
    if prev_date:
        # get_etf_history 内部使用 YYYYMMDD 格式查询，需要转换
        prev_date_db = prev_date.replace("-", "")
        for etf in CORE_ETFS:
            hist = get_etf_history(etf.code, prev_date_db, prev_date_db)
            if not hist.empty:
                prev_shares[etf.code] = hist.iloc[0]["shares"]

    # 3. 计算每只ETF的变化
    for etf in CORE_ETFS:
        data = current_data.get(etf.code, {})
        cur_shares = data.get("shares")
        price = data.get("price") or data.get("nav") or 1.0

        # 保存当日份额到DB
        if cur_shares is not None:
            save_etf_shares(
                code=etf.code,
                trade_date=trade_date.replace("-", ""),
                shares=cur_shares,
                nav=data.get("nav"),
                price=price,
                fund_flow_main=data.get("fund_flow_main")
            )

        # 计算变化
        prev_share = prev_shares.get(etf.code)
        if cur_shares is not None:
            if prev_share is not None and prev_share > 0:
                change = cur_shares - prev_share
                change_pct = (change / prev_share) * 100
                est_flow = estimate_fund_flow(change, price)

                # 信号判断
                signal = "none"
                if change_pct > SIGNAL_THRESHOLDS["entry_share_pct"] and change > SIGNAL_THRESHOLDS["entry_share_abs"]:
                    signal = "entry"
                elif change_pct < -SIGNAL_THRESHOLDS["entry_share_pct"] and abs(change) > SIGNAL_THRESHOLDS["entry_share_abs"]:
                    signal = "exit"
            else:
                # 无前日数据，显示为0变化（首次运行或新ETF）
                change = 0
                change_pct = 0.0
                est_flow = 0.0
                signal = "none"

            ch = ETFChange(
                code=etf.code, name=etf.name,
                shares=cur_shares, shares_change=change,
                shares_change_pct=round(change_pct, 2),
                price=price, est_flow=round(est_flow, 2),
                signal=signal
            )
            analysis.etf_changes.append(ch)

            # 保存日变化到DB
            save_daily_change(
                code=etf.code,
                trade_date=trade_date.replace("-", ""),
                shares_change=round(change, 2),
                shares_change_pct=round(change_pct, 2),
                est_flow=round(est_flow, 2),
                signal=signal
            )

            if signal == "entry":
                analysis.entry_count += 1
            elif signal == "exit":
                analysis.exit_count += 1

    # 4. 综合判断国家队信号
    analysis.total_est_flow = round(sum(c.est_flow for c in analysis.etf_changes), 2)

    _judge_national_team_signal(analysis)

    # 5. 保存信号日志
    if analysis.national_team_signal != "none":
        codes = ",".join([c.code for c in analysis.etf_changes if c.signal != "none"])
        save_signal(
            trade_date=trade_date.replace("-", ""),
            signal_type=analysis.national_team_signal,
            description=analysis.signal_description,
            etf_codes=codes,
            total_flow=analysis.total_est_flow
        )

    return analysis


def _judge_national_team_signal(analysis: DayAnalysis):
    """综合判断国家队操作信号"""
    thresholds = SIGNAL_THRESHOLDS

    # 入场信号：多个ETF同时触发入场
    if analysis.entry_count >= thresholds["entry_min_etfs"]:
        analysis.national_team_signal = "entry"
        analysis.signal_description = (
            f"国家队护盘信号：{analysis.entry_count}个核心宽基ETF同时出现大额净申购，"
            f"合计估算净流入{analysis.total_est_flow}亿元"
        )
    # 持续退出信号
    elif analysis.exit_count >= thresholds["entry_min_etfs"]:
        analysis.national_team_signal = "exit"
        analysis.signal_description = (
            f"国家队减持信号：{analysis.exit_count}个核心宽基ETF同时出现大额净赎回，"
            f"合计估算净流出{abs(analysis.total_est_flow)}亿元"
        )
    # 轮动：有的流入有的流出
    elif analysis.entry_count > 0 and analysis.exit_count > 0:
        total_in = sum(c.est_flow for c in analysis.etf_changes if c.signal == "entry")
        total_out = abs(sum(c.est_flow for c in analysis.etf_changes if c.signal == "exit"))
        if total_in > 0 and total_out > 0:
            ratio = abs(total_in - total_out) / max(total_in, total_out)
            if ratio < thresholds["rotation_tolerance"]:
                analysis.national_team_signal = "rotation"
                entry_names = ",".join([c.name for c in analysis.etf_changes if c.signal == "entry"])
                exit_names = ",".join([c.name for c in analysis.etf_changes if c.signal == "exit"])
                analysis.signal_description = (
                    f"疑似国家队轮动换仓：{exit_names}流出→{entry_names}流入，"
                    f"净差额较小，符合结构调整特征"
                )


def _get_prev_trade_date(trade_date: str) -> Optional[str]:
    """获取前一交易日"""
    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
        # 简单跳过周末
        for i in range(1, 10):
            prev = dt - timedelta(days=i)
            if prev.weekday() < 5:  # Mon-Fri
                return prev.strftime("%Y-%m-%d")
    except:
        pass
    return None


def get_trend_summary(days: int = 30) -> str:
    """获取最近N天的趋势摘要"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    df = get_daily_changes(start, end)
    signals = get_signals(start, end)

    if df.empty:
        return f"最近{days}天暂无数据"

    # 按日汇总
    daily_summary = df.groupby("trade_date").agg(
        total_flow=("est_flow", "sum"),
        etf_count=("code", "nunique"),
        entry_signals=("signal", lambda x: (x == "entry").sum()),
        exit_signals=("signal", lambda x: (x == "exit").sum()),
    ).reset_index()

    # 统计
    total_inflow = daily_summary["total_flow"].sum()
    signal_days = len(signals)

    lines = []
    lines.append(f"近{days}天趋势摘要：")
    lines.append(f"  累计估算资金流: {total_inflow:+.1f}亿元")
    lines.append(f"  国家队信号日: {signal_days}天")

    if not signals.empty:
        for _, row in signals.iterrows():
            dt_str = str(row["trade_date"])
            formatted = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}"
            stype = {"entry": "入场", "exit": "减持", "rotation": "轮动"}.get(row["signal_type"], row["signal_type"])
            lines.append(f"  {formatted} [{stype}] {row['description'][:80]}")

    return "\n".join(lines)
