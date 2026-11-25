"""
阶段 2：快递业务量需求预测（练习版 —— 你需要补完 3 个函数）
==============================================================

这个文件里，**框架、数据加载、模型调用、绘图、汇总我都写好了**。
你只需要实现 3 个函数，标着 `### TODO n`（n = 1/2/3）。

补完之后运行：
    python analysis/forecast.py

---

## 先理解数据现实（这决定方案）

你手上是 2024 年 11 个数据点，**只有 1 年**。

1. **做不了季节性模型。** Holt-Winters / SARIMA 这类要季节项的模型，
   至少需要 2 个完整周期（24 个月）。用 1 年的数据硬上季节项 = 过拟合。
   所以这里只用「水平 + 趋势」类模型。

2. **「1-2月」是合并区间**（232.61 亿件，2 个月）。直接放进去会形成一个假尖峰
   （232 vs 常态 140+），把趋势带歪。所以按月均折算：232.61 / 2 = 116.31。

3. **样本只有 11 点，不能做固定比例的训练/测试划分。**
   如果切「前 8 训练、后 3 测试」，测试集只有 3 个点，误差估计没有意义，
   而且训练只用了前期数据，浪费了后面真实发生的信息。
   正确做法是**滚动起点验证**（walk-forward），见 TODO 2。

---

## 三个空分别练什么

| TODO | 函数 | 练的能力 |
|---|---|---|
| 1 | `naive_forecast` | 理解「基准线」为什么必须存在 |
| 2 | `walk_forward` | 理解小样本为什么不切分、滚动验证怎么写 |
| 3 | `mape` | 理解误差指标的实现细节和陷阱 |

---

## 自检标准（写完自己先对一遍）

跑通后，你自己的结果应该落在这几个区间里：

| 模型 | MAPE 应该在 |
|---|---|
| 朴素法 | 4.0% ~ 4.6% |
| 简单指数平滑 | 4.1% ~ 4.6% |
| Holt 趋势 | 3.5% ~ 4.2% |
| 3 期移动平均 | 7.0% ~ 7.6% |

**如果偏离超过 1 个百分点，说明某个函数逻辑有问题，别急着交，先查。**

另外注意：Holt 在 MAPE 上最好，但它的 RMSE 可能比朴素法**更差**。
想一下为什么——这是这批数据里最有意思的一点。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("MPLCONFIGDIR", str(BASE_DIR / ".mplcache"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from statsmodels.tsa.holtwinters import Holt, SimpleExpSmoothing  # noqa: E402

OUT_DIR = BASE_DIR / "output"
DW_NAME = "logistics_dw"

# 滚动验证时，至少用几个点做训练（前面 6 个点训练太薄，模型学不到趋势）
MIN_TRAIN = 6


# ===========================================================================
# 数据加载（已写好，不用改）
# ===========================================================================

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


def load_series(year: int = 2024) -> tuple[pd.DataFrame, Engine | None]:
    """
    优先从 MySQL 的 ads_monthly_volume 读；数据库不可用时退回读本地 CSV。
    返回列：period_label / month_start / month_end / months / volume / volume_monthly
    """
    df = None
    engine: Engine | None = None

    try:
        engine = build_engine()
        df = pd.read_sql(
            text("""
                SELECT period_label, month_start, month_end, volume
                FROM ads_monthly_volume
                WHERE year = :y
                ORDER BY month_start
            """),
            engine, params={"y": year},
        )
        if df.empty:
            df = None
            print(f"[提示] ads_monthly_volume 里没有 {year} 年数据，改用本地 CSV")
    except Exception as e:
        print(f"[提示] 无法从 MySQL 读取（{type(e).__name__}），改用本地 CSV")
        engine = None

    if df is None:
        csv_path = BASE_DIR / "data" / "processed" / f"monthly_volume_{year}.csv"
        if not csv_path.exists():
            sys.exit(f"既读不到数据库，也找不到 {csv_path.name}")
        df = pd.read_csv(csv_path)
        print(f"[提示] 已从 {csv_path.relative_to(BASE_DIR)} 读取 {len(df)} 行")

    df["months"] = df["month_end"] - df["month_start"] + 1
    df["volume_monthly"] = df["volume"] / df["months"]
    return df.reset_index(drop=True), engine


# ===========================================================================
# ### TODO 1：朴素法（基准线）
# ===========================================================================

def naive_forecast(train: np.ndarray) -> float:
    """
    朴素法（naive / random walk）：用「最近一期的实际值」作为下一期的预测值。

    参数
    ----
    train : np.ndarray，到目前为止的历史值（按时间升序）

    返回
    ----
    float，对下一期的预测值

    提示：train 的最后一个元素就是最近一期。这个函数只有一行。

    ⚠️ 思考题（写在下面注释里，别空着）：
        这个「笨办法」几乎不需要任何计算，为什么任何预测模型都必须先跟它比？
        如果我的模型连朴素法都不如，说明什么？

    # 你的思考：
    朴素法是用这个月的实际值作为下个月的预测值。如果我的模型连朴素法都不如，
    说明它学到的规律还不如「什么都不做」，那这个模型就没有存在的价值。
    """
    # TODO 1: 返回最近一期的实际值作为预测值
    return float(train[-1])


# ===========================================================================
# ### TODO 2：滚动起点验证
# ===========================================================================

def walk_forward(y: np.ndarray, forecaster, name: str) -> pd.DataFrame:
    """
    滚动起点验证（walk-forward validation）。

    逻辑
    ----
    从第 MIN_TRAIN 个位置开始，每一步：
        - 用 y[:k] 训练（前 k 个点）
        - 预测 y[k]（第 k 个点）
        - 记录实际值、预测值、误差
    然后 k 往前走一步，训练窗口扩张，重复到序列末尾。

    对 11 个点、MIN_TRAIN=6 来说，会得到 5 次预测（k = 6,7,8,9,10）。

    参数
    ----
    y         : np.ndarray，完整序列
    forecaster: 接受 train 数组、返回一个预测值的函数（就是上面那几个模型）
    name      : 模型名，写进结果的 model 列

    返回
    ----
    DataFrame，必须包含这些列：
        model        模型名
        step         预测的是第几个点（0-based 索引）
        train_size   这次用了几个点训练
        actual       实际值
        forecast     预测值
        error        实际值 − 预测值
        abs_pct_error 绝对百分比误差（%）= |error| / actual * 100

    ⚠️ 思考题（写在下面注释里）：
        为什么样本只有 11 个点时，不能简单地「前 8 个训练、后 3 个测试」？
        滚动验证相比固定切分，多利用了哪些信息？

    # 你的思考：
               1.用样本后三个数据来测试的话，误差估计没有意义，而且也浪费了前八个数据
               2.固定切分法只切分一次属于静态评估不适合用来评估模型真实预测能力，而滚动验证法更加严谨
    """
    # TODO 2: 写循环，返回结果 DataFrame
    #
    # 骨架已经搭好，你只需要把下面两个 `...` 换成真正的表达式。
    # 别的一行都不用改。
    # 还没填的时候运行会报 TypeError，那是正常的——说明空没填完。
    rows = []
    for k in range(MIN_TRAIN, len(y)):
        train = y[:k]                    # 前 k 个点用来训练
        actual = float(y[k])             # 第 k 个点是"未来"，模型没见过
        pred = forecaster(train)         # 调用传进来的模型
        error = actual - pred            # ✓ 已填：实际值 − 预测值
        pct = abs(error) / actual*100                        # ← 你填：abs(error) / actual * 100
        rows.append({
            "model": name,
            "step": k,
            "train_size": k,
            "actual": actual,
            "forecast": pred,
            "error": error,
            "abs_pct_error": pct,
        })
    return pd.DataFrame(rows)


# ===========================================================================
# ### TODO 3：MAPE
# ===========================================================================

def mape(actual, pred) -> float:
    """
    平均绝对百分比误差（Mean Absolute Percentage Error），返回百分数。

    公式
    ----
        MAPE = mean( |actual − pred| / actual ) * 100

    例：返回 3.82 表示平均误差 3.82%。

    参数
    ----
    actual, pred : 等长的数组（list 或 np.ndarray 都行）

    返回
    ----
    float

    ⚠️ 坑：如果 actual 里有 0，就会除零报错 / 得到 inf。
        必须先把 actual == 0 的位置排除掉再算。
        提示：`mask = actual != 0`，然后用 `actual[mask]`。

    ⚠️ 思考题（写在下面注释里）：
        MAPE 相比 MAE（平均绝对误差）有什么好处？又有什么缺陷？
        提示：如果实际值很小（比如 1 亿件），MAPE 会不会被放大？

    # 你的思考：
    mape的平均绝对误差是相对比例的误差，当实际值很小时mape会被放大。而mae是平均错多少，预测值和真实值的差值平均一样
    """
    # TODO 3: 实现 MAPE，注意处理 actual == 0
    #
    # 骨架已搭好，你只需要把最后那行换成 return 语句。
    # 思路和 TODO 2 里的 pct 完全一样，区别是这里要对整组数据取平均。
    actual = np.asarray(actual, dtype=float)   # 统一转成 numpy 数组
    pred = np.asarray(pred, dtype=float)
    mask = actual != 0                         # 排除 actual 为 0 的位置，避免除零
    if mask.sum() == 0:
        return float("nan")
    # ← 你填：对每个点的绝对百分比误差取平均，再乘 100
    #          提示：用 np.abs、np.mean，并且 actual 和 pred 都要用 [mask] 过滤
    # ✓ 已填（注意：这一行和上面的 if 同级，缩进必须是 4 个空格，不能是 8 个）
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask]) * 100))


# ===========================================================================
# 以下全部已写好，不用改
# ===========================================================================

def moving_average_forecast(train: np.ndarray, window: int = 3) -> float:
    """3 期移动平均：用最近 3 个月的平均值预测下一个月。"""
    w = min(window, len(train))
    return float(np.mean(train[-w:]))


def ses_forecast(train: np.ndarray) -> float:
    """简单指数平滑（只有水平项，不含趋势）。"""
    fit = SimpleExpSmoothing(train, initialization_method="estimated").fit(optimized=True)
    return float(fit.forecast(1)[0])


def holt_forecast(train: np.ndarray) -> float:
    """Holt 线性趋势（水平项 + 趋势项）。"""
    fit = Holt(train, initialization_method="estimated").fit(optimized=True)
    return float(fit.forecast(1)[0])


def setup_cjk_font() -> None:
    for font in ("Microsoft YaHei", "SimHei", "DengXian"):
        plt.rcParams["font.sans-serif"] = [font]
        plt.rcParams["axes.unicode_minus"] = False


def plot_result(df: pd.DataFrame, detail: pd.DataFrame, path: Path) -> None:
    setup_cjk_font()
    fig, ax = plt.subplots(figsize=(11, 5.5))

    x = np.arange(len(df))
    ax.plot(x, df["volume_monthly"], marker="o", linewidth=2,
            label="实际值（月均折算）", color="#1f77b4")

    for model, g in detail.groupby("model"):
        ax.plot(g["step"].to_numpy(), g["forecast"], marker="s",
                linestyle="--", linewidth=1.4, alpha=0.85, label=f"{model} 预测")

    ax.set_xticks(x)
    ax.set_xticklabels(df["period_label"], rotation=45, ha="right")
    ax.set_ylabel("快递业务量（亿件）")
    ax.set_title("2024 年快递业务量：实际值 vs 各模型滚动预测", fontsize=13, pad=12)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=8, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    df, engine = load_series(year=2024)

    print("2024 年月度序列（合并区间按月均折算）：")
    show = df[["period_label", "months", "volume", "volume_monthly"]].copy()
    show.columns = ["区间", "月数", "区间合计(亿件)", "月均(亿件)"]
    print(show.to_string(index=False))

    y = df["volume_monthly"].to_numpy(dtype=float)
    print(f"\n参与建模的样本数：{len(y)}")

    forecasters = {
        "朴素法": naive_forecast,
        "3期移动平均": moving_average_forecast,
        "简单指数平滑": ses_forecast,
        "Holt趋势": holt_forecast,
    }

    # -----------------------------------------------------------------------
    # 冒烟测试：先单独调用每个模型，看它能不能给出一个数。
    #
    # 为什么要这一步？因为 walk_forward 里才会真正调用各个模型，
    # 如果 walk_forward 自己先抛错，你的模型函数根本不会被执行，
    # 于是「没报错」就成了假象——代码没跑过，当然不会报错。
    # 这段保证每个 TODO 改完立刻能得到反馈。
    # -----------------------------------------------------------------------
    print("\n【冒烟测试】用前 6 个点，预测第 7 个点：")
    smoke_ok = True
    for name, fn in forecasters.items():
        try:
            v = fn(y[:MIN_TRAIN])
            print(f"  {name:12} → {v:8.2f}")
        except NotImplementedError:
            print(f"  {name:12} → ⚠️  还没实现")
            smoke_ok = False
        except Exception as e:
            print(f"  {name:12} → ✗  {type(e).__name__}: {e}")
            smoke_ok = False

    if not smoke_ok:
        print("\n提示：上面标 ⚠️ 或 ✗ 的模型还有问题。")
        print("      仍然继续跑滚动验证，但对应模型会缺数据。\n")

    detail = pd.concat(
        [walk_forward(y, fn, name) for name, fn in forecasters.items()],
        ignore_index=True,
    )

    print("\n" + "=" * 74)
    print("滚动验证结果（每一步的预测值与误差）")
    print("=" * 74)
    for name, g in detail.groupby("model"):
        print(f"\n{name}")
        print(g[["step", "actual", "forecast", "abs_pct_error"]]
              .rename(columns={"step": "预测第N点", "actual": "实际值",
                               "forecast": "预测值", "abs_pct_error": "绝对百分比误差%"})
              .round(2).to_string(index=False))

    print("\n" + "=" * 74)
    print("模型对比（同一测试集）")
    print("=" * 74);
    rows = []
    for name, g in detail.groupby("model"):
        a = g["actual"].to_numpy(dtype=float)
        p = g["forecast"].to_numpy(dtype=float)
        err = a - p
        rows.append({
            "model": name,
            "MAE": float(np.nanmean(np.abs(err))),
            # 这里调用你写的 mape()，与 abs_pct_error 列的均值互为校验
            "MAPE(%)": mape(a, p),
            "MAPE_交叉校验": float(np.nanmean(g["abs_pct_error"])),
            "RMSE": float(np.sqrt(np.nanmean(err ** 2))),
        })
    summary = pd.DataFrame(rows).set_index("model").sort_values("MAPE(%)")
    print(summary.round(2).to_string())

    diff = (summary["MAPE(%)"] - summary["MAPE_交叉校验"]).abs().max()
    print(f"\nMAPE 两种算法最大偏差：{diff:.4f} 个百分点 "
          f"({'一致 ✓' if diff < 0.01 else '不一致 ✗ 检查你的 mape()'})")

    best = summary.index[0]
    naive_mape = summary.loc["朴素法", "MAPE(%)"]
    print(f"\n最优模型：{best}  MAPE = {summary.loc[best, 'MAPE(%)']:.2f}%")
    print(f"基准朴素法    MAPE = {naive_mape:.2f}%")

    if best != "朴素法" and summary.loc[best, "MAPE(%)"] < naive_mape:
        print(f"→ 比基准低 {(naive_mape - summary.loc[best, 'MAPE(%)']):.2f} 个百分点")
    else:
        print("→ 没有超过朴素基准。诚实结论是「数据量不足以支持复杂模型」。")

    # 关键观察：MAPE 最好的模型，RMSE 可能是最差的
    mape_best = summary["MAPE(%)"].idxmin()
    rmse_best = summary["RMSE"].idxmin()
    if mape_best != rmse_best:
        print(f"\n⚠️ 注意：MAPE 最优是「{mape_best}」，但 RMSE 最优是「{rmse_best}」。")
        print("   说明有一个模型虽然平均误差小，但存在个别大偏差。")
        print("   RMSE 因为对误差取平方，会放大离群点的影响。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detail.to_csv(OUT_DIR / "forecast_comparison.csv", index=False, encoding="utf-8-sig")
    plot_result(df, detail, OUT_DIR / "forecast_2024.png")

    if engine is not None:
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS ads_forecast_result"))
                summary.reset_index().to_sql("ads_forecast_result", conn, index=False)
            print("\n✓ 汇总已写入 MySQL 表 ads_forecast_result")
        except Exception as e:
            print(f"\n⚠️ 写入 MySQL 失败（{type(e).__name__}），已跳过")
    else:
        print("\nℹ️ 数据库不可用，跳过写库")

    print("✓ 明细已导出 output/forecast_comparison.csv")
    print("✓ 图表已导出 output/forecast_2024.png")


if __name__ == "__main__":
    main()
