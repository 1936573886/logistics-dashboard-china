# logistics-dashboard-china
中国城市物流网络可视化看板 | Power BI
# 中国城市物流网络可视化看板

## 项目简介
基于中国主要城市物流数据，使用 Power BI 构建的交互式看板，展示物流网络分布与运输流向。

## 文件说明
- `logistics.pbix`：Power BI 源文件
- `data/`：原始数据

## 技能
Power BI、数据可视化、物流网络分析
## 文件说明
- `logistics_network_dashboard.pbix`：Power BI 交互式看板源文件
- `logistics_analysis.py`：数据清洗与预处理脚本（Pandas）
- `物流分级报表_2026-08-28.xlsx`：原始数据与分级报表
## 数据处理流程
1. 使用 Pandas 读取原始 Excel 数据
2. 清洗缺失值与异常值
3. 按城市和运输方式进行聚合与分级
4. 输出清洗后的数据供 Power BI 使用
