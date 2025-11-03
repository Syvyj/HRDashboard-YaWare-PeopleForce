#!/usr/bin/env python3
"""Читання Control Excel файлів"""
import pandas as pd
import json

print("=" * 80)
print("CONTROL_1.xlsx:")
print("=" * 80)
df1 = pd.read_excel('config/Control_1.xlsx')
print(f"Columns: {list(df1.columns)}")
print(f"Total rows: {len(df1)}\n")
print("First 15 rows:")
print(df1.head(15).to_string(index=False))

print("\n" + "=" * 80)
print("CONTROL_2.xlsx:")
print("=" * 80)
df2 = pd.read_excel('config/Control_2.xlsx')
print(f"Columns: {list(df2.columns)}")
print(f"Total rows: {len(df2)}\n")
print("First 15 rows:")
print(df2.head(15).to_string(index=False))

print("\n" + "=" * 80)
print("SUMMARY:")
print("=" * 80)
print(f"Control_1: {len(df1)} users")
print(f"Control_2: {len(df2)} users")
print(f"Total: {len(df1) + len(df2)} users")
