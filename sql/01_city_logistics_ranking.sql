-- ===========================================================================
-- 中国城市物流枢纽分级与帕累托分析
-- 目的：用真实可跑的 SQL 展示窗口函数、CTE、累计占比等面试高频技能
-- 数据库：MySQL 官方示例库 world
-- 运行：USE world; SOURCE sql/01_city_logistics_ranking.sql;
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 查询 1：基础排名 —— ROW_NUMBER / RANK / DENSE_RANK 的区别
-- 面试常问：这三个函数有什么不同？同分时表现如何？
-- ---------------------------------------------------------------------------
SELECT
    Name                                                AS 城市,
    Population                                          AS 人口数,
    ROW_NUMBER() OVER (ORDER BY Population DESC)        AS 行号,
    RANK()       OVER (ORDER BY Population DESC)        AS 排名_跳跃,
    DENSE_RANK() OVER (ORDER BY Population DESC)        AS 排名_密集,
    ROUND(
        PERCENT_RANK() OVER (ORDER BY Population DESC) * 100, 2
    )                                                   AS 百分位
FROM city
WHERE CountryCode = 'CHN'
ORDER BY Population DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- 查询 2：帕累托分析（80/20 法则）
-- 业务含义：排名前多少的城市，贡献了全国 80% 的人口（可类比为业务量）？
-- 这是供应链数据分析里最常被问到的分析之一
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT
        Name                                                AS 城市,
        Population                                          AS 人口数,
        SUM(Population) OVER ()                             AS 全国总人口,
        SUM(Population) OVER (ORDER BY Population DESC
                              ROWS BETWEEN UNBOUNDED PRECEDING
                                       AND CURRENT ROW)     AS 累计人口
    FROM city
    WHERE CountryCode = 'CHN'
)
SELECT
    ROW_NUMBER() OVER (ORDER BY 人口数 DESC)                 AS 排名,
    城市,
    人口数,
    ROUND(累计人口 / 全国总人口 * 100, 2)                    AS 累计占比百分比,
    CASE
        WHEN 累计人口 / 全国总人口 <= 0.80 THEN '贡献 80% 的关键城市'
        ELSE '长尾城市'
    END                                                     AS 分层
FROM ranked
ORDER BY 排名;


-- ---------------------------------------------------------------------------
-- 查询 3：用 NTILE 做物流枢纽分级（等频分箱）
-- 相比用固定阈值硬编码，NTILE 按分位数自动分级，更适合做分层运营
-- ---------------------------------------------------------------------------
SELECT
    Name                                        AS 城市,
    Population                                  AS 人口数,
    CONCAT('T', NTILE(4) OVER (ORDER BY Population DESC))  AS 枢纽层级,
    CASE NTILE(4) OVER (ORDER BY Population DESC)
        WHEN 1 THEN 'A级 核心枢纽'
        WHEN 2 THEN 'B级 区域中心'
        WHEN 3 THEN 'C级 配送站点'
        ELSE        'D级 末端网点'
    END                                         AS 层级说明
FROM city
WHERE CountryCode = 'CHN'
ORDER BY Population DESC;


-- ---------------------------------------------------------------------------
-- 查询 4：分省汇总 + 组内排名
-- 展示 GROUP BY 与窗口函数配合：每个省内人口最多的城市
-- ---------------------------------------------------------------------------
WITH cn_city AS (
    SELECT
        c.Name          AS 城市,
        c.Population    AS 人口数,
        c.District      AS 省区
    FROM city c
    WHERE c.CountryCode = 'CHN'
),
ranked AS (
    SELECT
        省区,
        城市,
        人口数,
        ROW_NUMBER() OVER (PARTITION BY 省区 ORDER BY 人口数 DESC) AS 省内排名,
        SUM(人口数)  OVER (PARTITION BY 省区)                      AS 省内总人口
    FROM cn_city
)
SELECT
    省区,
    城市,
    人口数,
    省内排名,
    ROUND(人口数 / 省内总人口 * 100, 2) AS 占全省比重
FROM ranked
WHERE 省内排名 = 1
ORDER BY 人口数 DESC;


-- ---------------------------------------------------------------------------
-- 查询 5：层级汇总报表（供 Power BI 直接取数）
-- ---------------------------------------------------------------------------
SELECT
    CASE
        WHEN Population >= 5000000 THEN 'A级（核心枢纽）'
        WHEN Population >= 3000000 THEN 'B级（区域中心）'
        WHEN Population >= 1000000 THEN 'C级（配送站点）'
        ELSE                            'D级（末端网点）'
    END                     AS 物流等级,
    COUNT(*)                AS 城市数量,
    SUM(Population)         AS 覆盖人口,
    ROUND(AVG(Population))  AS 平均人口
FROM city
WHERE CountryCode = 'CHN'
GROUP BY 物流等级
ORDER BY 覆盖人口 DESC;
