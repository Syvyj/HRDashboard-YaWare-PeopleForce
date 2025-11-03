#!/usr/bin/env python3
"""Детальний аналіз Control файлів"""
import pandas as pd

def analyze_control_file(filepath, file_name):
    print("=" * 80)
    print(f"{file_name}:")
    print("=" * 80)
    
    df = pd.read_excel(filepath)
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}\n")
    
    # Знайдемо всі унікальні значення в першій колонці (Department/Team)
    first_col = df.iloc[:, 0]
    unique_vals = first_col.dropna().unique()
    print(f"Unique values in first column ({df.columns[0]}):")
    for val in unique_vals[:20]:  # Перші 20
        print(f"  - {val}")
    
    # Покажемо 30 рядків для розуміння структури
    print("\nFirst 30 rows:")
    print(df.head(30).to_string(index=True))
    print("\n")

analyze_control_file('config/Control_1.xlsx', 'Control_1.xlsx')
analyze_control_file('config/Control_2.xlsx', 'Control_2.xlsx')
