"""
中国城市物流网络分级分析
=========================

【数据真实性声明 —— 请务必先读】
本脚本连接 MySQL 官方示例数据库 `world` 的 `city` 表，该表只有三个字段：
    Name（城市名）、CountryCode（国家代码）、Population（人口数）

因此必须明确：
  - 「物流等级」是基于【人口规模】按规则划分的，**不是**真实物流业务分级
  - 「模拟订单量」「建议仓储面积」「配送时效」是**基于规则构造的模拟值**，
    不是真实业务数据
  - 本脚本的目的是验证「数据库取数 → 清洗 → 分级建模 → 导出报表」这条方法链路，
    而不是产出真实可用的物流决策依据

真实数据版本的开发计划见 README 的 Roadmap 章节。

【运行方式】
    1. 复制 .env.example 为 .env，填入你自己的数据库密码
    2. pip install -r requirements.txt
    3. python logistics_analysis.py

【输出】
    output/物流分级报表_YYYY-MM-DD.xlsx（含「城市明细」和「层级统计」两个 sheet）
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

# 物流分级规则：人口阈值 -> (等级名称, 建议仓储面积㎡, 目标配送时效小时)
# 这些数值是教学用的假设值，不是行业标准，真实项目应由业务方给定
LEVEL_RULES: list[tuple[int, str, int, int]] = [
    (5_000_000, "A级（核心枢纽）", 10_000, 24),
    (3_000_000, "B级（区域中心）", 5_000, 48),
    (1_000_000, "C级（配送站点）", 1_000, 72),
    (0,         "D级（末端网点）", 200,   96),
]

# 模拟订单量的换算系数：每 100 人 1 单（纯粹为了演示，无业务依据）
SIMULATED_ORDER_PER_CAPITA = 0.01


# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------

def build_engine():
    """从环境变量读取数据库配置并创建连接引擎。"""
    load_dotenv(BASE_DIR / ".env")

    required = ["DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        sys.exit(
            f"缺少环境变量：{', '.join(missing)}\n"
            f"请复制 .env.example 为 .env 并填写数据库信息。"
        )

    user = os.environ["DB_USER"]
    # 密码里可能含有 @ : / 等特殊字符，必须转义后再拼进 URL
    password = quote_plus(os.environ["DB_PASSWORD"])
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    database = os.environ["DB_NAME"]
    charset = os.getenv("DB_CHARSET", "utf8mb4")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"
    return create_engine(url)


# ---------------------------------------------------------------------------
# 业务逻辑
# ---------------------------------------------------------------------------

def assign_level(population: int) -> str:
    """根据人口数返回物流等级名称。"""
    for threshold, level_name, _, _ in LEVEL_RULES:
        if population >= threshold:
            return level_name
    return LEVEL_RULES[-1][1]


def read_city_data(engine) -> pd.DataFrame:
    """从 MySQL 读取中国城市数据。"""
    sql = """
        SELECT Name AS 城市, Population AS 人口数
        FROM city
        WHERE CountryCode = 'CHN'
        ORDER BY Population DESC
    """
    df = pd.read_sql(sql, engine)

    # 清洗：去掉人口为空或非正数的脏数据
    before = len(df)
    df = df[df["人口数"].notna() & (df["人口数"] > 0)].copy()
    if before != len(df):
        print(f"🧹 清洗掉 {before - len(df)} 条异常记录")

    return df.reset_index(drop=True)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """派生物流等级与模拟业务字段。"""
    df = df.copy()
    df["物流等级"] = df["人口数"].apply(assign_level)

    # 用字典映射代替多次 map，可读性和性能都更好
    level_to_area = {name: area for _, name, area, _ in LEVEL_RULES}
    level_to_hours = {name: hours for _, name, _, hours in LEVEL_RULES}

    df["建议仓储面积(㎡)"] = df["物流等级"].map(level_to_area)
    df["配送时效(小时)"] = df["物流等级"].map(level_to_hours)

    # ⚠️ 模拟字段，无业务依据
    df["模拟订单量"] = (df["人口数"] * SIMULATED_ORDER_PER_CAPITA).astype(int)

    return df


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按物流等级汇总城市数量与模拟业务量。"""
    summary = (
        df.groupby("物流等级")
        .agg(
            城市数量=("城市", "count"),
            覆盖人口=("人口数", "sum"),
            模拟订单总量=("模拟订单量", "sum"),
        )
        .reset_index()
    )
    # 按等级名称排序，保证 A→D 的顺序
    level_order = [name for _, name, _, _ in LEVEL_RULES]
    summary["_order"] = summary["物流等级"].map(
        {name: i for i, name in enumerate(level_order)}
    )
    return summary.sort_values("_order").drop(columns="_order").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def export(df: pd.DataFrame, summary: pd.DataFrame) -> Path:
    """导出为带日期的 Excel 报表。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.today().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"物流分级报表_{today}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="城市明细", index=False)
        summary.to_excel(writer, sheet_name="层级统计", index=False)

    return output_path


def main() -> None:
    engine = build_engine()

    df = read_city_data(engine)
    print(f"✅ 成功读取 {len(df)} 条中国城市记录")

    df = enrich(df)
    summary = build_summary(df)

    print("\n📊 物流网络层级规划：")
    print(summary.to_string(index=False))

    path = export(df, summary)
    print(f"\n✅ 报表已保存：{path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
