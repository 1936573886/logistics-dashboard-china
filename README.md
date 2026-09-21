## 项目简介
基于中国主要城市物流数据，使用 Power BI 构建的交互式看板，展示物流网络分布与运输流向。
## 看板预览
下图为 Power BI 看板的整体界面，展示了物流网络分布与运输流向的可视化分析。
<img width="2196" height="890" alt="屏幕截图 2026-09-21 214316" src="https://github.com/user-attachments/assets/62aac850-2438-4465-98d4-1cdca12b1b3d" />
<img width="2194" height="886" alt="屏幕截图 2026-09-21 174343" src="https://github.com/user-attachments/assets/c0f2bf27-fe5f-4bc4-95c3-86f2b82df9ba" />
<img width="2198" height="894" alt="屏幕截图 2026-09-21 214329" src="https://github.com/user-attachments/assets/411435a9-6613-46d6-b375-f786b38c5285" />
## 文件说明
- `logistics_network_dashboard.pbix`：Power BI 交互式看板源文件
- `logistics_analysis.py`：数据清洗与预处理脚本（Pandas）
- `物流分级报表_2026-08-28.xlsx`：原始数据与分级报表
## 数据处理流程
1. 使用 Pandas 读取原始 Excel 数据
2. 清洗缺失值与异常值
3. 按城市和运输方式进行聚合与分级
4. 输出清洗后的数据供 Power BI 使用
## 文件说明
Power BI、数据可视化、物流网络分析
