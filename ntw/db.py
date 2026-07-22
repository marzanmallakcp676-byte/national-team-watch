"""SQLite数据存储层 — 持久化ETF份额数据"""

import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
import os

from .config import CORE_ETFS, DB_PATH

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FULL = os.path.join(os.path.dirname(DB_DIR), DB_PATH)


def get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FULL)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS etf_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            shares REAL,          -- 份额（万份）
            nav REAL,             -- 单位净值
            price REAL,           -- 收盘价
            fund_flow_main REAL,  -- 主力资金净流入（万元）
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(code, trade_date)
        );

        CREATE INDEX IF NOT EXISTS idx_etf_shares_code ON etf_shares(code);
        CREATE INDEX IF NOT EXISTS idx_etf_shares_date ON etf_shares(trade_date);
        CREATE INDEX IF NOT EXISTS idx_etf_shares_codedate ON etf_shares(code, trade_date);

        CREATE TABLE IF NOT EXISTS etf_daily_change (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            shares_change REAL,        -- 份额变化量（万份）
            shares_change_pct REAL,    -- 份额变化率（%）
            est_flow REAL,             -- 估算资金净流入（亿元）
            signal TEXT,               -- 信号类型: entry/exit/none
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            signal_type TEXT NOT NULL,  -- 'entry'(国家队入场) / 'exit'(国家队退出) / 'rotation'(轮动)
            description TEXT,
            etf_codes TEXT,             -- 涉及的ETF代码，逗号分隔
            total_flow REAL,            -- 合计估算资金流（亿元）
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_signal_date ON signal_log(trade_date);
    """)
    conn.commit()
    conn.close()


def save_etf_shares(code: str, trade_date: str, shares: float = None,
                    nav: float = None, price: float = None,
                    fund_flow_main: float = None):
    """保存单条ETF份额数据"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO etf_shares (code, trade_date, shares, nav, price, fund_flow_main)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (code, trade_date, shares, nav, price, fund_flow_main))
    conn.commit()
    conn.close()


def save_daily_change(code: str, trade_date: str, shares_change: float,
                      shares_change_pct: float, est_flow: float, signal: str = "none"):
    """保存ETF日变化数据"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO etf_daily_change (code, trade_date, shares_change,
            shares_change_pct, est_flow, signal)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (code, trade_date, shares_change, shares_change_pct, est_flow, signal))
    conn.commit()
    conn.close()


def save_signal(trade_date: str, signal_type: str, description: str,
                etf_codes: str, total_flow: float):
    """保存国家队信号"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO signal_log (trade_date, signal_type, description, etf_codes, total_flow)
        VALUES (?, ?, ?, ?, ?)
    """, (trade_date, signal_type, description, etf_codes, total_flow))
    conn.commit()
    conn.close()


def get_etf_history(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取ETF历史份额数据"""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM etf_shares
        WHERE code = ? AND trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date
    """, conn, params=(code, start_date, end_date))
    conn.close()
    return df


def get_daily_changes(start_date: str, end_date: str) -> pd.DataFrame:
    """获取日变化数据"""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM etf_daily_change
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date, code
    """, conn, params=(start_date, end_date))
    conn.close()
    return df


def get_signals(start_date: str, end_date: str) -> pd.DataFrame:
    """获取国家队信号历史"""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM signal_log
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date DESC
    """, conn, params=(start_date, end_date))
    conn.close()
    return df


def get_latest_trade_date() -> Optional[str]:
    """获取数据库中最新的交易日"""
    conn = get_conn()
    row = conn.execute("SELECT MAX(trade_date) as d FROM etf_shares").fetchone()
    conn.close()
    return row["d"] if row and row["d"] else None


def get_all_latest_shares() -> pd.DataFrame:
    """获取所有ETF最新一份份额数据"""
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT a.* FROM etf_shares a
        INNER JOIN (
            SELECT code, MAX(trade_date) as max_date FROM etf_shares GROUP BY code
        ) b ON a.code = b.code AND a.trade_date = b.max_date
    """, conn)
    conn.close()
    return df
