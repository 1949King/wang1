#!/usr/bin/env python3
# 测试配置修复

from config.settings import Config

print("Config imported successfully!")
print(f"APP_DATA_DIR: {Config.APP_DATA_DIR}")
print(f"PLUGINS_DIR: {Config.PLUGINS_DIR}")
print(f"CACHE_DIR: {Config.CACHE_DIR}")
print(f"LOGS_DIR: {Config.LOGS_DIR}")
print(f"TEMP_DIR: {Config.TEMP_DIR}")

print("\n配置测试成功！")
