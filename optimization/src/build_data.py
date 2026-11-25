"""
构建 VRP / 选址的输入数据
==========================

把两样东西拼起来：
  1. 31 个省会城市的经纬度        → data/province_capitals.csv（人工维护）
  2. 各省 2024 年快递业务量（真实） → ../stage1-real-data/data/raw/spb_province.csv

产出
----
  data/customers.csv        客户点表：省份、省会、经纬度、真实业务量、需求量
  data/distance_matrix.csv  球面距离矩阵（公里）

关于需求量的单位
----------------
真实业务量跨 3 个数量级（广东 425.9 亿件，西藏 0.3 亿件）。直接拿来当需求量，
会让车辆容量约束变得毫无意义（一辆车装广东就满了）。

所以按 **10 亿件 = 1 个需求单位** 缩放，并对小于 10 亿件的省份保底给 1 个单位：

    demand_units = max(1, round(volume_yi / 10))

这样既保留了「广东 >> 西藏」的真实量级关系，又能构造出容量有意义的 CVRP。
`volume_yi` 列保留原始真实值，任何结论都能回溯。

距离的计算
----------
用 haversine 球面距离，不做路网修正。真实运输距离通常是直线距离的 1.2~1.4 倍，
在 README 里明确标注这个局限，不假装它是路网距离。

用法
----
    python src/build_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STAGE1_PROVINCE_CSV = (BASE_DIR.parent / "stage1-real-data" / "data" / "raw"
                       / "spb_province.csv")

YEAR_LABEL = "2024年全年"
VOLUME_UNIT_YI = 10  # 10 亿件 = 1 个需求单位
EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间球面距离（公里）。"""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlambda = np.radians(lon2 - lon1)
    a = (np.sin(dphi / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(dlambda / 2) ** 2)
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def build() -> None:
    caps = pd.read_csv(DATA_DIR / "province_capitals.csv")
    print(f"省会坐标表：{len(caps)} 行")

    if not STAGE1_PROVINCE_CSV.exists():
        raise SystemExit(
            f"找不到 {STAGE1_PROVINCE_CSV}\n"
            f"请先运行 stage1-real-data/scripts/fetch_spb.py 抓取数据"
        )

    prov = pd.read_csv(STAGE1_PROVINCE_CSV)
    prov = prov[(prov["period_label"] == YEAR_LABEL) & (prov["province"] != "全国")]
    prov = prov[["province", "volume_yi"]]
    print(f"{YEAR_LABEL} 分省业务量：{len(prov)} 行")

    df = caps.merge(prov, left_on="province", right_on="province", how="inner")
    missing = set(caps["province"]) - set(df["province"])
    if missing:
        print(f"⚠️ 这些省份没有匹配到业务量数据：{sorted(missing)}")

    df = df.sort_values("volume_yi", ascending=False).reset_index(drop=True)

    # 需求量：10 亿件 = 1 单位，保底 1
    df["demand_units"] = np.maximum(1, np.round(df["volume_yi"] / VOLUME_UNIT_YI)).astype(int)

    df.to_csv(DATA_DIR / "customers.csv", index=False, encoding="utf-8-sig")
    print(f"\n✓ 已生成 data/customers.csv（{len(df)} 行）")

    # 距离矩阵
    n = len(df)
    mat = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                mat[i, j] = haversine(df.lat[i], df.lon[i], df.lat[j], df.lon[j])
    pd.DataFrame(mat).to_csv(DATA_DIR / "distance_matrix.csv",
                             index=False, header=False, float_format="%.2f")
    print(f"✓ 已生成 data/distance_matrix.csv（{n}×{n}，球面距离 km）")

    # 汇总，顺便给出容量建议
    total_d = int(df.demand_units.sum())
    max_d = int(df.demand_units.max())
    print("\n需求量分布（前 8）：")
    print(df.head(8)[["province", "capital", "volume_yi", "demand_units"]]
          .to_string(index=False))
    print(f"\n需求总量 {total_d} 单位  最大单点 {max_d} 单位（{df.iloc[0]['province']}）")

    for k in (3, 4, 5):
        # 容量下界：既要 >= 最大单点，也要 >= 总量/K；再留 10% 余量
        q = max(max_d, int(np.ceil(total_d / k * 1.1)))
        print(f"  若用 {k} 辆车 → 建议容量 {q}（总运力 {k * q}，利用率 {total_d / (k * q):.0%}）")
    print("\n注：以上容量只是使问题可行的初值，不是最优。")

    # 距离矩阵自检：按省会城市名查
    print("\n距离自检（球面 km，可与常见里程对照）：")
    for a, b in [("北京", "上海"), ("广州", "北京"), ("乌鲁木齐", "上海")]:
        ia = df.index[df.capital == a][0]
        ib = df.index[df.capital == b][0]
        print(f"  {a} → {b}: {mat[ia, ib]:.0f} km")


if __name__ == "__main__":
    build()
