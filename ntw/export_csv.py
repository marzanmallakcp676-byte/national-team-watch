"""导出 SQLite 数据为 CSV，供 Streamlit Cloud 使用"""

import pandas as pd
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ntw.db import get_conn

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OUTPUT = os.path.join(DATA_DIR, "history.csv")


def export():
    conn = get_conn()

    # 查询：ETF份额 + 日变化合并
    sql = """
    SELECT
        s.code,
        s.trade_date,
        s.shares,
        s.price,
        c.shares_change,
        c.shares_change_pct,
        c.est_flow,
        c.signal
    FROM etf_shares s
    LEFT JOIN etf_daily_change c
        ON s.code = c.code AND s.trade_date = c.trade_date
    ORDER BY s.trade_date, s.code
    """
    df = pd.read_sql_query(sql, conn)
    conn.close()

    if df.empty:
        print("数据库为空，请先运行 python3 -m ntw.cli backfill")
        return

    df.to_csv(OUTPUT, index=False, encoding="utf-8")
    print(f"导出完成: {OUTPUT}")
    print(f"  {len(df)} 条记录")
    print(f"  {df['code'].nunique()} 只ETF")
    print(f"  日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")


if __name__ == "__main__":
    export()
