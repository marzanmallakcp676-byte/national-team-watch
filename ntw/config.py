"""国家队监测ETF清单配置"""

from dataclasses import dataclass
from typing import List

@dataclass
class ETFInfo:
    code: str          # 交易代码
    name: str          # 简称
    full_name: str     # 全称
    exchange: str      # 交易所 SSE/SZSE
    index_name: str    # 跟踪指数
    tier: int          # 优先级 1=核心 2=辅助
    used_by: str       # 国家队使用者

# ── 国家队核心宽基ETF清单 ──
# 汇金买宽基（沪深300/上证50/中证500/中证1000/科创50）
# 国新买央企+科技ETF；诚通买全市场宽基+科技
# 数据来源：各ETF季报前十大持有人 + 公开报道
CORE_ETFS: List[ETFInfo] = [
    # ═══ 沪深300（汇金最大持仓品种，有多只ETF）═══
    ETFInfo("510300", "沪深300ETF",    "华泰柏瑞沪深300ETF",    "SSE",  "沪深300",   1, "汇金"),
    ETFInfo("510330", "沪深300ETF",    "华夏沪深300ETF",         "SSE",  "沪深300",   1, "汇金"),
    ETFInfo("510310", "沪深300ETF",    "易方达沪深300ETF",       "SSE",  "沪深300",   1, "汇金"),
    ETFInfo("159919", "沪深300ETF",    "嘉实沪深300ETF",         "SZSE", "沪深300",   2, "汇金"),
    # ═══ 上证50 ═══
    ETFInfo("510050", "上证50ETF",      "华夏上证50ETF",         "SSE",  "上证50",    1, "汇金"),
    # ═══ 中证500 ═══
    ETFInfo("510500", "中证500ETF",     "南方中证500ETF",        "SSE",  "中证500",   1, "汇金"),
    ETFInfo("159922", "中证500ETF",     "嘉实中证500ETF",         "SZSE", "中证500",   2, "汇金"),
    # ═══ 中证1000 ═══
    ETFInfo("512100", "中证1000ETF",    "南方中证1000ETF",       "SSE",  "中证1000",  1, "汇金+诚通"),
    ETFInfo("159845", "中证1000ETF",    "华夏中证1000ETF",       "SZSE", "中证1000",  2, "汇金+诚通"),
    # ═══ 科创50（国新2026年新增，7月20日大买）═══
    ETFInfo("588000", "科创50ETF",      "华夏科创50ETF",         "SSE",  "科创50",    1, "汇金+国新"),
    ETFInfo("588080", "科创50ETF",      "易方达科创50ETF",        "SSE",  "科创50",    2, "汇金+国新"),
    # ═══ 创业板 ═══
    ETFInfo("159915", "创业板ETF",      "易方达创业板ETF",       "SZSE", "创业板指",  2, "诚通"),
    # ═══ 中证A500（2025新品种，汇金/诚通均有）═══
    ETFInfo("563300", "中证A500ETF",    "华泰柏瑞中证A500ETF",   "SSE",  "中证A500",  2, "汇金+诚通"),
    # ═══ 央企科技（国新专属武器）═══
    ETFInfo("560170", "央企科技ETF",    "南方中证国新央企科技引领ETF", "SSE", "央企科技", 2, "国新"),
]
# 共计10只，覆盖汇金+国新+诚通主要操作通道

# ── 按代码索引 ──
ETF_MAP = {etf.code: etf for etf in CORE_ETFS}

# ── 国家队主体 ──
NATIONAL_TEAM = ["中央汇金", "中国国新", "中国诚通"]

# ── 信号阈值 ──
SIGNAL_THRESHOLDS = {
    "entry_share_pct": 5.0,        # 单日份额增幅超过5%
    "entry_share_abs": 10.0,       # 绝对增量超过10亿份
    "entry_min_etfs": 3,           # 同日至少3个核心ETF触发
    "exit_consecutive_days": 3,    # 连续流出天数
    "exit_cumulative_share": 50.0, # 累计流出超过50亿份
    "rotation_tolerance": 0.3,     # 轮动判断容忍度（流入流出差额<30%视为轮动）
}

# ── DB路径 ──
DB_PATH = "ntw_data.db"
