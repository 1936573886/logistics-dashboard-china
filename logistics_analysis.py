import pandas as pd
import pymysql
from datetime import datetime

# 1. 连接 MySQL，读取数据
conn = pymysql.connect(
    host='localhost',
    user='root',
    password='root123456',  # ⚠️ 改成你自己的 MySQL 密码！
    database='world',
    charset='utf8mb4'
)

sql = "SELECT Name, Population FROM city WHERE CountryCode = 'CHN' ORDER BY Population DESC;"
df = pd.read_sql(sql, conn)
conn.close()

print(f"✅ 成功读取 {len(df)} 条中国城市记录")

# 2. 物流等级划分
def assign_logistics_level(population):
    if population >= 5000000:
        return "A级（核心枢纽）"
    elif population >= 3000000:
        return "B级（区域中心）"
    elif population >= 1000000:
        return "C级（配送站点）"
    else:
        return "D级（末端网点）"

df['物流等级'] = df['Population'].apply(assign_logistics_level)

# 3. 模拟物流业务字段
df['模拟订单量'] = (df['Population'] * 0.01).astype(int)  # 每100人1单
df['建议仓储面积(㎡)'] = df['物流等级'].map({
    'A级（核心枢纽）': 10000,
    'B级（区域中心）': 5000,
    'C级（配送站点）': 1000,
    'D级（末端网点）': 200
})
df['配送时效(小时)'] = df['物流等级'].map({
    'A级（核心枢纽）': 24,
    'B级（区域中心）': 48,
    'C级（配送站点）': 72,
    'D级（末端网点）': 96
})

# 4. 按等级统计
summary = df.groupby('物流等级').size().reset_index(name='城市数量')
print("\n📊 物流网络层级规划：")
print(summary.to_string(index=False))

# 5. 自动生成带日期的文件名
today = datetime.today().strftime('%Y-%m-%d')
output_path = rf"C:\Users\Admin（无密码）\Desktop\物流分级报表_{today}.xlsx"

# 6. 保存到 Excel
with pd.ExcelWriter(output_path) as writer:
    df.to_excel(writer, sheet_name='城市明细', index=False)
    summary.to_excel(writer, sheet_name='层级统计', index=False)

print(f"\n✅ 报表已保存到桌面：物流分级报表_{today}.xlsx")