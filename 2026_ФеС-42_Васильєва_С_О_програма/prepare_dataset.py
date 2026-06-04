"""
Чистить personalised_dataset.csv для навчання ML-моделі.
Залишає тільки ті колонки, які трекер реально збирає + мітки для навчання.
"""

import pandas as pd

df = pd.read_csv('personalised_dataset.csv')
print(f"Оригінал: {len(df)} рядків, {len(df.columns)} колонок")

keep = [
    'Age',
    'Gender',
    'BMI',
    'Physical_Activity_Level',
    'Sleep_Hours',
    'Resting_Heart_Rate',
    'Systolic_BP',
    'Diastolic_BP',
    'Health_Risk',
    'Diet_Recommendation',
    'Exercise_Recommendation',
]

df_clean = df[keep].copy()

# Числове кодування для ML
df_clean['Gender'] = df_clean['Gender'].map({'Male': 0, 'Female': 1})
df_clean['Activity_Score'] = df_clean['Physical_Activity_Level'].map({
    'Sedentary': 1, 'Lightly Active': 2, 'Moderately Active': 3, 'Highly Active': 4
})
df_clean['Risk_Label'] = df_clean['Health_Risk'].map({'Low': 0, 'Moderate': 1, 'High': 2})
df_clean = df_clean.drop(columns=['Physical_Activity_Level'])

df_clean.to_csv('personalised_dataset_clean.csv', index=False)
print(f"Чистий CSV: {len(df_clean.columns)} колонок, {len(df_clean)} рядків")
print(f"Колонки: {list(df_clean.columns)}")
print("Збережено: personalised_dataset_clean.csv")