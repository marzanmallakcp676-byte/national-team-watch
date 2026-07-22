"""可视化 — Matplotlib图表生成"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List
import os
import warnings
warnings.filterwarnings("ignore")

plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

from .config import CORE_ETFS, ETF_MAP
from .db import get_daily_changes, get_etf_history, get_signals
from .fetcher import estimate_fund_flow


OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
os.makedirs(OUTDIR, exist_ok=True)


def plot_daily_flow(days: int = 30, save: bool = True) -> Optional[str]:
    """
    生成ETF每日资金流向图

    Returns:
        保存路径
    """
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    df = get_daily_changes(start, end)
    if df.empty:
        print("无数据可供绘图")
        return None

    df["trade_date"] = pd.to_datetime(df["trade_date"])

    # 按日汇总
    daily = df.groupby("trade_date")["est_flow"].sum().reset_index()
    daily = daily.sort_values("trade_date")

    # 分别统计流入和流出
    daily["inflow"] = daily["est_flow"].clip(lower=0)
    daily["outflow"] = daily["est_flow"].clip(upper=0)

    fig, ax = plt.subplots(figsize=(12, 5))

    colors = ['#c62828' if x >= 0 else '#2e7d32' for x in daily["est_flow"]]
    ax.bar(daily["trade_date"], daily["est_flow"], color=colors, width=0.7, edgecolor='white', alpha=0.85)

    # 零线
    ax.axhline(y=0, color='black', linewidth=0.8, linestyle='-')

    # 标注大额流入/流出日
    for _, row in daily.iterrows():
        if abs(row["est_flow"]) > 50:
            color = '#c62828' if row["est_flow"] > 0 else '#2e7d32'
            direction = '流入' if row["est_flow"] > 0 else '流出'
            ax.annotate(f'{direction}\n{row["est_flow"]:+.0f}亿',
                       xy=(row["trade_date"], row["est_flow"]),
                       xytext=(0, 15 if row["est_flow"] > 0 else -15),
                       textcoords='offset points',
                       ha='center', fontsize=8, color=color, fontweight='bold')

    ax.set_title(f'核心宽基ETF每日估算资金流向（近{days}日）', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel('估算资金净流入（亿元）', fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days//15)))
    ax.grid(True, alpha=0.2, axis='y', linestyle='--')
    plt.xticks(rotation=45)
    plt.tight_layout()

    path = os.path.join(OUTDIR, f"daily_flow_{datetime.now().strftime('%Y%m%d')}.png")
    if save:
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()
        return path
    plt.close()
    return None


def plot_etf_share_trend(codes: Optional[List[str]] = None,
                         days: int = 90, save: bool = True) -> Optional[str]:
    """
    生成ETF份额变化趋势图（多ETF叠加）

    Args:
        codes: ETF代码列表，默认所有核心ETF
        days: 回溯天数
    """
    if codes is None:
        codes = [etf.code for etf in CORE_ETFS if etf.tier == 1]

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    fig, ax = plt.subplots(figsize=(12, 6))

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

    for i, code in enumerate(codes):
        etf = ETF_MAP.get(code)
        hist = get_etf_history(code, start, end)
        if hist.empty or "shares" not in hist.columns:
            continue

        hist["trade_date"] = pd.to_datetime(hist["trade_date"])
        hist = hist.sort_values("trade_date")

        # 归一化到起始日=100
        if not hist.empty and hist.iloc[0]["shares"] > 0:
            norm = hist["shares"] / hist.iloc[0]["shares"] * 100
            label = f'{etf.name}({code})' if etf else code
            ax.plot(hist["trade_date"], norm, color=colors[i % len(colors)],
                   linewidth=1.8, label=label, marker='.', markersize=3)

    ax.set_title(f'核心宽基ETF份额变化趋势（归一化，起始=100，近{days}日）', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel('份额指数（起始=100）', fontsize=11)
    ax.legend(loc='upper left', fontsize=8, ncol=2)
    ax.grid(True, alpha=0.2, linestyle='--')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    plt.xticks(rotation=45)
    plt.tight_layout()

    path = os.path.join(OUTDIR, f"share_trend_{datetime.now().strftime('%Y%m%d')}.png")
    if save:
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()
        return path
    plt.close()
    return None


def plot_signals_timeline(days: int = 90, save: bool = True) -> Optional[str]:
    """生成国家队信号时间线图"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    signals = get_signals(start, end)
    flow = get_daily_changes(start, end)

    if flow.empty:
        return None

    flow["trade_date"] = pd.to_datetime(flow["trade_date"])
    daily_flow = flow.groupby("trade_date")["est_flow"].sum().reset_index()

    fig, ax = plt.subplots(figsize=(12, 5))

    # 资金流向背景
    colors = ['#ffcdd2' if x >= 0 else '#c8e6c9' for x in daily_flow["est_flow"]]
    ax.bar(daily_flow["trade_date"], daily_flow["est_flow"], color=colors, width=0.8, alpha=0.6)
    ax.axhline(y=0, color='gray', linewidth=0.5)

    # 标记信号点
    if not signals.empty:
        signal_dates = []
        signal_types = []
        for _, row in signals.iterrows():
            dt = pd.to_datetime(str(row["trade_date"]))
            stype = row["signal_type"]
            signal_dates.append(dt)
            signal_types.append(stype)
            marker = {'entry': '^', 'exit': 'v', 'rotation': 'o'}.get(stype, 'o')
            color = {'entry': 'red', 'exit': 'green', 'rotation': 'orange'}.get(stype, 'gray')
            label = {'entry': '国家队入场', 'exit': '国家队减持', 'rotation': '轮动'}.get(stype, '')
            ax.scatter(dt, daily_flow[daily_flow["trade_date"] == dt]["est_flow"].values[0]
                      if dt in daily_flow["trade_date"].values else 0,
                      marker=marker, s=150, c=color, edgecolors='white', linewidth=1.5,
                      zorder=5, label=label)

    # 去重图例
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc='upper left', fontsize=9)

    ax.set_title(f'国家队操作信号时间线（近{days}日）', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel('估算资金净流入（亿元）', fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.grid(True, alpha=0.2, axis='y', linestyle='--')
    plt.xticks(rotation=45)
    plt.tight_layout()

    path = os.path.join(OUTDIR, f"signals_{datetime.now().strftime('%Y%m%d')}.png")
    if save:
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()
        return path
    plt.close()
    return None


def generate_all_charts(days: int = 30) -> dict:
    """生成所有图表，返回路径字典"""
    paths = {}
    path = plot_daily_flow(days=days, save=True)
    if path:
        paths["daily_flow"] = path

    path = plot_etf_share_trend(days=days, save=True)
    if path:
        paths["share_trend"] = path

    path = plot_signals_timeline(days=days*3, save=True)
    if path:
        paths["signals"] = path

    return paths
