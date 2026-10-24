"""
把抓取到的原始数据装载进 MySQL 数据仓库，并导出 Power BI 用的 ADS 宽表
======================================================================

流程
----
    1. 读取 .env 里的数据库连接信息
    2. 创建数据库 logistics_dw（若不存在）
    3. 执行 sql/01_schema.sql：建 ODS 表 + DWD/DWS/ADS 视图
    4. TRUNCATE 后重新装载 CSV 到 ODS（幂等）
    5. 校验各层行数
    6. 从 ADS 层取数，打印关键洞察，并导出 Excel 供 Power BI 使用

用法
----
    python scripts/load_mysql.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
SQL_DIR = BASE_DIR / "sql"
OUT_DIR = BASE_DIR / "output"

DW_NAME = "logistics_dw"


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------

def build_engine(with_db: bool = True) -> Engine:
    load_dotenv(BASE_DIR / ".env")
    required = ["DB_USER", "DB_PASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        sys.exit(f"缺少环境变量 {', '.join(missing)}，请先复制 .env.example 为 .env 并填写")

    user = os.environ["DB_USER"]
    pwd = quote_plus(os.environ["DB_PASSWORD"])
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    db = os.getenv("DW_NAME", DW_NAME)

    suffix = f"/{db}" if with_db else "/"
    url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}{suffix}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def split_sql(script: str) -> list[str]:
    """去掉 -- 注释，按分号切分语句。"""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. 创建数据库
    db_name = os.getenv("DW_NAME", DW_NAME) if load_dotenv(BASE_DIR / ".env") is None else DW_NAME
    load_dotenv(BASE_DIR / ".env")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    print(f"连接 MySQL：{host}:{port}")

    root_engine = build_engine(with_db=False)
    with root_engine.begin() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        ))
    print(f"✓ 数据库 `{db_name}` 就绪")

    engine = build_engine(with_db=True)

    # 2. 建表 + 视图
    ddl = (SQL_DIR / "01_schema.sql").read_text(encoding="utf-8")
    stmts = split_sql(ddl)
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
    print(f"✓ 已执行 {len(stmts)} 条建表/建视图语句")

    # 3. 装载 ODS
    files = {
        "ods_spb_national": "spb_national.csv",
        "ods_spb_province": "spb_province.csv",
        "ods_spb_city": "spb_city.csv",
    }
    with engine.begin() as conn:
        for table, fname in files.items():
            path = RAW_DIR / fname
            if not path.exists():
                sys.exit(f"找不到 {path}，请先运行 scripts/fetch_spb.py")

            df = pd.read_csv(path)
            # 日期列转 datetime，空值转 None
            if "publish_date" in df.columns:
                df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce")
            df = df.astype(object).where(pd.notna(df), None)

            conn.execute(text(f"TRUNCATE TABLE {table}"))
            df.to_sql(table, conn, if_exists="append", index=False)
            print(f"✓ {table:20} 装载 {len(df):>4} 行")

    # 4. 校验各层
    print("\n各层行数：")
    with engine.connect() as conn:
        for obj in ["ods_spb_national", "ods_spb_province", "ods_spb_city",
                    "dwd_city", "dwd_province",
                    "dws_city_concentration", "dws_region_share",
                    "ads_city_network", "ads_national_trend", "ads_province_compare"]:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {obj}")).scalar()
            print(f"  {obj:24} {n:>5} 行")

    # 5. ADS 洞察 + 导出
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    city = pd.read_sql("SELECT * FROM ads_city_network", engine)
    prov = pd.read_sql("SELECT * FROM ads_province_compare", engine)
    natl = pd.read_sql("SELECT * FROM ads_national_trend", engine)
    conc = pd.read_sql("SELECT * FROM dws_city_concentration", engine)
    regn = pd.read_sql("SELECT * FROM dws_region_share", engine)

    print("\n" + "=" * 72)
    print("洞察 1：城市业务量 TOP10（2024年全年）")
    print("=" * 72)
    top = city[city.period_label == "2024年全年"].nsmallest(10, "rank_volume")
    if len(top):
        print(top[["rank_volume", "city", "volume_yi", "revenue_yi",
                   "revenue_per_piece", "pareto_cum_pct"]].to_string(index=False))

    print("\n" + "=" * 72)
    print("洞察 2：单票收入对比 —— 「最忙的城市」不一定是「最赚钱的城市」")
    print("=" * 72)
    t24 = city[city.period_label == "2024年全年"]
    if len(t24):
        busiest = t24.nsmallest(5, "rank_volume")
        priciest = t24.nlargest(5, "revenue_per_piece")
        print("\n  业务量最大的 5 个城市：")
        print(busiest[["city", "volume_yi", "revenue_per_piece"]].to_string(index=False))
        print("\n  单票收入最高的 5 个城市：")
        print(priciest[["city", "volume_yi", "revenue_per_piece"]].to_string(index=False))

    print("\n" + "=" * 72)
    print("洞察 3：城市集中度（TOP50 样本内部）")
    print("=" * 72)
    print(conc[["period_label", "city_cnt", "cr5_pct", "cr10_pct"]].to_string(index=False))

    print("\n" + "=" * 72)
    print("洞察 4：东中西区域结构")
    print("=" * 72)
    latest = regn[regn.period_label == "2024年全年"] if len(regn) else regn
    print(latest[["period_label", "region", "volume_share_pct", "revenue_share_pct"]]
          .to_string(index=False))

    xlsx = OUT_DIR / "快递物流分析_ADS.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        city.to_excel(w, sheet_name="城市网络", index=False)
        prov.to_excel(w, sheet_name="分省对比", index=False)
        natl.to_excel(w, sheet_name="全国趋势", index=False)
        conc.to_excel(w, sheet_name="城市集中度", index=False)
        regn.to_excel(w, sheet_name="区域结构", index=False)

    print(f"\n✓ ADS 宽表已导出：{xlsx.relative_to(BASE_DIR)}")
    print("  可直接用 Power BI 连接，或在 MySQL 中查询 ads_* 视图")


if __name__ == "__main__":
    main()
