"""国家队ETF资金流哨兵 — Streamlit Web Dashboard (Cloud版)"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys, os, json

# ── Page config ──
st.set_page_config(
    page_title="国家队ETF资金流哨兵",
    page_icon="🇨🇳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Path setup ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ntw.config import CORE_ETFS, ETF_MAP, SIGNAL_THRESHOLDS
from ntw.fetcher import fetch_all_core_etf_data, fetch_sse_etf_shares, estimate_fund_flow

# ── 北京时间 ──
from zoneinfo import ZoneInfo
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

def beijing_now():
    return datetime.now(BEIJING_TZ)

def beijing_today_str():
    return beijing_now().strftime("%Y%m%d")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORY_CSV = os.path.join(DATA_DIR, "history.csv")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Live data fetcher (AKShare, no DB) ──
@st.cache_data(ttl=3600)
def get_live_snapshot(date_str=None):
    """从 AKShare 实时获取ETF份额快照（北京时间）"""
    if date_str is None:
        date_str = beijing_today_str()
    data = fetch_all_core_etf_data(target_date=date_str)
    # 如果今天数据还没出（T+1延迟），尝试昨天
    if not any(d.get("shares") for d in data.values()):
        yesterday = (beijing_now() - timedelta(days=1)).strftime("%Y%m%d")
        data = fetch_all_core_etf_data(target_date=yesterday)
    return data

@st.cache_data(ttl=3600)
def get_previous_snapshot():
    """获取前一交易日数据，用于计算变化"""
    # 先获取当前已有数据的最新日期
    live = fetch_all_core_etf_data(target_date=beijing_today_str())
    has_data = any(d.get("shares") for d in live.values())

    if has_data:
        # 今天有数据，前一日就是昨天
        ref = beijing_now() - timedelta(days=1)
    else:
        # 今天没数据，当前展示的是昨天，前一日就是前天
        ref = beijing_now() - timedelta(days=2)

    date_str = ref.strftime("%Y%m%d")
    sse_df = fetch_sse_etf_shares(date_str)
    prev = {}
    if sse_df is not None and not sse_df.empty:
        for etf in CORE_ETFS:
            if etf.exchange == "SSE":
                match = sse_df[sse_df["基金代码"].astype(str) == etf.code]
                if not match.empty:
                    prev[etf.code] = float(match.iloc[0]["基金份额"]) / 10000
    return prev

@st.cache_data(ttl=86400)
def load_history_csv():
    """从CSV加载历史数据"""
    if os.path.exists(HISTORY_CSV):
        df = pd.read_csv(HISTORY_CSV, dtype={"code": str})
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
        return df
    return pd.DataFrame()

# ── Compute analysis from live + history ──
def compute_latest_analysis():
    """综合实时数据和历史CSV，计算最新分析"""
    live = get_live_snapshot()
    prev = get_previous_snapshot()
    history = load_history_csv()

    # 组装ETF变化
    changes = []
    total_flow = 0.0
    entry_count = 0
    exit_count = 0

    for etf in CORE_ETFS:
        code = etf.code
        data = live.get(code, {})
        cur_shares = data.get("shares")
        price = data.get("price") or data.get("nav") or 1.0

        if cur_shares is None:
            continue

        # 优先使用前一日快照，其次用历史CSV
        prev_share = prev.get(code)
        if prev_share is None and not history.empty and code in history.columns:
            hist_for_code = history[history["code"] == code]
            if not hist_for_code.empty:
                latest_hist = hist_for_code.sort_values("trade_date").iloc[-1]
                prev_share = latest_hist.get("shares")

        if prev_share is not None and prev_share > 0:
            change = cur_shares - prev_share
            change_pct = (change / prev_share) * 100
            est_flow = estimate_fund_flow(change, price)
        else:
            change = 0
            change_pct = 0.0
            est_flow = 0.0

        # 信号判断
        signal = "none"
        if change_pct > SIGNAL_THRESHOLDS["entry_share_pct"] and change > SIGNAL_THRESHOLDS["entry_share_abs"]:
            signal = "entry"
        elif change_pct < -SIGNAL_THRESHOLDS["entry_share_pct"] and abs(change) > SIGNAL_THRESHOLDS["entry_share_abs"]:
            signal = "exit"

        changes.append({
            "code": code, "name": etf.name, "shares": cur_shares,
            "shares_change": change, "shares_change_pct": round(change_pct, 2),
            "price": price, "est_flow": round(est_flow, 2), "signal": signal,
        })
        total_flow += est_flow
        if signal == "entry":
            entry_count += 1
        elif signal == "exit":
            exit_count += 1

    # 综合判断
    nt_signal = "none"
    signal_desc = ""
    if entry_count >= SIGNAL_THRESHOLDS["entry_min_etfs"]:
        nt_signal = "entry"
        signal_desc = f"国家队护盘信号：{entry_count}个核心宽基ETF同时出现大额净申购，合计估算净流入{total_flow:.1f}亿元"
    elif exit_count >= SIGNAL_THRESHOLDS["entry_min_etfs"]:
        nt_signal = "exit"
        signal_desc = f"国家队减持信号：{exit_count}个核心宽基ETF同时出现大额净赎回，合计估算净流出{abs(total_flow):.1f}亿元"
    elif entry_count > 0 and exit_count > 0:
        total_in = sum(c["est_flow"] for c in changes if c["signal"] == "entry")
        total_out = abs(sum(c["est_flow"] for c in changes if c["signal"] == "exit"))
        if total_in > 0 and total_out > 0:
            ratio = abs(total_in - total_out) / max(total_in, total_out)
            if ratio < SIGNAL_THRESHOLDS["rotation_tolerance"]:
                nt_signal = "rotation"
                signal_desc = f"疑似国家队轮动换仓：净差额较小，符合结构调整特征"

    # 确定数据日期：优先用历史CSV最新日期
    data_date = datetime.now().strftime("%Y-%m-%d")
    if not history.empty:
        data_date = history["trade_date"].max().strftime("%Y-%m-%d")

    return {
        "trade_date": data_date,
        "etf_changes": sorted(changes, key=lambda x: abs(x["est_flow"]), reverse=True),
        "total_est_flow": round(total_flow, 2),
        "entry_count": entry_count,
        "exit_count": exit_count,
        "national_team_signal": nt_signal,
        "signal_description": signal_desc,
    }

# ── Styles ──
st.markdown("""
<style>
.signal-entry { background: #c62828; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-exit { background: #2e7d32; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-rotation { background: #f57f17; color: white; padding: 20px; border-radius: 12px; text-align: center; }
.signal-none { background: #455a64; color: white; padding: 20px; border-radius: 12px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════ SIDEBAR ═══════════════════════
with st.sidebar:
    st.title("🇨🇳 国家队ETF哨兵")
    st.caption("监测国家队在A股核心宽基ETF中的资金动向")

    st.divider()
    days = st.slider("历史回溯天数", 7, 180, 60, 7)

    st.divider()
    data_date = get_live_snapshot()
    has_live = any(d.get("shares") for d in data_date.values())
    if has_live:
        st.success("✅ 实时数据连接正常")
    else:
        st.error("❌ 数据获取失败（非交易日或接口异常）")

    st.caption(f"北京时间: {beijing_now().strftime('%Y-%m-%d %H:%M')}")
    st.caption("数据来源: AKShare (东方财富/上交所)")
    st.caption("缓存1小时 | 数据T+1更新")
    st.caption("⚠️ 仅供参考，不构成投资建议")

# ═══════════════════════ PAGE 1: OVERVIEW ═══════════════════════
tab1, tab2, tab3 = st.tabs(["📊 总览仪表盘", "🔍 ETF明细", "ℹ️ 关于"])

with tab1:
    st.title("国家队ETF资金流监测")

    analysis = compute_latest_analysis()

    col_sig, col_flow, col_entry, col_exit = st.columns([2, 1, 1, 1])

    with col_sig:
        data_date = analysis.get("trade_date", "")
        if analysis["national_team_signal"] == "none":
            st.markdown(f'<div class="signal-none"><h3>🟡 无明显信号</h3><p>数据日期: {data_date}</p><p>暂未检测到国家队大规模操作</p></div>', unsafe_allow_html=True)
        elif analysis["national_team_signal"] == "entry":
            st.markdown(f'<div class="signal-entry"><h3>🔴 国家队护盘</h3><p style="font-size:14px">数据日期: {data_date}</p><p>{analysis["signal_description"][:100]}</p></div>', unsafe_allow_html=True)
        elif analysis["national_team_signal"] == "exit":
            st.markdown(f'<div class="signal-exit"><h3>🟢 国家队减持</h3><p style="font-size:14px">数据日期: {data_date}</p><p>{analysis["signal_description"][:100]}</p></div>', unsafe_allow_html=True)
        elif analysis["national_team_signal"] == "rotation":
            st.markdown(f'<div class="signal-rotation"><h3>🟡 疑似轮动换仓</h3><p style="font-size:14px">数据日期: {data_date}</p><p>{analysis["signal_description"][:100]}</p></div>', unsafe_allow_html=True)

    with col_flow:
        st.metric("合计资金流", f'{analysis["total_est_flow"]:+.1f}亿')
    with col_entry:
        st.metric("入场ETF数", analysis["entry_count"])
    with col_exit:
        st.metric("退出ETF数", analysis["exit_count"])

    st.caption(f"数据日期: {analysis.get('trade_date', '')} | 上交所ETF份额数据T+1更新 | 数据来源: AKShare")

    st.divider()

    # ── ETF Summary Table ──
    changes = analysis.get("etf_changes", [])
    if changes:
        st.subheader("核心宽基ETF份额变化明细")

        data_date = analysis.get("trade_date", "")
        rows = []
        for ch in changes:
            if ch["signal"] == "entry":
                sig = "🔴入场"
            elif ch["signal"] == "exit":
                sig = "🟢退出"
            else:
                sig = "—"
            rows.append({
                "日期": data_date,
                "ETF": f'{ch["name"]} ({ch["code"]})',
                "份额(万份)": f'{ch["shares"]:,.0f}',
                "变化(万份)": f'{ch["shares_change"]:+,.0f}',
                "变化率": f'{ch["shares_change_pct"]:+.2f}%',
                "估算资金流(亿)": ch["est_flow"],
                "信号": sig,
            })

        def color_flow(val):
            if isinstance(val, (int, float)):
                return 'color: #c62828' if val > 0 else 'color: #2e7d32' if val < 0 else ''
            return ''

        st.dataframe(
            pd.DataFrame(rows).style.map(color_flow, subset=['估算资金流(亿)']),
            use_container_width=True, hide_index=True, height=300,
        )

    st.divider()

    # ── Historical Trend (from CSV) ──
    st.subheader("历史资金流向趋势")
    history_df = load_history_csv()

    if not history_df.empty:
        # Daily aggregate from history
        history_df = history_df.sort_values("trade_date")
        daily = history_df.groupby("trade_date")["est_flow"].sum().reset_index()

        history_end = history_df["trade_date"].max().strftime("%Y-%m-%d")
        st.caption(f"历史数据范围: {history_df['trade_date'].min().strftime('%Y-%m-%d')} ~ {history_end}")

        colors = ['#c62828' if x >= 0 else '#2e7d32' for x in daily["est_flow"]]
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Bar(
            x=daily["trade_date"], y=daily["est_flow"],
            marker_color=colors, name="日资金流",
            hovertemplate='%{x|%Y-%m-%d}: %{y:+.1f}亿元<extra></extra>'
        ))
        fig_hist.add_trace(go.Scatter(
            x=daily["trade_date"], y=daily["est_flow"].cumsum(),
            mode='lines', line=dict(color='#1565c0', width=2, dash='dot'),
            name="累计资金流", yaxis="y2",
            hovertemplate='累计: %{y:+.1f}亿元<extra></extra>'
        ))
        fig_hist.update_layout(
            height=400, hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis=dict(title="日净流入(亿元)"),
            yaxis2=dict(title="累计(亿元)", overlaying="y", side="right"),
        )
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.warning("暂无历史数据。数据积累中，请稍后再来查看趋势图。")

    st.divider()

    # ── Recent ETF Share Trends ──
    st.subheader("ETF份额变化趋势")
    if not history_df.empty:
        tier1_etfs = [e for e in CORE_ETFS if e.tier == 1]
        fig_shares = go.Figure()
        colors = px.colors.qualitative.Dark24  # 24色自动循环
        for i, etf in enumerate(tier1_etfs):
            etf_hist = history_df[history_df["code"] == etf.code].sort_values("trade_date")
            if not etf_hist.empty and not etf_hist["shares"].isna().all():
                # Normalize
                first_shares = etf_hist["shares"].iloc[0]
                if first_shares > 0:
                    norm = etf_hist["shares"] / first_shares * 100
                    fig_shares.add_trace(go.Scatter(
                        x=etf_hist["trade_date"], y=norm,
                        mode='lines', name=f"{etf.name}({etf.code})",
                        line=dict(color=colors[i % len(colors)], width=2),
                    ))
        if fig_shares.data:
            fig_shares.update_layout(
                title="核心宽基ETF份额变化（归一化，起始日=100）",
                height=350, hovermode="x unified",
                margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig_shares, use_container_width=True)
    else:
        st.info("数据积累中，历史趋势图将在多次更新后展示。")

# ═══════════════════════ PAGE 2: ETF DETAIL ═══════════════════════
with tab2:
    st.title("ETF份额变化明细")

    etf_options = {f"{e.name} ({e.code}) - {e.index_name}": e.code for e in CORE_ETFS}
    selected = st.selectbox("选择ETF", list(etf_options.keys()))
    code = etf_options[selected]
    etf = ETF_MAP[code]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("交易所", etf.exchange)
    col2.metric("跟踪指数", etf.index_name)
    col3.metric("优先级", "核心" if etf.tier == 1 else "辅助")
    col4.metric("使用者", etf.used_by)

    st.divider()

    history_df = load_history_csv()
    if not history_df.empty:
        etf_hist = history_df[history_df["code"] == code].sort_values("trade_date")
        if not etf_hist.empty:
            # Shares trend
            fig_s = go.Figure()
            fig_s.add_trace(go.Scatter(
                x=etf_hist["trade_date"], y=etf_hist["shares"],
                mode='lines+markers', line=dict(color='#1f77b4', width=2.5),
                marker=dict(size=4),
                name="份额(万份)",
                hovertemplate='%{x|%Y-%m-%d}: %{y:,.0f}万份<extra></extra>'
            ))
            fig_s.update_layout(
                title=f"{etf.name} ({code}) — 份额变化趋势",
                height=350, hovermode="x unified",
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_s, use_container_width=True)

            # Daily change
            if "est_flow" in etf_hist.columns:
                colors_flow = ['#c62828' if x >= 0 else '#2e7d32' for x in etf_hist["est_flow"]]
                fig_f = go.Figure()
                fig_f.add_trace(go.Bar(
                    x=etf_hist["trade_date"], y=etf_hist["est_flow"],
                    marker_color=colors_flow,
                    hovertemplate='%{x|%Y-%m-%d}: %{y:+.1f}亿元<extra></extra>'
                ))
                fig_f.update_layout(
                    title=f"{etf.name} ({code}) — 每日估算资金流",
                    height=300, margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_f, use_container_width=True)

            # Stats
            c1, c2, c3 = st.columns(3)
            pos = etf_hist[etf_hist["est_flow"] > 0]["est_flow"].sum()
            neg = etf_hist[etf_hist["est_flow"] < 0]["est_flow"].sum()
            c1.metric("总流入", f"{pos:+.1f}亿")
            c2.metric("总流出", f"{neg:+.1f}亿")
            c3.metric("净流动", f"{pos+neg:+.1f}亿")
        else:
            st.warning(f"暂无 {etf.name}({code}) 的历史数据。")
    else:
        st.warning("暂无历史数据。数据积累中，每天更新后会越来越丰富。")

    # ── Current snapshot for this ETF ──
    st.divider()
    st.subheader("最新快照")
    live = get_live_snapshot()
    d = live.get(code, {})
    if d.get("shares"):
        st.metric("当前份额", f'{d["shares"]:,.0f}万份')
        st.metric("最新价", f'{d.get("price", 0):.3f}元')

# ═══════════════════════ PAGE 3: ABOUT ═══════════════════════
with tab3:
    st.title("关于国家队ETF资金流哨兵")

    st.markdown("""
    ### 这是什么？

    通过监测A股核心宽基ETF的**份额变化**，反推**国家队**（中央汇金、中国国新、中国诚通）
    在A股市场的资金流向。

    ### 工作原理

    国家队在A股的操作呈现**"涨卖跌买"逆周期规律**：
    - 市场急跌时 → 大额申购宽基ETF托底
    - 市场过热时 → 减持降温引导慢牛

    本工具每日获取上交所ETF份额数据，当 ≥3个核心ETF同日出现大额净申购时，
    自动标记为国家队"入场/护盘"信号。

    ### 监测ETF

    沪深300ETF (510300)、上证50ETF (510050)、中证500ETF (510500)、
    中证1000ETF (512100)、科创50ETF (588000) 等8只宽基ETF。

    ### 数据来源

    - 上交所ETF份额数据（T+1更新）
    - AKShare 免费开源金融数据库
    - 底层数据来自东方财富 / 上交所

    ### 局限性

    - 仅准确追踪**上交所**ETF（深交所无公开按日历史份额接口）
    - ETF份额变化含散户和机构噪音，非国家队精确持仓
    - 资金流估算 = 日份额变化 × 收盘价（简化计算）
    - ⚠️ 仅供参考，不构成投资建议

    ### 技术栈

    Python + AKShare + Streamlit + Plotly | Streamlit Cloud 部署
    """)

    st.divider()
    st.caption("© 2026 国家队ETF资金流哨兵 | T+1数据延迟 | 不构成投资建议")
