"""
车辆路径问题（CVRP）：配送 31 个省会城市
=========================================

问题
----
    1 个枢纽仓（郑州）+ 30 个客户城市，K 辆车，每辆有容量上限，
    求总行驶距离最短的配送路线。

算法（全部手写，不依赖 OR-Tools）
--------------------------------
    构造：Clarke-Wright 节约算法
        - 先假设每个城市单独一条线路（车从仓库出发、送完就回）
        - 计算「把 i 和 j 合并到同一线路」能省多少公里：
              saving(i,j) = d(0,i) + d(0,j) − d(i,j)
        - 按节省量从大到小排序，贪心地合并线路，
          只要两端相邻、且合并后不超车辆容量

    改进：2-opt 局部搜索
        - 在单条线路内，尝试把「i→i+1 ... j→j+1」这一段反转成
          「i→j ... i+1→j+1」，如果距离变短就保留
        - 反复直到没有任何改进（局部最优）

    对照组：最近邻法（nearest neighbor）
        - 从仓库出发，每次去最近的未访问城市，装不下就回仓库换车
        - 这是最直觉的做法，用来衡量节约算法到底赚了多少

为什么不用现成求解器
--------------------
本机 Smart App Control 拦截了 OR-Tools 的未签名原生 DLL，无法加载。
手写反而有个好处：算法每一步都能讲清楚，结果可复现、可验证，
而且这些算法（节约算法、2-opt）本身就是物流工程的专业课内容。

输出
----
    output/vrp_routes.png        路线可视化
    output/vrp_routes.csv        每条线路的访问顺序与距离
    output/vrp_summary.csv       三种方案的对比指标

用法
----
    python src/vrp_solver.py                    # 默认 4 辆车
    python src/vrp_solver.py --vehicles 3
    python src/vrp_solver.py --vehicles 5 --capacity 43
"""

from __future__ import annotations

import argparse
import itertools
import os
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

DEPOT_PROVINCE = "河南"   # 郑州：地理居中，实际也是全国性物流枢纽


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------

def load_data():
    """返回 (客户表, 距离矩阵, 仓库索引)。索引 0 固定为仓库。"""
    df = pd.read_csv(DATA_DIR / "customers.csv")
    dist = pd.read_csv(DATA_DIR / "distance_matrix.csv", header=None).to_numpy()

    depot_row = df.index[df.province == DEPOT_PROVINCE]
    if len(depot_row) == 0:
        raise SystemExit(f"数据里找不到仓库所在省份：{DEPOT_PROVINCE}")
    depot = int(depot_row[0])

    # 把仓库挪到索引 0，其余保持顺序
    order = [depot] + [i for i in range(len(df)) if i != depot]
    df = df.iloc[order].reset_index(drop=True)
    dist = dist[np.ix_(order, order)]
    return df, dist, 0


def route_distance(route: list[int], dist: np.ndarray) -> float:
    """一条线路的距离：仓库 → 各点 → 仓库。"""
    total = dist[0, route[0]]
    for a, b in zip(route, route[1:]):
        total += dist[a, b]
    return total + dist[route[-1], 0]


def solution_distance(routes: list[list[int]], dist: np.ndarray) -> float:
    return sum(route_distance(r, dist) for r in routes if r)


# ---------------------------------------------------------------------------
# 对照：最近邻法
# ---------------------------------------------------------------------------

def nearest_neighbor(demand: np.ndarray, dist: np.ndarray,
                     capacity: int, max_vehicles: int) -> list[list[int]]:
    """从仓库出发每次去最近的可行城市，装不下就回车换一辆。"""
    n = len(demand)
    unvisited = set(range(1, n))
    routes: list[list[int]] = []

    while unvisited and len(routes) < max_vehicles:
        route: list[int] = []
        load = 0
        cur = 0
        while True:
            candidates = [c for c in unvisited if load + demand[c] <= capacity]
            if not candidates:
                break
            nxt = min(candidates, key=lambda c: dist[cur, c])
            route.append(nxt)
            load += int(demand[nxt])
            unvisited.remove(nxt)
            cur = nxt
        if not route:          # 容量连一个城市都装不下
            break
        routes.append(route)
    return routes


# ---------------------------------------------------------------------------
# Clarke-Wright 节约算法
# ---------------------------------------------------------------------------

def clarke_wright(demand: np.ndarray, dist: np.ndarray,
                  capacity: int, max_vehicles: int) -> list[list[int]]:
    n = len(demand)
    routes: list[list[int]] = [[i] for i in range(1, n)]
    load = {id(r): int(demand[r[0]]) for r in routes}
    owner = {i: r for r in routes for i in r}   # 节点 → 所属线路

    # 计算所有节约值，从大到小排序
    savings = []
    for i, j in itertools.combinations(range(1, n), 2):
        s = dist[0, i] + dist[0, j] - dist[i, j]
        if s > 0:
            savings.append((s, i, j))
    savings.sort(reverse=True)

    for _, i, j in savings:
        ra, rb = owner.get(i), owner.get(j)
        if ra is None or rb is None or ra is rb:
            continue
        if load[id(ra)] + load[id(rb)] > capacity:
            continue

        # 只有 i 在 ra 端点、j 在 rb 端点时才能合并
        if ra[-1] == i and rb[0] == j:
            merged = ra + rb
        elif ra[-1] == i and rb[-1] == j:
            merged = ra + rb[::-1]
        elif ra[0] == i and rb[0] == j:
            merged = ra[::-1] + rb
        elif ra[0] == i and rb[-1] == j:
            merged = rb + ra
        else:
            continue

        routes.remove(ra)
        routes.remove(rb)
        routes.append(merged)
        load[id(merged)] = load[id(ra)] + load[id(rb)]
        for node in merged:
            owner[node] = merged

    if len(routes) > max_vehicles:
        print(f"⚠️ 节约算法得到 {len(routes)} 条线路，超过车辆数上限 {max_vehicles}")
    return routes


# ---------------------------------------------------------------------------
# 改进：2-opt
# ---------------------------------------------------------------------------

def two_opt(route: list[int], dist: np.ndarray, max_pass: int = 200) -> list[int]:
    """线路内 2-opt：反转一段区间，距离变短就保留。"""
    if len(route) < 3:
        return route
    best = route[:]
    best_len = route_distance(best, dist)
    improved = True
    passes = 0

    while improved and passes < max_pass:
        improved = False
        passes += 1
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cand_len = route_distance(cand, dist)
                if cand_len < best_len - 1e-6:
                    best, best_len = cand, cand_len
                    improved = True
    return best


def apply_two_opt(routes: list[list[int]], dist: np.ndarray) -> list[list[int]]:
    return [two_opt(r, dist) for r in routes]


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def setup_cjk_font() -> None:
    for font in ("Microsoft YaHei", "SimHei", "DengXian"):
        plt.rcParams["font.sans-serif"] = [font]
        plt.rcParams["axes.unicode_minus"] = False


def plot_routes(df: pd.DataFrame, routes: list[list[int]], dist: np.ndarray,
                title: str, path: Path) -> None:
    setup_cjk_font()
    fig, ax = plt.subplots(figsize=(11, 8))
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(routes), 1)))

    for k, route in enumerate(routes):
        xs = [df.lon[0]] + [df.lon[i] for i in route] + [df.lon[0]]
        ys = [df.lat[0]] + [df.lat[i] for i in route] + [df.lat[0]]
        ax.plot(xs, ys, "-o", color=colors[k], linewidth=1.6, markersize=4,
                alpha=0.85, label=f"线路 {k + 1}：{route_distance(route, dist):,.0f} km")

    ax.scatter(df.lon[0], df.lat[0], marker="*", s=520, c="red",
               edgecolors="black", zorder=5, label="枢纽仓（郑州）")
    for _, r in df.iterrows():
        if r.province == DEPOT_PROVINCE:
            continue
        ax.annotate(r.capital, (r.lon, r.lat), fontsize=7,
                    xytext=(3, 3), textcoords="offset points", alpha=0.75)

    ax.set_title(title, fontsize=13)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicles", type=int, default=4)
    ap.add_argument("--capacity", type=int, default=None,
                    help="不指定则按 max(最大单点, 总量/K*1.1) 自动推算")
    args = ap.parse_args()

    df, dist, _ = load_data()
    demand = df.demand_units.to_numpy(dtype=int)
    n = len(demand)

    total = int(demand[1:].sum())
    max_single = int(demand[1:].max())
    cap = args.capacity or max(max_single, int(np.ceil(total / args.vehicles * 1.1)))

    print(f"客户点：{n - 1} 个（仓库：{df.capital[0]}）")
    print(f"需求总量：{total} 单位（10 亿件/单位）  最大单点：{max_single}")
    print(f"车辆数：{args.vehicles}  容量：{cap}  总运力：{args.vehicles * cap}")
    print()

    results = {}

    # 1) 最近邻（不改进）
    nn = nearest_neighbor(demand, dist, cap, args.vehicles)
    results["最近邻"] = nn

    # 2) 最近邻 + 2-opt
    results["最近邻 + 2-opt"] = apply_two_opt(nn, dist)

    # 3) Clarke-Wright（不改进）
    cw = clarke_wright(demand, dist, cap, args.vehicles)
    results["节约算法"] = cw

    # 4) Clarke-Wright + 2-opt
    results["节约算法 + 2-opt"] = apply_two_opt(cw, dist)

    rows = []
    for name, routes in results.items():
        routes = [r for r in routes if r]
        d = solution_distance(routes, dist)
        rows.append({
            "方案": name,
            "线路数": len(routes),
            "总距离(km)": round(d),
            "最大线路负载": max(sum(int(demand[x]) for x in r) for r in routes),
        })
    summary = pd.DataFrame(rows)

    base = summary.loc[summary["方案"] == "节约算法 + 2-opt", "总距离(km)"].iloc[0]
    summary["相对最优差值(km)"] = summary["总距离(km)"] - base
    summary["相对最优差值(%)"] = (summary["相对最优差值(km)"] / base * 100).round(1)

    print("=" * 72)
    print("四种方案对比（同一批数据、同一容量约束）")
    print("=" * 72)
    print(summary.to_string(index=False))

    nn_d = summary.loc[summary["方案"] == "最近邻", "总距离(km)"].iloc[0]
    best_name = summary.loc[summary["总距离(km)"].idxmin(), "方案"]
    best_d = summary["总距离(km)"].min()
    print(f"\n最优方案：{best_name}  总距离 {best_d:,} km")
    print(f"相比朴素最近邻（{nn_d:,} km）节省 {nn_d - best_d:,} km，"
          f"降幅 {(nn_d - best_d) / nn_d * 100:.1f}%")

    # 明细
    best_routes = results[best_name]
    detail = []
    for k, r in enumerate(best_routes, 1):
        if not r:
            continue
        detail.append({
            "线路": k,
            "配送顺序": "郑州 → " + " → ".join(df.capital[i] for i in r) + " → 郑州",
            "客户数": len(r),
            "负载": sum(int(demand[i]) for i in r),
            "容量": cap,
            "距离(km)": round(route_distance(r, dist)),
        })
    detail_df = pd.DataFrame(detail)
    print("\n最优方案的线路明细：")
    print(detail_df[["线路", "客户数", "负载", "容量", "距离(km)"]].to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_DIR / "vrp_summary.csv", index=False, encoding="utf-8-sig")
    detail_df.to_csv(OUT_DIR / "vrp_routes.csv", index=False, encoding="utf-8-sig")
    plot_routes(df, best_routes, dist,
                f"配送路线（{args.vehicles} 辆车，容量 {cap}）— {best_name}，总里程 {best_d:,} km",
                OUT_DIR / "vrp_routes.png")

    print(f"\n✓ output/vrp_summary.csv")
    print(f"✓ output/vrp_routes.csv")
    print(f"✓ output/vrp_routes.png")

    # 可行性自检
    violations = []
    for k, r in enumerate(best_routes, 1):
        ld = sum(int(demand[i]) for i in r)
        if ld > cap:
            violations.append(f"线路 {k} 负载 {ld} 超过容量 {cap}")
    served = sorted(i for r in best_routes for i in r)
    if served != list(range(1, n)):
        violations.append("有客户未被覆盖或重复访问")
    print("\n可行性自检：", "全部通过 ✓" if not violations else "发现问题 ✗")
    for v in violations:
        print("  -", v)


if __name__ == "__main__":
    main()
