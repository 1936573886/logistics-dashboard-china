import pandas as pd

# 读取原始数据
df = pd.read_excel('../data/物流分级报表_2026-08-28.xlsx')

# 看一眼数据基本信息
print(df.info())
print(df.head())

# 简单清洗：去掉完全空白的行，重置索引
df_clean = df.dropna(how='all').reset_index(drop=True)

# 输出清洗后的数据
df_clean.to_excel('../output/cleaned_data.xlsx', index=False)
print("清洗完成，已输出到 output/cleaned_data.xlsx")