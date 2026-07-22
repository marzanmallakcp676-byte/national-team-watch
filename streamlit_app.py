"""国家队ETF资金流哨兵 — Streamlit Web Dashboard"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys, os

# ── Page config ──
st.set_page_config(
    page_title="国家队ETF资金流哨兵",
    page_icon="🇨🇳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Path setup ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ntw.config import CORE_ETFS, ETF_MAP, NATIONAL_TEAM, SIGNAL_THRESHOLDS
from ntw.db import init_db, get_daily_changes, get_signals, get_etf_history, get_latest_trade_date
from ntw.fetcher import fetch_all_core_etf_data, fetch_etf_spot_all
from ntw.analyzer import analyze_daily_data

init_db()

# ── Cached data fetchers ──
@st.cache_data(ttl=7200)  # cache 2 hours
def get_flow_data(days=60):
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    df = get_daily_changes(start, end)
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df

@st.cache_data(ttl=7200)
def get_signal_data(days=60):
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    return get_signals(start, end)

@st.cache_data(ttl=3600)
def get_latest_analysis():
    """获取最新交易日的分析"""
    latest = get_latest_trade_date()
    if latest:
        date_str = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        return analyze_daily_data(date_str)
    except:
        return None

# ── Styles ──
st.markdown("""
<style>
.signal-entry { background: #c62828; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-exit { background: #2e7d32; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-rotation { background: #f57f17; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-none { background: #455a64; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.metric-card { background: #f5f5f5; padding: 16px; border-radius: 8px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════ SIDEBAR ═══════════════════════
with st.sidebar:
    st.image("https://img.icons8.com/color/96/china.png", width=48)
    st.title("国家队ETF哨兵")
    st.caption("监测国家队在A股核心宽基ETF中的资金动向")

    st.divider()
    days = st.slider("回溯天数", 7, 180, 60, 7)

    st.divider()
    st.caption(f"数据来源: AKShare (东方财富/上交所)")
    st.caption(f"更新间隔: 每2小时")

# ═══════════════════════ PAGE 1: OVERVIEW ═══════════════════════
tab1, tab2, tab3 = st.tabs(["📊 总览仪表盘", "🔍 ETF明细", "ℹ️ 关于"])

with tab1:
    st.title("国家队ETF资金流监测")

    # ── Top: Signal + Metrics Row ──
    analysis = get_latest_analysis()

    col_sig, col_flow, col_entry, col_exit = st.columns([2, 1, 1, 1])

    with col_sig:
        if analysis is None or analysis.national_team_signal == "none":
            st.markdown('<div class="signal-none"><h3>🟡 无明显信号</h3><p>暂未检测到国家队大规模操作</p></div>', unsafe_allow_html=True)
        elif analysis.national_team_signal == "entry":
            desc = analysis.signal_description[:80] if analysis.signal_description else "多个核心宽基ETF同步大额净申购"
            st.markdown(f'<div class="signal-entry"><h3>🔴 国家队护盘</h3><p>{desc}</p></div>', unsafe_allow_html=True)
        elif analysis.national_team_signal == "exit":
            desc = analysis.signal_description[:80] if analysis.signal_description else "多个核心宽基ETF同步大额净赎回"
            st.markdown(f'<div class="signal-exit"><h3>🟢 国家队减持</h3><p>{desc}</p></div>', unsafe_allow_html=True)
        elif analysis.national_team_signal == "rotation":
            desc = analysis.signal_description[:80] if analysis.signal_description else "部分ETF流入部分流出，净额相近"
            st.markdown(f'<div class="signal-rotation"><h3>🟡 疑似轮动换仓</h3><p>{desc}</p></div>', unsafe_allow_html=True)

    latest_date = get_latest_trade_date() or datetime.now().strftime("%Y%m%d")
    formatted_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}"

    with col_flow:
        total_flow = analysis.total_est_flow if analysis else 0
        st.metric("合计资金流", f"{total_flow:+.1f}亿", delta=None)

    with col_entry:
        entry_count = analysis.entry_count if analysis else 0
        st.metric("入场ETF数", entry_count)

    with col_exit:
        exit_count = analysis.exit_count if analysis else 0
        st.metric("退出ETF数", exit_count)

    st.caption(f"数据日期: {formatted_date} | 上交所ETF份额数据通常T+1更新")

    st.divider()

    # ── ETF Summary Table ──
    if analysis and analysis.etf_changes:
        st.subheader("核心宽基ETF份额变化明细")

        rows = []
        for ch in sorted(analysis.etf_changes, key=lambda x: abs(x.est_flow), reverse=True):
            if ch.signal == "entry":
                sig = "🔴入场"
            elif ch.signal == "exit":
                sig = "🟢退出"
            else:
                sig = "—"
            rows.append({
                "ETF": f"{ch.name} ({ch.code})",
                "份额(万份)": f"{ch.shares:,.0f}",
                "变化(万份)": f"{ch.shares_change:+,.0f}",
                "变化率": f"{ch.shares_change_pct:+.2f}%",
                "估算资金流(亿)": ch.est_flow,
                "信号": sig,
            })

        df_summary = pd.DataFrame(rows)

        def color_flow(val):
            if isinstance(val, (int, float)):
                color = 'color: #c62828' if val > 0 else 'color: #2e7d32' if val < 0 else ''
                return color
            return ''

        st.dataframe(
            df_summary.style.map(color_flow, subset=['估算资金流(亿)']),
            use_container_width=True,
            hide_index=True,
            height=300,
        )

    st.divider()

    # ── Flow Trend Chart ──
    st.subheader("资金流向趋势")

    flow_df = get_flow_data(days=days)
    if not flow_df.empty:
        daily = flow_df.groupby("trade_date")["est_flow"].sum().reset_index()
        daily = daily.sort_values("trade_date")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.7, 0.3], vertical_spacing=0.05)

        # Bar chart
        colors = ['#c62828' if x >= 0 else '#2e7d32' for x in daily["est_flow"]]
        fig.add_trace(
            go.Bar(x=daily["trade_date"], y=daily["est_flow"], marker_color=colors,
                   name="日资金流", hovertemplate='%{x|%m-%d}: %{y:+.1f}亿元<extra></extra>'),
            row=1, col=1
        )

        # Cumulative line
        daily["cumulative"] = daily["est_flow"].cumsum()
        fig.add_trace(
            go.Scatter(x=daily["trade_date"], y=daily["cumulative"], mode='lines+markers',
                       line=dict(color='#1565c0', width=2), marker=dict(size=5),
                       name="累计资金流", yaxis="y2",
                       hovertemplate='%{x|%m-%d}: 累计 %{y:+.1f}亿元<extra></extra>'),
            row=2, col=1
        )

        fig.update_yaxes(title_text="日净流入(亿元)", row=1, col=1)
        fig.update_yaxes(title_text="累计(亿元)", row=2, col=1)
        fig.update_layout(
            height=500, hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=20, b=0),
        )

        # Mark signal points
        sig_df = get_signal_data(days=days)
        if not sig_df.empty:
            for _, row in sig_df.iterrows():
                dt = pd.to_datetime(str(row["trade_date"]))
                marker_sym = {'entry': 'triangle-up', 'exit': 'triangle-down', 'rotation': 'diamond'}
                marker_color = {'entry': '#c62828', 'exit': '#2e7d32', 'rotation': '#f57f17'}
                fig.add_trace(
                    go.Scatter(x=[dt], y=[daily[daily["trade_date"] == dt]["est_flow"].values[0]
                               if dt in daily["trade_date"].values else 0],
                               mode='markers', marker=dict(
                                   symbol=marker_sym.get(row["signal_type"], 'circle'),
                                   size=14, color=marker_color.get(row["signal_type"], 'gray'),
                                   line=dict(width=1, color='white')),
                               showlegend=False,
                               hovertemplate=f'%{{x|%m-%d}}: {row["signal_type"]}<extra></extra>'),
                    row=1, col=1
                )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("暂无足够的资金流数据。请先运行 `python3 -m ntw.cli backfill` 补充历史数据。")

    st.divider()

    # ── Signal History ──
    st.subheader("国家队操作信号历史")
    sig_df = get_signal_data(days=days)
    if not sig_df.empty:
        records = []
        for _, row in sig_df.iterrows():
            dt = str(row["trade_date"])
            formatted = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
            stype = {"entry": "🔴 入场/护盘", "exit": "🟢 减持/退出", "rotation": "🟡 轮动换仓"}.get(row["signal_type"], row["signal_type"])
            records.append({
                "日期": formatted,
                "信号类型": stype,
                "涉及ETF": row.get("etf_codes", "—"),
                "资金流(亿)": f"{row['total_flow']:+.1f}" if row.get("total_flow") else "—",
                "说明": row.get("description", "")[:120],
            })
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    else:
        st.info("暂无国家队信号记录")

# ═══════════════════════ PAGE 2: ETF DETAIL ═══════════════════════
with tab2:
    st.title("ETF份额变化明细")

    # ETF selector
    etf_options = {f"{e.name} ({e.code}) - {e.index_name}": e.code for e in CORE_ETFS}
    selected = st.selectbox("选择ETF", list(etf_options.keys()))

    code = etf_options[selected]
    etf = ETF_MAP[code]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("交易所", etf.exchange)
    col2.metric("跟踪指数", etf.index_name)
    col3.metric("优先级", "核心" if etf.tier == 1 else "辅助")

    st.divider()

    # Fetch detail
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    hist = get_etf_history(code, start, end)
    flow_detail = get_flow_data(days=days)

    if not hist.empty and "shares" in hist.columns:
        hist["trade_date"] = pd.to_datetime(hist["trade_date"])
        hist = hist.sort_values("trade_date")

        # Shares trend chart
        fig_shares = go.Figure()
        fig_shares.add_trace(go.Scatter(
            x=hist["trade_date"], y=hist["shares"],
            mode='lines+markers',
            line=dict(color='#1f77b4', width=2.5),
            marker=dict(size=5),
            name="份额(万份)",
            hovertemplate='%{x|%Y-%m-%d}: %{y:,.0f}万份<extra></extra>'
        ))

        fig_shares.update_layout(
            title=f"{etf.name} ({code}) — 份额变化趋势",
            height=400,
            hovermode="x unified",
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig_shares, use_container_width=True)

        # Daily change chart
        if not flow_detail.empty:
            etf_flow = flow_detail[flow_detail["code"] == code].copy()
            if not etf_flow.empty:
                etf_flow = etf_flow.sort_values("trade_date")

                fig_change = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                           row_heights=[0.6, 0.4], vertical_spacing=0.05)

                colors = ['#c62828' if x >= 0 else '#2e7d32' for x in etf_flow["shares_change"]]
                fig_change.add_trace(
                    go.Bar(x=etf_flow["trade_date"], y=etf_flow["shares_change"],
                           marker_color=colors, name="份额变化(万份)",
                           hovertemplate='%{x|%m-%d}: %{y:+,.0f}万份<extra></extra>'),
                    row=1, col=1
                )

                fig_change.add_trace(
                    go.Bar(x=etf_flow["trade_date"], y=etf_flow["est_flow"],
                           marker_color=colors, name="估算资金流(亿)",
                           hovertemplate='%{x|%m-%d}: %{y:+.1f}亿元<extra></extra>'),
                    row=2, col=1
                )

                fig_change.update_yaxes(title_text="份额变化(万份)", row=1, col=1)
                fig_change.update_yaxes(title_text="资金流(亿)", row=2, col=1)
                fig_change.update_layout(
                    height=450, hovermode="x unified",
                    margin=dict(l=0, r=0, t=20, b=0),
                )

                st.subheader("每日变化")
                st.plotly_chart(fig_change, use_container_width=True)

                # Summary stats
                c1, c2, c3 = st.columns(3)
                with c1:
                    total_in = etf_flow[etf_flow["shares_change"] > 0]["shares_change"].sum()
                    st.metric(f"近{days}天总流入", f"{total_in:+,.0f}万份")
                with c2:
                    total_out = etf_flow[etf_flow["shares_change"] < 0]["shares_change"].sum()
                    st.metric(f"近{days}天总流出", f"{total_out:+,.0f}万份")
                with c3:
                    net = etf_flow["shares_change"].sum()
                    st.metric(f"近{days}天净变化", f"{net:+,.0f}万份",
                             delta=f"{total_in + total_out:+,.0f}" if (total_in + total_out) != 0 else None)

    else:
        st.warning(f"暂无 {etf.name}({code}) 的历史数据。请先运行 backfill。")

# ═══════════════════════ PAGE 3: ABOUT ═══════════════════════
with tab3:
    st.title("关于国家队ETF资金流哨兵")

    st.markdown("""
    ### 这是什么？

    本工具通过监测A股核心宽基ETF的**份额变化**，反推**国家队**（中央汇金、中国国新、中国诚通）
    在A股市场的资金流向。

    ### 为什么做这个？

    国家队在A股的操作呈现清晰的 **"涨卖跌买"逆周期规律**：
    - 市场急跌时 → 大额申购宽基ETF托底
    - 市场过热时 → 减持降温引导慢牛

    2025年4月关税战中，国家队单周净买入1,698亿元ETF；2026年1月市场逼近4,200点时，
    国家队在12天内赎回了约9,230亿元宽基ETF。这些操作的**痕迹**全部留在了ETF份额数据里。

    ### 监测哪些ETF？

    覆盖8只核心宽基ETF，以沪深300、上证50、中证500、中证1000、科创50为主。

    ### 信号怎么判断？

    当 ≥3个核心宽基ETF在同一天出现**大额净申购**（份额增幅>5% + 绝对增量>10亿份），
    自动标记为国家队"入场/护盘"信号。系统还能区分"真减仓"与"轮动换仓"。

    ### 数据来源

    - 上交所ETF份额数据（日频，T+1更新）
    - 全市场ETF行情（日频）
    - 数据接口：**AKShare**（免费开源金融数据库，底层抓取东方财富/上交所）

    ### 局限性

    - 仅能准确追踪**上交所**ETF（深交所无公开的按日历史份额接口）
    - ETF份额变化包含了散户和机构的申赎噪音，非国家队精确持仓
    - 资金流估算采用 `日份额变化 × 当日收盘价`，未考虑加权均价
    - 仅供参考，不构成投资建议

    ### 技术栈

    Python + AKShare + Streamlit + Plotly + SQLite
    """)

    st.divider()
    st.caption("© 2026 国家队ETF资金流哨兵 | 数据延迟: T+1 | 不构成投资建议")
