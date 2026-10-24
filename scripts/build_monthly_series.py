"""
从累计值还原连续月度序列
========================

背景
----
国家邮政局每月发布「1-X月」累计口径的公报，但不是每个月都能拿到。
只要拿到若干期**累计值**，就能用差分把中间月份还原出来：

    某月业务量 = 本期累计 − 上期累计

如果两期之间恰好只缺 1 个月，且知道后一期的「当月值」，还能进一步拆分：

    缺失月 = (本期累计 − 上期累计) − 后一期当月值

产物
----
    ads_monthly_volume 表（写入 MySQL）
    data/processed/monthly_volume_<年份>.csv

每条记录都带 `derive_method` 字段，标明这个数字是：
    原始差值  —— 两期累计直接相减，误差最小
    推导拆分  —— 用当月值反推，受四舍五入影响
    合并区间  —— 缺太多期无法拆分，只能给出区间合计（如「1-2月」）
这样任何数字都能追溯来源，不做无依据的插值。

用法
----
    python scripts/build_monthly_series.py
    python scripts/build_monthly_series.py --year 2024 --metric 快递业务量
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "processed"
DW_NAME = "logistics_dw"


def build_engine() -> Engine:
    load_dotenv(BASE_DIR / ".env")
    for k in ("DB_USER", "DB_PASSWORD"):
        if not os.getenv(k):
            sys.exit(f"缺少环境变量 {k}，请先配置 .env")
    url = (
        f"mysql+pymysql://{os.environ['DB_USER']}:"
        f"{quote_plus(os.environ['DB_PASSWORD'])}@"
        f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '3306')}/"
        f"{os.getenv('DW_NAME', DW_NAME)}?charset=utf8mb4"
    )
    return create_engine(url, pool_pre_ping=True)


def reconstruct(rows: list[tuple[int, float, float | None]]) -> list[dict]:
    """
    rows: [(月末月份, 累计值, 当月值)]，按月份升序。
    返回按月/区间的还原结果。
    """
    rows = sorted(rows, key=lambda r: r[0])
    out: list[dict] = []
    prev_m, prev_cum = 0, 0.0

    for m, cum, cur in rows:
        segment = round(cum - prev_cum, 4)      # 本区间总增量
        span = m - prev_m                        # 覆盖几个月

        if span == 1:
            out.append({
                "month_start": prev_m + 1, "month_end": m,
                "volume": segment, "derive_method": "原始差值",
            })
        elif span == 2 and cur is not None:
            # 缺 1 个月，用后一期的当月值拆分
            out.append({
                "month_start": prev_m + 1, "month_end": m - 1,
                "volume": round(segment - cur, 4), "derive_method": "推导拆分",
            })
            out.append({
                "month_start": m, "month_end": m,
                "volume": round(cur, 4), "derive_method": "原始差值",
            })
        elif cur is not None and span > 1:
            # 缺多个月：末尾月份有当月值，剩下的合并成一个区间
            out.append({
                "month_start": prev_m + 1, "month_end": m - 1,
                "volume": round(segment - cur, 4), "derive_method": "合并区间",
            })
            out.append({
                "month_start": m, "month_end": m,
                "volume": round(cur, 4), "derive_method": "原始差值",
            })
        else:
            out.append({
                "month_start": prev_m + 1, "month_end": m,
                "volume": segment, "derive_method": "合并区间",
            })

        prev_m, prev_cum = m, cum

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--metric", default="快递业务量")
    args = ap.parse_args()

    engine = build_engine()

    df = pd.read_sql(
        text("""
            SELECT period_label, period_month, cumulative, current
            FROM ods_spb_national
            WHERE period_year = :y AND metric = :m AND cumulative IS NOT NULL
            ORDER BY period_month
        """),
        engine, params={"y": args.year, "m": args.metric},
    )

    if df.empty:
        sys.exit(f"没有找到 {args.year} 年「{args.metric}」的数据")

    print(f"{args.year} 年「{args.metric}」原始累计点：")
    for _, r in df.iterrows():
        print(f"  {r['period_label']:14} 月末={r['period_month']:>2}  "
              f"累计={r['cumulative']:>10.2f}  当月={r['current']}")

    rows = [(int(r["period_month"]), float(r["cumulative"]),
             None if pd.isna(r["current"]) else float(r["current"]))
            for _, r in df.iterrows()]

    series = reconstruct(rows)

    result = pd.DataFrame(series)
    result.insert(0, "year", args.year)
    result.insert(1, "metric", args.metric)
    result["unit"] = "亿件"
    result["period_label"] = result.apply(
        lambda r: (f"{r.month_start}月" if r.month_start == r.month_end
                   else f"{r.month_start}-{r.month_end}月"), axis=1)

    print(f"\n还原后的序列（{len(result)} 个数据点）：")
    print(result[["period_label", "volume", "derive_method"]].to_string(index=False))
    print(f"\n合计校验：{result['volume'].sum():.2f} 亿件  "
          f"| 官方全年累计：{df['cumulative'].max():.2f} 亿件")

    # 写库
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ads_monthly_volume"))
        result.to_sql("ads_monthly_volume", conn, index=False)
    print("\n✓ 已写入 MySQL 表 ads_monthly_volume")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"monthly_volume_{args.year}.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"✓ 已导出 {csv_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
