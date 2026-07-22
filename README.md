# 国家队ETF资金流哨兵 (national-team-watch)

监测国家队（中央汇金、中国国新、中国诚通）在A股核心宽基ETF中的资金流向，通过ETF份额变化反推护盘/退出操作。

## 工作原理

国家队在A股的操作遵循"涨卖跌买"的逆周期规则——市场急跌时大额申购宽基ETF托底，市场过热时减持降温。

本工具通过AKShare免费数据接口，每日获取上交所核心宽基ETF的份额数据，计算份额变化量并估算对应的资金流向，当多个ETF同时出现大额异动时自动标记为"国家队信号"。

## 安装

```bash
cd national-team-watch
pip3 install -r requirements.txt --break-system-packages
```

## 使用方法

```bash
# 查看今日ETF申赎概况（含国家队信号判断）
python3 -m ntw.cli today

# 查看指定日期
python3 -m ntw.cli today --date 2026-07-21

# 查看资金流向趋势
python3 -m ntw.cli flow --days 30

# 查看国家队操作信号历史
python3 -m ntw.cli signals --days 30

# 生成Markdown日报 + 图表
python3 -m ntw.cli report

# 列出监测的ETF清单
python3 -m ntw.cli list

# 回溯填充历史数据
python3 -m ntw.cli backfill
```

## 监测ETF清单

| 代码 | 名称 | 跟踪指数 | 优先级 |
|------|------|----------|--------|
| 510300 | 华泰柏瑞沪深300ETF | 沪深300 | ★ 核心 |
| 510050 | 华夏上证50ETF | 上证50 | ★ 核心 |
| 510500 | 南方中证500ETF | 中证500 | ★ 核心 |
| 512100 | 南方中证1000ETF | 中证1000 | ★ 核心 |
| 588000 | 华夏科创50ETF | 科创50 | ★ 核心 |
| 159845 | 华夏中证1000ETF | 中证1000 | ☆ 辅助 |
| 159915 | 易方达创业板ETF | 创业板指 | ☆ 辅助 |
| 563300 | 华泰柏瑞中证A500ETF | 中证A500 | ☆ 辅助 |

## 信号判断规则

| 信号 | 条件 | 含义 |
|------|------|------|
| 🔴 **入场/护盘** | ≥3个核心ETF同日触发大额净申购 | 国家队进场托底 |
| 🟢 **减持/退出** | ≥3个核心ETF同日触发大额净赎回 | 国家队减持降温 |
| 🟡 **轮动换仓** | 部分ETF流入、部分流出，净额相近 | 结构调整而非减仓 |

## 数据来源

- 上交所 ETF 份额数据：`akshare.fund_etf_scale_sse`
- 全市场 ETF 行情数据：`akshare.fund_etf_spot_em`
- 数据源：东方财富 / 上交所

## 局限说明

- 仅能准确追踪上交所ETF的日度份额变化（深交所无公开的按日历史归档接口）
- 国家队具体持仓无法精确识别——我们通过多个宽基ETF的同步异动来推断
- 份额变化包含散户和机构申赎噪音，极端情况下可能误判
- 估算资金流 = 份额变化 × 当日收盘价（简化计算，未考虑加权均价）

## 项目结构

```
national-team-watch/
├── ntw/
│   ├── cli.py          # CLI入口 (Click)
│   ├── config.py       # ETF清单 + 信号阈值配置
│   ├── fetcher.py      # AKShare数据封装
│   ├── db.py           # SQLite存储
│   ├── analyzer.py     # 信号分析引擎
│   ├── reporter.py     # 终端/Markdown报告
│   └── visualizer.py   # Matplotlib图表
├── requirements.txt
├── Makefile
└── README.md
```
