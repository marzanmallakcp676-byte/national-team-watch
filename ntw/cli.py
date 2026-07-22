"""CLI入口 — Click命令框架"""

import click
from datetime import datetime, timedelta
import os
import sys

# 确保项目路径在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ntw.config import CORE_ETFS, ETF_MAP, NATIONAL_TEAM
from ntw.db import init_db, get_signals, get_daily_changes, get_latest_trade_date
from ntw.fetcher import fetch_all_core_etf_data
from ntw.analyzer import analyze_daily_data, get_trend_summary
from ntw.reporter import terminal_report, generate_markdown_report
from ntw.visualizer import generate_all_charts


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """国家队ETF资金流哨兵 — 监测国家队在A股的ETF申赎动向"""
    init_db()


@cli.command()
@click.option("--date", default=None, help="交易日 (YYYY-MM-DD), 默认今天")
def today(date):
    """查看今日ETF申赎概况和国家队信号"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    terminal_report(trade_date=date)


@cli.command()
@click.option("--from", "from_date", default=None, help="起始日期 (YYYY-MM-DD)")
@click.option("--to", "to_date", default=None, help="截止日期 (YYYY-MM-DD)")
@click.option("--days", default=30, help="最近N天 (默认30)")
def flow(from_date, to_date, days):
    """查看国家队资金流向趋势"""
    if from_date and to_date:
        start = from_date.replace("-", "")
        end = to_date.replace("-", "")
    else:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    df = get_daily_changes(start, end)

    if df.empty:
        click.echo(f"暂无数据 ({start} ~ {end})")
        return

    # 按日汇总
    df["trade_date_str"] = df["trade_date"]
    daily = df.groupby("trade_date_str").agg(
        total_flow=("est_flow", "sum"),
        etf_count=("code", "nunique"),
    ).reset_index().sort_values("trade_date_str")

    for _, row in daily.iterrows():
        dt = str(row["trade_date_str"])
        formatted = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        flow_val = row["total_flow"]
        bar = "█" * min(int(abs(flow_val) / 5), 40)
        bar = bar if flow_val >= 0 else click.style(bar, fg="green")
        color = "red" if flow_val > 10 else "green" if flow_val < -10 else "white"
        click.echo(f"  {formatted}  {click.style(f'{flow_val:+7.1f}亿', fg=color)}  {bar}")


@cli.command()
@click.option("--days", default=30, help="最近N天 (默认30)")
def signals(days):
    """查看国家队操作信号历史"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    sig_df = get_signals(start, end)

    if sig_df.empty:
        click.echo(f"近{days}天无国家队信号记录")
        return

    click.secho(f"\n近{days}天国家队操作信号:\n", bold=True)

    label_map = {"entry": "入场/护盘", "exit": "减持/退出", "rotation": "轮动换仓"}
    for _, row in sig_df.iterrows():
        dt = str(row["trade_date"])
        formatted = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        stype = label_map.get(row["signal_type"], row["signal_type"])
        flow_str = f"{row['total_flow']:+.1f}亿" if row["total_flow"] else "—"

        if row["signal_type"] == "entry":
            icon = click.style("▲", fg="red", bold=True)
        elif row["signal_type"] == "exit":
            icon = click.style("▼", fg="green", bold=True)
        else:
            icon = click.style("◆", fg="yellow")

        click.echo(f"  {icon} {formatted} [{stype}] {flow_str}")
        if row.get("description"):
            click.echo(f"    {row['description'][:100]}")


@cli.command()
@click.option("--date", default=None, help="交易日 (YYYY-MM-DD)")
@click.option("--output", "-o", default=None, help="输出路径")
def report(date, output):
    """生成国家队ETF资金流日报 (Markdown)"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # 生成图表
    chart_paths = generate_all_charts(days=30)
    if chart_paths:
        click.echo(f"已生成 {len(chart_paths)} 张图表")

    # 生成报告
    if output is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
        os.makedirs(output_dir, exist_ok=True)
        output = os.path.join(output_dir, f"report_{date.replace('-', '')}.md")

    report_text = generate_markdown_report(trade_date=date, output_path=output)
    click.echo(f"报告已保存: {output}")


@cli.command()
@click.option("--port", default=8501, help="端口号 (默认8501)")
def dashboard(port):
    """启动Web仪表盘 (Streamlit)"""
    dashboard_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.py")

    if not os.path.exists(dashboard_path):
        click.echo("仪表盘文件不存在，请先创建 dashboard.py")
        return

    click.echo(f"启动仪表盘: http://localhost:{port}")
    os.system(f"streamlit run {dashboard_path} --server.port {port}")


@cli.command()
@click.option("--from", "from_date", default=None, help="起始日期 (YYYYMMDD)")
def backfill(from_date):
    """回溯填充历史数据"""
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    click.echo(f"开始回溯填充数据（从 {from_date} 起）...")
    click.echo("提示: 此操作需要逐个交易日获取数据，请耐心等待")

    # 简化版：填充最近90天
    days = 90
    for i in range(days, -1, -1):
        dt = (datetime.now() - timedelta(days=i))
        if dt.weekday() < 5:  # 工作日
            date_str = dt.strftime("%Y-%m-%d")
            try:
                analysis = analyze_daily_data(date_str)
                if analysis.etf_changes:
                    click.echo(f"  {date_str} ✓ ({len(analysis.etf_changes)} ETFs, "
                               f"flow: {analysis.total_est_flow:+.1f}亿)")
            except Exception as e:
                click.echo(f"  {date_str} ✗ {e}")

    click.echo("回溯填充完成")


@cli.command()
def list():
    """列出监测的ETF清单"""
    click.secho("\n国家队重点监测ETF:\n", bold=True)
    for etf in CORE_ETFS:
        tier_icon = "★" if etf.tier == 1 else "☆"
        click.echo(f"  {tier_icon} {etf.code}  {etf.full_name}  ({etf.index_name}, {etf.exchange})")


if __name__ == "__main__":
    cli()
