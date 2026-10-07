import pandas as pd

df1 = pd.read_csv("1Stage_Output.csv")
print("1Stage_Output shape:", df1.shape)

df2 = pd.read_csv("2Stage_Final_Output.csv")
print("2Stage_Final_Output shape:", df2.shape)

