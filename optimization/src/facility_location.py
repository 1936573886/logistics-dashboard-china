"""
设施选址（p-median 问题）：在 31 个省会里选 3 个建区域仓
=========================================================

问题
----
    有 31 个需求点（省会城市），需求量 = 该省真实快递业务量。
    要选 p 个点建区域仓，让「所有需求点送到最近仓库」的总运输量最小。

    目标函数：
        minimize  Σ_i  weight_i × distance(i, 最近的仓库)

    单位是「亿件·公里」，可以理解为运输工作量。weight_i 用真实业务量，
    所以这个目标有业务含义：不是让距离最短，而是让「货量大的地方」离仓库近。

解法一：穷举（精确解）
----------------------
    C(31, 3) = 4495 种组合，全部算一遍取最小。
    规模小的时候，穷举就是最好的算法——简单、绝对正确、不需要任何库。

解法二：贪心（对照）
--------------------
    每次选「能让目标函数下降最多」的那一个点，重复 p 次。
    这是实际业务里最常用的快速估算法，但它不保证最优。
    把它跟穷举结果放在一起，就能量化「贪心到底差多少」。

为什么要放两个解
----------------
面试里常被问：「你为什么用这个算法？」
如果你能说「我先用穷举确认真实最优值，再用贪心对比，发现贪心在 p=3 时
只差 0.8%，那实际业务里完全可以用贪心，因为它快得多」——
这就是**用精确解验证启发式**的工程思维，比只说「我调了求解器」强得多。

输出
----
    output/facility_optimal.png    最优方案的可视化（每个点连到最近仓）
    output/facility_sensitivity.csv 不同 p 值下的最优与贪心对比
    output/facility_solution.csv    最优方案明细

用法
----
    python src/facility_location.py
    python src/facility_location.py --p 4
"""

from __future__ import annotations

import argparse
import itertools
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "output"
os.environ.setdefault("MPLCONFIGDIR", str(BASE_DIR / ".mplcache"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def load_data():
    df = pd.read_csv(DATA_DIR / "customers.csv")
    dist = pd.read_csv(DATA_DIR / "distance_matrix.csv", header=None).to_numpy()
    weights = df.volume_yi.to_numpy(dtype=float)
    return df, dist, weights


def objective(hubs: tuple[int, ...], dist: np.ndarray, weights: np.ndarray) -> float:
    """总加权距离：每个需求点到最近仓库的距离 × 需求量。"""
    d = dist[:, list(hubs)].min(axis=1)
    return float(np.dot(weights, d))


def solve_exact(dist: np.ndarray, weights: np.ndarray, p: int):
    """穷举所有 C(n, p) 组合，返回 (最优组合, 最优值, 耗时秒)。"""
    n = len(weights)
    best, best_val = None, float("inf")
    t0 = time.perf_counter()
    for combo in itertools.combinations(range(n), p):
        v = objective(combo, dist, weights)
        if v < best_val:
            best, best_val = combo, v
    return best, best_val, time.perf_counter() - t0


def solve_greedy(dist: np.ndarray, weights: np.ndarray, p: int) -> tuple[int, ...]:
    """贪心：每次选边际收益最大的点。"""
    chosen: list[int] = []
    remaining = set(range(len(weights)))
    for _ in range(p):
        best, best_val = None, float("inf")
        for c in remaining:
            v = objective(tuple(chosen + [c]), dist, weights)
            if v < best_val:
                best, best_val = c, v
        chosen.append(best)
        remaining.remove(best)
    return tuple(chosen)


def setup_cjk_font() -> None:
    for font in ("Microsoft YaHei", "SimHei", "DengXian"):
        plt.rcParams["font.sans-serif"] = [font]
        plt.rcParams["axes.unicode_minus"] = False


def plot_solution(df: pd.DataFrame, dist: np.ndarray, hubs: tuple[int, ...],
                  weights: np.ndarray, path: Path) -> None:
    setup_cjk_font()
    fig, ax = plt.subplots(figsize=(11, 8))

    hub_colors = plt.cm.Set1(np.linspace(0, 1, max(len(hubs), 1)))
    assign = {h: [] for h in hubs}
    for i in range(len(df)):
        nearest = min(hubs, key=lambda h: dist[i, h])
        assign[nearest].append(i)

    for k, h in enumerate(hubs):
        for i in assign[h]:
            ax.plot([df.lon[h], df.lon[i]], [df.lat[h], df.lat[i]],
                    "-", color=hub_colors[k], linewidth=0.7, alpha=0.45)
    for i in range(len(df)):
        ax.scatter(df.lon[i], df.lat[i], s=max(12, weights[i] * 1.6),
                   c="lightsteelblue", edgecolors="gray", linewidths=0.5, zorder=3)
    for k, h in enumerate(hubs):
        ax.scatter(df.lon[h], df.lat[h], marker="*", s=760,
                   c=[hub_colors[k]], edgecolors="black", linewidths=1.2,
                   zorder=6, label=f"区域仓 {k + 1}：{df.capital[h]}")

    for _, r in df.iterrows():
        ax.annotate(r.capital, (r.lon, r.lat), fontsize=7,
                    xytext=(3, 3), textcoords="offset points", alpha=0.7)

    total = objective(hubs, dist, weights)
    ax.set_title(f"区域仓选址（p={len(hubs)}）  目标值 {total:,.0f} 亿件·km", fontsize=13)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p", type=int, default=3, help="建几个区域仓")
    ap.add_argument("--max-p", type=int, default=5, help="灵敏度分析最大到几")
    args = ap.parse_args()

    df, dist, weights = load_data()
    n = len(df)
    print(f"需求点：{n} 个（省会城市）")
    print(f"需求总量：{weights.sum():,.1f} 亿件（真实 2024 年快递业务量）\n")

    # 主方案
    hubs, val, elapsed = solve_exact(dist, weights, args.p)
    greedy = solve_greedy(dist, weights, args.p)
    gval = objective(greedy, dist, weights)

    print("=" * 72)
    print(f"精确解（穷举 C({n},{args.p}) 共 {len(list(itertools.combinations(range(n), args.p)))} 种组合，耗时 {elapsed:.2f}s）")
    print("=" * 72)
    print(f"  区域仓：{' / '.join(df.capital[h] for h in hubs)}")
    print(f"  目标值：{val:,.0f} 亿件·km")
    print()
    print("贪心解（不保证最优）")
    print(f"  区域仓：{' / '.join(df.capital[h] for h in greedy)}")
    print(f"  目标值：{gval:,.0f} 亿件·km")
    gap = (gval - val) / val * 100
    print(f"  与精确解差距：{gval - val:,.0f} 亿件·km（{gap:+.2f}%）")
    if gap < 0.01:
        print("  → 贪心在本题恰好找到最优解。")
    else:
        print("  → 贪心有偏差，需要精确解兜底。")

    # 各仓覆盖
    print("\n各区域仓的覆盖范围：")
    rows = []
    for h in hubs:
        covered = [i for i in range(n) if min(hubs, key=lambda x: dist[i, x]) == h]
        rows.append({
            "区域仓": df.capital[h],
            "覆盖省数": len(covered),
            "覆盖货量(亿件)": round(float(weights[covered].sum()), 1),
            "货量占比": f"{weights[covered].sum() / weights.sum() * 100:.1f}%",
        })
        print(f"  {df.capital[h]:6} 覆盖 {len(covered):>2} 省  "
              f"货量 {weights[covered].sum():>7,.1f} 亿件  "
              f"({weights[covered].sum() / weights.sum() * 100:>5.1f}%)")
    sol_df = pd.DataFrame(rows)

    # 灵敏度：p 从 1 到 max_p
    print("\n" + "=" * 72)
    print("灵敏度分析：多建一个仓能省多少")
    print("=" * 72)
    sens = []
    prev = None
    for p in range(1, args.max_p + 1):
        h, v, t = solve_exact(dist, weights, p)
        g = solve_greedy(dist, weights, p)
        gv = objective(g, dist, weights)
        improv = "" if prev is None else f"{(prev - v) / prev * 100:.1f}%"
        sens.append({
            "p": p,
            "最优目标值": round(v),
            "相对上一档改善": improv,
            "贪心目标值": round(gv),
            "贪心偏差%": round((gv - v) / v * 100, 2),
            "穷举耗时(s)": round(t, 2),
        })
        prev = v
    sens_df = pd.DataFrame(sens)
    print(sens_df.to_string(index=False))
    print("\n注：改善幅度递减说明存在边际收益拐点，是决定建几个仓的主要依据。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sol_df.to_csv(OUT_DIR / "facility_solution.csv", index=False, encoding="utf-8-sig")
    sens_df.to_csv(OUT_DIR / "facility_sensitivity.csv", index=False, encoding="utf-8-sig")
    plot_solution(df, dist, hubs, weights, OUT_DIR / "facility_optimal.png")

    print(f"\n✓ output/facility_solution.csv")
    print(f"✓ output/facility_sensitivity.csv")
    print(f"✓ output/facility_optimal.png")


if __name__ == "__main__":
    main()
