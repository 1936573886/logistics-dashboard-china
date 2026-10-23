-- ===========================================================================
-- 中国快递物流数据仓库 —— 建表与分层视图
-- ===========================================================================
-- 数据源：国家邮政局「邮政行业运行情况」系列公报（官方发布，可逐条溯源）
-- 分层：   ODS 原始层 → DWD 明细层 → DWS 汇总层 → ADS 应用层
-- 运行：   python scripts/load_mysql.py 会自动执行本文件
-- 特性：   全部语句幂等，可反复执行
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 维度：省份 → 三大地带（国家统计局标准划分）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_region (
    province  VARCHAR(20)  NOT NULL PRIMARY KEY COMMENT '省份（不含"省/市/自治区"后缀）',
    region    VARCHAR(10)  NOT NULL COMMENT '东部/中部/西部',
    region_order TINYINT   NOT NULL COMMENT '排序用'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='省份区域维表';

INSERT INTO dim_region (province, region, region_order) VALUES
    ('北京','东部',1),('天津','东部',1),('河北','东部',1),('辽宁','东部',1),
    ('上海','东部',1),('江苏','东部',1),('浙江','东部',1),('福建','东部',1),
    ('山东','东部',1),('广东','东部',1),('海南','东部',1),
    ('山西','中部',2),('吉林','中部',2),('黑龙江','中部',2),('安徽','中部',2),
    ('江西','中部',2),('河南','中部',2),('湖北','中部',2),('湖南','中部',2),
    ('内蒙古','西部',3),('广西','西部',3),('重庆','西部',3),('四川','西部',3),
    ('贵州','西部',3),('云南','西部',3),('西藏','西部',3),('陕西','西部',3),
    ('甘肃','西部',3),('青海','西部',3),('宁夏','西部',3),('新疆','西部',3)
ON DUPLICATE KEY UPDATE region=VALUES(region), region_order=VALUES(region_order);


-- ===========================================================================
-- ODS：原始层 —— 与源数据字段一一对应，不做业务加工
-- ===========================================================================

CREATE TABLE IF NOT EXISTS ods_spb_national (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    period_label   VARCHAR(32)   COMMENT '报告期标签，如 2024年1-9月',
    period_type    VARCHAR(16)   COMMENT '月度/月度区间/半年度/季度累计/年度',
    period_year    SMALLINT,
    period_month   TINYINT       COMMENT '报告期结束月份',
    publish_date   DATE,
    source_url     VARCHAR(255)  COMMENT '原始公报 URL，可溯源',
    metric         VARCHAR(32)   COMMENT '指标名',
    raw_unit       VARCHAR(16)   COMMENT '原始单位（万件/亿件/万元/亿元）',
    unit           VARCHAR(16)   COMMENT '标准单位（亿件/亿元）',
    cumulative     DECIMAL(18,6) COMMENT '累计值',
    current        DECIMAL(18,6) COMMENT '当月值',
    yoy_cumulative DECIMAL(8,2)  COMMENT '累计同比%',
    yoy_current    DECIMAL(8,2)  COMMENT '当月同比%'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全国汇总（ODS）';

CREATE TABLE IF NOT EXISTS ods_spb_province (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    period_label VARCHAR(32),
    period_type  VARCHAR(16),
    period_year  SMALLINT,
    period_month TINYINT,
    publish_date DATE,
    source_url   VARCHAR(255),
    province     VARCHAR(20),
    volume_yi    DECIMAL(18,6) COMMENT '快递业务量（亿件）',
    revenue_yi   DECIMAL(18,6) COMMENT '快递业务收入（亿元）',
    volume_yoy   DECIMAL(8,2)  COMMENT '业务量同比%',
    revenue_yoy  DECIMAL(8,2)  COMMENT '收入同比%'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分省数据（ODS）';

CREATE TABLE IF NOT EXISTS ods_spb_city (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    period_label VARCHAR(32),
    period_type  VARCHAR(16),
    period_year  SMALLINT,
    period_month TINYINT,
    publish_date DATE,
    source_url   VARCHAR(255),
    city         VARCHAR(32),
    rank_volume  SMALLINT   COMMENT '按业务量排名',
    rank_revenue SMALLINT   COMMENT '按收入排名',
    volume_yi    DECIMAL(18,6),
    revenue_yi   DECIMAL(18,6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='城市 TOP50（ODS）';


-- ===========================================================================
-- DWD：明细层 —— 类型规范、口径统一、派生度量
-- ===========================================================================

-- 报告期维度（去重后的期间主数据）
CREATE OR REPLACE VIEW dwd_period AS
SELECT
    period_label,
    MIN(period_type)  AS period_type,
    MIN(period_year)  AS period_year,
    MIN(period_month) AS period_month,
    MIN(publish_date) AS publish_date,
    MIN(source_url)   AS source_url
FROM (
    SELECT period_label, period_type, period_year, period_month, publish_date, source_url
    FROM ods_spb_city
    UNION ALL
    SELECT period_label, period_type, period_year, period_month, publish_date, source_url
    FROM ods_spb_province
) t
GROUP BY period_label;

-- 城市明细：补单票收入（元/件）
CREATE OR REPLACE VIEW dwd_city AS
SELECT
    c.period_label,
    c.period_year,
    c.period_month,
    c.city,
    c.rank_volume,
    c.rank_revenue,
    c.volume_yi,
    c.revenue_yi,
    -- 单票收入：亿元 / 亿件 = 元/件
    ROUND(c.revenue_yi / NULLIF(c.volume_yi, 0), 4) AS revenue_per_piece,
    c.source_url
FROM ods_spb_city c;

-- 分省明细：补区域与单票收入
-- 注意：官方分省表里第一行是「全国」汇总，不是省份，必须排除，
--       否则会被当成一个省份参与排名。全国口径请用 ods_spb_national。
CREATE OR REPLACE VIEW dwd_province AS
SELECT
    p.period_label,
    p.period_year,
    p.period_month,
    p.province,
    r.region,
    r.region_order,
    p.volume_yi,
    p.revenue_yi,
    ROUND(p.revenue_yi / NULLIF(p.volume_yi, 0), 4) AS revenue_per_piece,
    p.volume_yoy,
    p.revenue_yoy,
    p.source_url
FROM ods_spb_province p
LEFT JOIN dim_region r ON r.province = p.province
WHERE p.province <> '全国';


-- ===========================================================================
-- DWS：汇总层 —— 按分析主题聚合
-- ===========================================================================

-- 城市集中度：每个报告期，全国 TOP N 城市占全部 TOP50 城市的比重
CREATE OR REPLACE VIEW dws_city_concentration AS
WITH base AS (
    SELECT
        period_label,
        city,
        volume_yi,
        revenue_yi,
        SUM(volume_yi)  OVER (PARTITION BY period_label) AS total_volume,
        SUM(revenue_yi) OVER (PARTITION BY period_label) AS total_revenue
    FROM dwd_city
    WHERE volume_yi IS NOT NULL
)
SELECT
    period_label,
    COUNT(*)                                          AS city_cnt,
    ROUND(SUM(volume_yi), 2)                          AS top50_volume,
    ROUND(SUM(revenue_yi), 2)                         AS top50_revenue,
    -- CR5 / CR10：前 5、前 10 城市业务量占比
    ROUND(SUM(CASE WHEN rank_volume <= 5  THEN volume_yi END)
          / NULLIF(MAX(total_volume), 0) * 100, 2)    AS cr5_pct,
    ROUND(SUM(CASE WHEN rank_volume <= 10 THEN volume_yi END)
          / NULLIF(MAX(total_volume), 0) * 100, 2)    AS cr10_pct
FROM (
    SELECT d.*, b.total_volume, b.total_revenue
    FROM dwd_city d
    JOIN base b ON b.period_label = d.period_label AND b.city = d.city
) x
GROUP BY period_label;

-- 分省区域结构：东部/中部/西部 的业务量与收入占比
CREATE OR REPLACE VIEW dws_region_share AS
WITH agg AS (
    SELECT
        period_label,
        region,
        SUM(volume_yi)  AS region_volume,
        SUM(revenue_yi) AS region_revenue
    FROM dwd_province
    WHERE region IS NOT NULL
    GROUP BY period_label, region
)
SELECT
    a.period_label,
    a.region,
    ROUND(a.region_volume, 2)  AS volume_yi,
    ROUND(a.region_revenue, 2) AS revenue_yi,
    ROUND(a.region_volume  / NULLIF(t.total_vol, 0) * 100, 2) AS volume_share_pct,
    ROUND(a.region_revenue / NULLIF(t.total_rev, 0) * 100, 2) AS revenue_share_pct
FROM agg a
JOIN (
    SELECT period_label, SUM(volume_yi) AS total_vol, SUM(revenue_yi) AS total_rev
    FROM dwd_province
    WHERE region IS NOT NULL
    GROUP BY period_label
) t ON t.period_label = a.period_label;


-- ===========================================================================
-- ADS：应用层 —— 直接供 Power BI / Streamlit 取数
-- ===========================================================================

-- 应用表 1：城市物流网络（含帕累托累计占比与网络层级）
CREATE OR REPLACE VIEW ads_city_network AS
WITH ranked AS (
    SELECT
        period_label,
        period_year,
        period_month,
        city,
        rank_volume,
        rank_revenue,
        volume_yi,
        revenue_yi,
        revenue_per_piece,
        SUM(volume_yi) OVER (PARTITION BY period_label) AS period_total,
        SUM(volume_yi) OVER (
            PARTITION BY period_label
            ORDER BY rank_volume
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_volume,
        PERCENT_RANK() OVER (PARTITION BY period_label ORDER BY volume_yi DESC) AS pct_rank
    FROM dwd_city
    WHERE volume_yi IS NOT NULL
)
SELECT
    period_label,
    period_year,
    period_month,
    city,
    rank_volume,
    rank_revenue,
    volume_yi,
    revenue_yi,
    revenue_per_piece,
    ROUND(volume_yi / NULLIF(period_total, 0) * 100, 3) AS volume_share_pct,
    ROUND(running_volume / NULLIF(period_total, 0) * 100, 2) AS pareto_cum_pct,
    CASE
        WHEN pct_rank <= 0.10 THEN 'A级 核心枢纽'
        WHEN pct_rank <= 0.30 THEN 'B级 区域中心'
        WHEN pct_rank <= 0.60 THEN 'C级 重要节点'
        ELSE                      'D级 一般节点'
    END AS network_level
FROM ranked
ORDER BY period_label, rank_volume;

-- 应用表 2：全国月度趋势
CREATE OR REPLACE VIEW ads_national_trend AS
SELECT
    period_label,
    period_type,
    period_year,
    period_month,
    metric,
    unit,
    cumulative,
    current,
    yoy_cumulative,
    yoy_current
FROM ods_spb_national
ORDER BY period_year, period_month, metric;

-- 应用表 3：分省对比（含区域）
CREATE OR REPLACE VIEW ads_province_compare AS
SELECT
    period_label,
    period_year,
    period_month,
    province,
    region,
    volume_yi,
    revenue_yi,
    revenue_per_piece,
    volume_yoy,
    revenue_yoy,
    RANK() OVER (PARTITION BY period_label ORDER BY volume_yi DESC) AS volume_rank
FROM dwd_province
ORDER BY period_label, volume_rank;
