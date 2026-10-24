"""
抓取国家邮政局「邮政行业运行情况」公报 → 三张结构化 CSV
==========================================================

产出
----
data/raw/spb_national.csv   全国汇总（报告期 × 指标）
data/raw/spb_province.csv   分省数据（报告期 × 31 省 × 业务量/收入）
data/raw/spb_city.csv       城市 TOP50（报告期 × 城市 × 业务量/收入）

数据来源
--------
国家邮政局官网 https://www.spb.gov.cn 「邮政行业运行情况」系列公报。
全部为官方发布口径，每条记录保留 source_url 可回溯核对。

单位统一
--------
官方原表混用「万件 / 万元 / 亿件 / 亿元」。本脚本统一换算为：
    业务量 → 亿件       收入 → 亿元
换算关系：1 亿 = 10000 万。

已知局限
--------
1. 报告期不规整（月度 / 半年 / 年度混排），用 period_type 标注
2. 2024 年之后的公报把城市表改成了图片，只有 2021–2023 的页面带 HTML 城市表
3. 官网列表页分页由 JS 驱动，无法一次性枚举，因此覆盖率取决于种子 URL
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
BASE_URL = "https://www.spb.gov.cn"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 已知可访问的公报页面（人工核实）
# 说明：官网列表页的分页由 JS 驱动，无法程序化枚举，
#       因此这里维护的是通过站内搜索 + 信息公开索引逐一核实过的 URL 清单。
#       新增 URL 时请先手动打开确认：页面存在，且正文含「邮政行业运行情况」。
#
# 注：各省子站（yn / jx / fj.spb.gov.cn 等）会转载同一批公报，内容重复，
#     为避免脏数据不抓取。
SEED_URLS = [
    # ---- 年度 ----
    "/gjyzj/c100015/c100016/202101/2ef764639616407d82cba2aa6f4ae74d.shtml",  # 2020年
    "/gjyzj/c100015/c100016/202201/d278cb7483544a729e394c17e387a7e6.shtml",  # 2021年
    "/gjyzj/c200039/202304/e4a775da6c074576a40f131e1330d91d.shtml",          # 2022年
    "/gjyzj/2022lhbjzlkt/202403/22e465692d4746f8ae89c7beae8b404e.shtml",     # 2023年
    "/gjyzj/c100276/202501/460d02f2e54c4d0ebbba3a4f431d0042.shtml",          # 2024年
    "/gjyzj/c100015/c100016/202601/e6e402458627430daca67f9354c179ed.shtml",  # 2025年
    # ---- 季度 / 半年度 ----
    "/gjyzj/c200045/202004/7778c3ef3d784e8391371294f637027f.shtml",          # 2020年一季度
    "/gjyzj/c200045/202108/ed4a1e698fa84c7fbf297310227d53a5.shtml",          # 2021年上半年
    "/gjyzj/c100015/c100016/202110/90a2b3fa247043bcb4afa27c9d66aedc.shtml",  # 2021年前三季度
    "/gjyzj/c100276/202308/969261ace8a14315a843423bf825adb6.shtml",          # 2023年上半年
    "/gjyzj/c100015/c100016/202407/c21604618b0342efa51e6b7c5c95d358.shtml",  # 2024年上半年
    "/gjyzj/c100276/202410/d342f99765a04e71b7fda798e185f1ab.shtml",          # 2024年前三季度
    # ---- 月度 ----
    "/gjyzj/c200045/202102/9ce7faa668fd4034853e330dc0e72810.shtml",          # 2021年1月
    "/gjyzj/c200045/202108/cf289a051013453cb2d6eefcb6cb4585.shtml",          # 2021年7月
    "/gjyzj/c200045/202110/02c51bd4c9cd4b2a8e521509d48b4391.shtml",          # 2021年9月
    "/gjyzj/c100015/c100016/202209/190d0392f63c4e62a9bcc458ae5562f3.shtml",  # 2022年8月
    "/gjyzj/c100015/c100016/202211/fef4774760f44e9e93fadfa525035595.shtml",  # 2022年10月
    "/gjyzj/c100276/202410/b296f727c16a494387269b964b38e3e8.shtml",          # 2024年1-9月
    "/gjyzj/c100015/c100016/202609/5da542159e1449b4ba8334b6054e0718.shtml",  # 2026年1-8月
    # ---- 统计公报 ----
    "/gjyzj/c100277/202605/639737d297434c83ab880b0a739bfb29.shtml",          # 2025年统计公报解读
    # ---- 2024 年（用于构建连续月度序列）----
    "/gjyzj/c100015/c100016/202404/606fd6a6318e4055b86a06aa2d7cb7a6.shtml",  # 2024年一季度
    "/gjyzj/c100015/c100016/202405/1b2fc1cd9a174ae38596f426bc65f11f.shtml",  # 2024年4月
    "https://www.gov.cn/lianbo/bumen/202406/content_6957791.htm",             # 2024年5月（中国政府网转载）
    "/gjyzj/c100015/c100016/202408/b9ead4244d384c4b8f940c6815aee683.shtml",  # 2024年7月
    "/gjyzj/c100015/c100016/202409/cdc064712a2e43e8899fdd04b398d66d.shtml",  # 2024年8月
    "/gjyzj/c100015/c100016/202411/cb8e6841781c41d59bab21365b0ed452.shtml",  # 2024年1-10月
    "/gjyzj/c100015/c100016/202412/213132b50e1c458284e07bfde40a1d72.shtml",  # 2024年1-11月
]


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def clean(x) -> str:
    s = re.sub(r"<[^>]+>", "", str(x))
    s = s.replace("\u3000", " ").replace("\xa0", " ").replace(",", "")
    return re.sub(r"\s+", " ", s).strip()


def to_num(x) -> float | None:
    s = clean(x)
    if s in ("", "-", "—", "…", "nan", "None"):
        return None
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 报告期识别
# ---------------------------------------------------------------------------

PERIOD_RE = re.compile(
    r"(20\d{2})\s*年\s*"
    r"(?:(\d{1,2})\s*月份?(?!\d)"        # 8月份
    r"|(1\s*[-—]\s*\d{1,2}\s*月)"        # 1-8月
    r"|(上半年|下半年)"                   # 上半年
    r"|(前三季度)"                       # 前三季度
    r"|([一二三四])\s*季度"               # 一季度
    r"|(全年))?"                         # 全年
)

# 「X季度」→ 该季度结束月份
QUARTER_END = {"一": 3, "二": 6, "三": 9, "四": 12}


def parse_period(html: str) -> tuple[str, str, int, int] | None:
    """
    从页面正文识别报告期。兼容以下标题写法：
        国家邮政局公布2023年8月邮政行业运行情况
        国家邮政局公布2024年1-9月邮政行业运行情况
        国家邮政局公布2020年一季度邮政行业运行情况
        国家邮政局关于2021年上半年行业经济运行情况的通报
        国家邮政局公布2022年邮政行业运行情况      ← 无月份词，视为年度
    """
    text = clean(html)
    for m in re.finditer(r"(?:邮政)?行业(?:经济)?运行情况", text):
        window = text[max(0, m.start() - 40):m.start()]
        # 取窗口中最后一个年份，确保取到离标题最近的那个
        matches = list(PERIOD_RE.finditer(window))
        if not matches:
            continue
        ym = matches[-1]
        year = int(ym.group(1))
        g2, g3, g4, g5, g6, g7 = (ym.group(2), ym.group(3), ym.group(4),
                                  ym.group(5), ym.group(6), ym.group(7))

        if g2:
            return f"{year}年{int(g2)}月", "月度", year, int(g2)
        if g3:
            # g3 形如 "1-9月" 或 "1—9月"，要取连字符后面的月份
            mm = int(re.search(r"[-—]\s*(\d{1,2})", g3).group(1))
            return f"{year}年1-{mm}月", "月度区间", year, mm
        if g4:
            if g4 == "下半年":
                return f"{year}年下半年", "半年累计", year, 12
            return f"{year}年上半年", "半年度", year, 6
        if g5:
            return f"{year}年前三季度", "季度累计", year, 9
        if g6:
            # 「一季度」这类，必须单独处理：
            # 否则会掉进下面的「无期间词 → 年度」分支，
            # 把一季度数据错标成全年，进而和真正的全年数据合并到一起。
            end_m = QUARTER_END[g6]
            return f"{year}年{g6}季度", "季度", year, end_m
        # 无任何期间词 → 年度报告
        return f"{year}年全年", "年度", year, 12
    return None


# ---------------------------------------------------------------------------
# 表格解析
# ---------------------------------------------------------------------------

def find_tables(html: str) -> list[pd.DataFrame]:
    try:
        return pd.read_html(io.StringIO(html))
    except ValueError:
        return []


def classify(t: pd.DataFrame) -> str | None:
    """判断这张表属于哪一类。"""
    head = " ".join(clean(v) for v in t.head(2).values.flatten() if pd.notna(v))
    flat = " ".join(clean(v) for v in t.values.flatten() if pd.notna(v))
    if "指标名称" in head:
        return "national"
    if "排名" in head and "城市" in head:
        return "city_income" if "业务收入" in head else "city_volume"
    if "快递业务量" in flat and ("北京" in flat or "广东" in flat) and "全国" in flat:
        return "province"
    return None


METRIC_MAP = {
    "一、邮政行业业务收入": "行业业务收入",
    "1、快递业务": None,          # 按单位区分收入 / 量
    "2、邮政普遍服务业务": None,
    "二、邮政行业寄递业务量": "寄递业务量",
    "其中：同城": "同城快递量",
    "异地": "异地快递量",
    "国际/港澳台": "国际快递量",
}


def normalize_amount(value: float | None, unit: str) -> float | None:
    """把万件/万元 换算成 亿件/亿元。"""
    if value is None:
        return None
    if unit.startswith("万"):
        return round(value / 10000, 6)
    return round(value, 6)


def resolve_metric(label: str, unit: str) -> tuple[str, str] | None:
    """由 (标签, 原始单位) 推断标准指标名和标准单位。"""
    is_volume = "件" in unit
    canon_unit = "亿件" if is_volume else "亿元" if "元" in unit else ""

    if label == "1、快递业务":
        return ("快递业务量" if is_volume else "快递业务收入"), canon_unit
    if label == "2、邮政普遍服务业务":
        return ("普遍服务业务量" if is_volume else "普遍服务业务收入"), canon_unit
    name = METRIC_MAP.get(label)
    if name:
        return name, canon_unit
    return None


def parse_national(t: pd.DataFrame, key: dict) -> list[dict]:
    """
    全国汇总表 → 长表。
    兼容两种列结构：
        6 列：[指标, 单位, 累计, 当月, 同比累计, 同比当月]
        4 列：[指标, 单位, 当月份值, 同比]        （1 月份的公报没有累计列）
    """
    out = []
    for _, row in t.iterrows():
        vals = row.tolist()
        if len(vals) < 4:
            continue
        label, unit = clean(vals[0]), clean(vals[1])
        if not label or unit in ("单位", "指标名称", ""):
            continue
        resolved = resolve_metric(label, unit)
        if resolved is None:
            continue
        metric, canon_unit = resolved

        if len(vals) >= 6:
            nums = [to_num(v) for v in vals[2:6]]
            cum, cur, yoy_cum, yoy_cur = nums
        else:
            cur = to_num(vals[2])
            yoy_cur = to_num(vals[3])
            cum, yoy_cum = None, None

        out.append({
            **key, "metric": metric, "raw_unit": unit, "unit": canon_unit,
            "cumulative": normalize_amount(cum, unit),
            "current": normalize_amount(cur, unit),
            "yoy_cumulative": yoy_cum, "yoy_current": yoy_cur,
        })
    return out


def header_units(t: pd.DataFrame) -> tuple[float, float]:
    """
    从表头识别单位，返回 (业务量除数, 收入除数)。
    官方公报在不同年份混用「万件/万元」和「亿件/亿元」，
    例如 2021 年是万件、2024 年改成亿件，必须先识别再换算。
    """
    header = " ".join(clean(v) for v in t.head(2).values.flatten() if pd.notna(v))
    vol_div = 10000.0 if "万件" in header else 1.0
    rev_div = 10000.0 if "万元" in header else 1.0
    return vol_div, rev_div


def parse_province(t: pd.DataFrame, key: dict) -> list[dict]:
    """分省表（5 列）→ 长表，统一换算为亿件 / 亿元。"""
    vol_div, rev_div = header_units(t)
    out = []
    for _, row in t.iterrows():
        vals = row.tolist()
        if len(vals) < 5:
            continue
        region = clean(vals[0])
        if region in ("单位", "", "nan"):
            continue
        vol, vol_yoy = to_num(vals[1]), to_num(vals[2])
        inc, inc_yoy = to_num(vals[3]), to_num(vals[4])
        out.append({
            **key, "province": region,
            "volume_yi": round(vol / vol_div, 6) if vol is not None else None,
            "revenue_yi": round(inc / rev_div, 6) if inc is not None else None,
            "volume_yoy": vol_yoy, "revenue_yoy": inc_yoy,
        })
    return out


def parse_city(t: pd.DataFrame, key: dict, kind: str) -> list[dict]:
    """城市 TOP50 双栏表 → 长表，统一换算为亿件 / 亿元。"""
    vol_div, rev_div = header_units(t)
    div = vol_div if kind == "city_volume" else rev_div
    out = []
    value_col = "volume_yi" if kind == "city_volume" else "revenue_yi"
    for _, row in t.iterrows():
        vals = row.tolist()
        if len(vals) < 6:
            continue
        for rank_i, city_i, val_i in ((0, 1, 2), (3, 4, 5)):
            city = clean(vals[city_i])
            val = to_num(vals[val_i])
            if not city or city in ("城市", "") or val is None:
                continue
            city = re.sub(r"（.*?）|\(.*?\)", "", city).strip()
            if not city.endswith("市"):
                city += "市"
            out.append({**key, "rank": to_num(vals[rank_i]),
                        "city": city, value_col: round(val / div, 6)})
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_page(html: str, url: str) -> dict | None:
    period = parse_period(html)
    if period is None:
        return None
    label, ptype, year, month = period

    md = re.search(r"日期[：:]\s*(\d{4}-\d{2}-\d{2})", clean(html))
    key = {"period_label": label, "period_type": ptype, "period_year": year,
           "period_month": month, "publish_date": md.group(1) if md else "",
           "source_url": url}

    result = {"national": [], "province": [], "city_volume": [], "city_income": []}
    for t in find_tables(html):
        kind = classify(t)
        if kind == "national":
            result["national"] += parse_national(t, key)
        elif kind == "province":
            result["province"] += parse_province(t, key)
        elif kind == "city_volume":
            result["city_volume"] += parse_city(t, key, "city_volume")
        elif kind == "city_income":
            result["city_income"] += parse_city(t, key, "city_income")

    if not any(result.values()):
        return None
    return {"key": key, **result}


def merge_city(rows: list[dict]) -> list[dict]:
    """
    城市表里「业务量」和「业务收入」原本是两张独立的 TOP50 表，
    合并成「每个报告期 × 每个城市 一行」，同时保留两列数值。
    """
    merged: dict[tuple, dict] = {}
    for r in rows:
        k = (r["period_label"], r["city"])
        cur = merged.setdefault(k, {
            "period_label": r["period_label"],
            "period_type": r["period_type"],
            "period_year": r["period_year"],
            "period_month": r["period_month"],
            "publish_date": r["publish_date"],
            "source_url": r["source_url"],
            "city": r["city"],
            "rank_volume": None, "rank_revenue": None,
            "volume_yi": None, "revenue_yi": None,
        })
        if r.get("volume_yi") is not None:
            cur["volume_yi"] = r["volume_yi"]
            cur["rank_volume"] = r.get("rank")
        if r.get("revenue_yi") is not None:
            cur["revenue_yi"] = r["revenue_yi"]
            cur["rank_revenue"] = r.get("rank")
    return list(merged.values())


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    national, province, city = [], [], []
    ok, skipped = 0, []
    # 记录「报告期 → 来源 URL」，用于检测同一报告期被两个不同页面命中
    period_sources: dict[str, set[str]] = {}

    for rel in SEED_URLS:
        # 允许种子写成相对路径（默认挂到国家邮政局域名）或完整 URL（如政府网转载）
        url = rel if rel.startswith("http") else BASE_URL + rel
        try:
            html = fetch(url)
        except Exception as e:
            skipped.append((url, f"{type(e).__name__}"))
            continue
        page = parse_page(html, url)
        if not page:
            skipped.append((url, "无法识别报告期或表格"))
            if args.verbose:
                print(f"[SKIP] {url}")
            continue
        ok += 1
        period_sources.setdefault(page["key"]["period_label"], set()).add(url)
        national += page["national"]
        province += page["province"]
        city += page["city_volume"] + page["city_income"]
        if args.verbose:
            print(f"[OK] {page['key']['period_label']:16} "
                  f"全国{len(page['national']):>2}行  "
                  f"分省{len(page['province']):>2}行  "
                  f"城市{len(page['city_volume']) + len(page['city_income']):>3}行")
        time.sleep(0.6)

    KEY = ["period_label", "period_type", "period_year", "period_month",
           "publish_date", "source_url"]

    city = merge_city(city)

    write_csv(RAW_DIR / "spb_national.csv", national,
              KEY + ["metric", "raw_unit", "unit", "cumulative", "current",
                     "yoy_cumulative", "yoy_current"])
    write_csv(RAW_DIR / "spb_province.csv", province,
              KEY + ["province", "volume_yi", "revenue_yi", "volume_yoy", "revenue_yoy"])
    write_csv(RAW_DIR / "spb_city.csv", city,
              KEY + ["city", "rank_volume", "rank_revenue", "volume_yi", "revenue_yi"])

    print(f"\n成功解析 {ok} / {len(SEED_URLS)} 篇")
    print(f"  全国汇总 {len(national):>4} 行  → data/raw/spb_national.csv")
    print(f"  分省数据 {len(province):>4} 行  → data/raw/spb_province.csv")
    print(f"  城市数据 {len(city):>4} 行  → data/raw/spb_city.csv")

    # 同一报告期被多个页面命中 = 数据可能被覆盖，必须人工确认
    dupes = {k: v for k, v in period_sources.items() if len(v) > 1}
    if dupes:
        print(f"\n⚠️  发现 {len(dupes)} 个报告期被多个页面命中（数据可能互相覆盖）：")
        for label, urls in dupes.items():
            print(f"  {label}")
            for u in urls:
                print(f"    - {u}")

    if skipped:
        print(f"\n未解析 {len(skipped)} 篇：")
        for u, why in skipped:
            print(f"  {why:22} {u}")

    if city:
        periods = sorted({r["period_label"] for r in city})
        cities = sorted({r["city"] for r in city})
        print(f"\n城市数据覆盖 {len(periods)} 个报告期、{len(cities)} 个城市")
        print("报告期:", ", ".join(periods))


if __name__ == "__main__":
    main()
