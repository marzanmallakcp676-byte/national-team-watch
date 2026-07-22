"""报告生成 — Markdown日报 + 终端Rich输出"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from .config import CORE_ETFS, ETF_MAP, SIGNAL_THRESHOLDS
from .analyzer import analyze_daily_data, DayAnalysis, ETFChange
from .db import get_daily_changes, get_signals, get_all_latest_shares


def terminal_report(trade_date: Optional[str] = None):
    """终端Rich格式报告"""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    console = Console()

    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    # 标题
    title = Text(f"国家队ETF资金流监测 — {trade_date}", style="bold cyan")
    console.print(Panel(title, box=box.HEAVY))

    # 分析数据
    try:
        analysis = analyze_daily_data(trade_date)
    except Exception as e:
        console.print(f"[red]数据获取失败: {e}[/red]")
        console.print("[yellow]提示: 如果今天是周末或非交易日，请指定最近的交易日[/yellow]")
        return

    # 信号Panel
    signal_color = {"entry": "red bold", "exit": "green bold", "rotation": "yellow bold", "none": "dim"}
    signal_label = {"entry": "国家队入场/护盘", "exit": "国家队减持/退出",
                    "rotation": "疑似轮动换仓", "none": "无明显信号"}

    sig_text = Text()
    sig_text.append("信号: ", style="bold")
    sig_text.append(signal_label.get(analysis.national_team_signal, "—"),
                    style=signal_color.get(analysis.national_team_signal, "dim"))
    sig_text.append(f"\n总估算资金流: {analysis.total_est_flow:+.1f}亿元")
    if analysis.signal_description:
        sig_text.append(f"\n{analysis.signal_description}")

    console.print(Panel(sig_text, title="综合判断", border_style="yellow"))

    # ETF明细表
    if analysis.etf_changes:
        table = Table(title="核心宽基ETF份额变化", box=box.ROUNDED)
        table.add_column("ETF", style="cyan")
        table.add_column("份额(万份)", justify="right")
        table.add_column("变化量(万份)", justify="right")
        table.add_column("变化率", justify="right")
        table.add_column("估算资金流(亿)", justify="right")
        table.add_column("信号", justify="center")

        for ch in sorted(analysis.etf_changes, key=lambda x: abs(x.est_flow), reverse=True):
            flow_val = ch.est_flow
            if flow_val > 0:
                flow_str = f"[red]{flow_val:+.1f}[/red]"
            elif flow_val < 0:
                flow_str = f"[green]{flow_val:+.1f}[/green]"
            else:
                flow_str = "—"

            sig_icon = {"entry": "🔴入场", "exit": "🟢退出"}.get(ch.signal, "—")

            table.add_row(
                f"{ch.name}({ch.code})",
                f"{ch.shares:,.0f}",
                f"{ch.shares_change:+,.0f}",
                f"{ch.shares_change_pct:+.2f}%",
                flow_str,
                sig_icon,
            )

        console.print(table)

    console.print(f"\n[dim]数据来源: AKShare (东方财富/上交所)[/dim]")


def generate_markdown_report(trade_date: Optional[str] = None,
                             output_path: Optional[str] = None) -> str:
    """生成Markdown日报"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        analysis = analyze_daily_data(trade_date)
    except Exception as e:
        return f"# 国家队ETF资金流日报\n\n生成失败: {e}"

    lines = []
    lines.append(f"# 国家队ETF资金流日报")
    lines.append(f"")
    lines.append(f"**日期**: {trade_date}  ")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"")

    # 信号
    signal_map = {"entry": "国家队入场/护盘", "exit": "国家队减持/退出",
                  "rotation": "疑似轮动换仓", "none": "无明显信号"}
    lines.append(f"## 综合信号")
    lines.append(f"")
    lines.append(f"> **{signal_map.get(analysis.national_team_signal, '—')}**")
    lines.append(f"")
    lines.append(f"- 总估算资金流: **{analysis.total_est_flow:+.1f}亿元**")
    lines.append(f"- 触发入场信号的ETF: {analysis.entry_count}个")
    lines.append(f"- 触发退出信号的ETF: {analysis.exit_count}个")
    if analysis.signal_description:
        lines.append(f"- {analysis.signal_description}")
    lines.append(f"")

    # ETF明细
    if analysis.etf_changes:
        lines.append(f"## 核心宽基ETF份额变化")
        lines.append(f"")
        lines.append(f"| ETF | 份额(万份) | 变化量(万份) | 变化率 | 估算资金流(亿) | 信号 |")
        lines.append(f"|-----|-----------|-------------|--------|---------------|------|")

        for ch in sorted(analysis.etf_changes, key=lambda x: abs(x.est_flow), reverse=True):
            sig_icon = "🔴入场" if ch.signal == "entry" else "🟢退出" if ch.signal == "exit" else "—"
            lines.append(
                f"| {ch.name}({ch.code}) | {ch.shares:,.0f} | {ch.shares_change:+,.0f} | "
                f"{ch.shares_change_pct:+.2f}% | {ch.est_flow:+.1f} | {sig_icon} |"
            )
        lines.append(f"")

    # 近期信号回顾
    end_dt = trade_date.replace("-", "")
    start_dt = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y%m%d")
    signals_df = get_signals(start_dt, end_dt)
    if not signals_df.empty:
        lines.append(f"## 近30日国家队信号回顾")
        lines.append(f"")
        for _, row in signals_df.iterrows():
            dt = str(row["trade_date"])
            formatted = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
            stype = {"entry": "入场", "exit": "减持", "rotation": "轮动"}.get(row["signal_type"], "—")
            lines.append(f"- **{formatted}** [{stype}] {row['description']}")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"*数据来源: AKShare (东方财富/上交所/深交所) | 国家队ETF资金流哨兵*")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存到: {output_path}")

    return report
