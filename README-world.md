# 中国城市物流网络可视化看板

基于中国主要城市数据，用 **Python (pandas) + MySQL + Power BI** 构建的物流网络分级与流向分析看板。

## 看板预览

Power BI 看板整体界面，展示了物流网络分布与运输流向的可视化分析。

![看板预览 1](https://github.com/user-attachments/assets/62aac850-2438-4465-98d4-1cdca12b1b3d)

![看板预览 2](https://github.com/user-attachments/assets/c0f2bf27-fe5f-4bc4-95c3-86f2b82df9ba)

![看板预览 3](https://github.com/user-attachments/assets/411435a9-6613-46d6-b375-f786b38c5285)

---

## ⚠️ 数据真实性说明（请先读这一段）

**本项目当前使用的是 MySQL 官方示例库 `world` 的 `city` 表**，该表只有三个字段：

| 字段 | 含义 |
|---|---|
| `Name` | 城市名 |
| `CountryCode` | 国家代码 |
| `Population` | 人口数 |

因此：

- **`物流等级`** 是基于「人口规模」按固定阈值划分的，**不是**真实物流业务分级
- **`模拟订单量` / `建议仓储面积(㎡)` / `配送时效(小时)`** 是**基于规则构造的模拟值**，不是真实业务数据，无业务依据

**本项目的价值在于验证「数据库取数 → 数据清洗 → 分级建模 → 可视化交付」这条完整方法链路**，而非产出可直接用于物流决策的结论。

> 真实数据版本开发中，见下方 [Roadmap](#roadmap)。

---

## 目录结构

```
logistics-dashboard-china/
├── logistics_analysis.py            # 主分析脚本：取数 → 清洗 → 分级 → 导出
├── 中国城市物流网络看板.pbix          # Power BI 交互式看板源文件
├── 物流分级报表_YYYY-MM-DD.xlsx       # 输出的分级报表（示例产物）
├── sql/
│   └── 01_city_logistics_ranking.sql # 窗口函数 / 帕累托分析 / NTILE 分级
├── data/                            # 存放原始数据（当前为空）
├── output/                          # 脚本输出目录
├── requirements.txt
├── .env.example                     # 数据库配置模板
└── .gitignore
```

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置数据库连接（.env 已被 .gitignore 忽略，不会提交）
cp .env.example .env
#    然后编辑 .env，填入你自己的 MySQL 密码

# 3. 运行分析
python logistics_analysis.py
```

**前置条件**：本地 MySQL 中已导入官方示例数据库 `world`。
（可从 [MySQL 官方示例库](https://dev.mysql.com/doc/index-other.html) 下载 `world.sql` 后导入）

### 运行结果

脚本会在 `output/` 下生成 `物流分级报表_YYYY-MM-DD.xlsx`，包含两个 sheet：

- **城市明细**：每个城市的人口、物流等级、建议仓储面积、配送时效、模拟订单量
- **层级统计**：各等级的城市数量、覆盖人口、模拟订单总量

---

## 数据处理流程

```
MySQL (world.city)
      │  SQL 取数，筛选 CountryCode = 'CHN'
      ▼
   pandas 清洗          # 剔除人口为空或非正数的异常记录
      │
      ▼
   分级建模             # 按人口阈值划分 A/B/C/D 四级物流枢纽
      │
      ▼
   派生字段             # 建议仓储面积、配送时效、模拟订单量
      │
      ▼
   Excel 报表  ──────▶  Power BI 看板
```

### 分级规则

| 等级 | 人口阈值 | 建议仓储面积 | 目标配送时效 |
|---|---|---|---|
| A级（核心枢纽） | ≥ 5,000,000 | 10,000 ㎡ | 24 h |
| B级（区域中心） | ≥ 3,000,000 | 5,000 ㎡ | 48 h |
| C级（配送站点） | ≥ 1,000,000 | 1,000 ㎡ | 72 h |
| D级（末端网点） | < 1,000,000 | 200 ㎡ | 96 h |

> 以上阈值为**教学假设值**，非行业标准。真实项目应由业务方给定。

---

## 技术栈

| 类别 | 技术 |
|---|---|
| 数据处理 | Python 3.10+、pandas |
| 数据库 | MySQL、PyMySQL、SQLAlchemy |
| 可视化 | Power BI |
| 其他 | Git、python-dotenv |

---

## Roadmap

- [x] **v0.1** 打通「MySQL → pandas → Excel → Power BI」完整链路
- [ ] **v0.2** 替换为真实数据
  - 数据源：快递公司年报（巨潮资讯网）、国家统计局、交通运输部、中国物流与采购联合会
- [ ] **v0.3** 引入数仓分层（ODS / DWD / DWS / ADS）与 SQL 视图
- [ ] **v0.4** 增加需求预测模块（指数平滑 / ARIMA / Prophet，含 MAE、MAPE 评估）
- [ ] **v0.5** 增加运筹优化模块（车辆路径问题 VRP、设施选址），使用 OR-Tools
- [ ] **v0.6** 用 Streamlit 部署在线 Demo，无需安装 Power BI 即可查看

---

## 已知局限

1. 数据为 MySQL 示例库的城市人口数据，**非真实物流数据**
2. 业务字段为规则模拟值，未经业务验证
3. 尚无 OD（Origin-Destination）数据，因此**无法真实反映运输流向**，看板中的流向为示意
4. 未考虑实际运输距离、道路网络、时效约束等真实因素

---

## License

MIT
