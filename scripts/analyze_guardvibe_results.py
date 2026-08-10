#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GuardVibe 综合安全报告：合并所有子扫描，生成项目自身代码完整安全画像"""
import json
import os
from collections import Counter, defaultdict

# 所有扫描结果文件
SCAN_FILES = [
    r"D:\拾光剪影\.guardvibe-app-scan.json",
    r"D:\拾光剪影\.guardvibe-core-scan.json",
    r"D:\拾光剪影\.guardvibe-modules-scan.json",
    r"D:\拾光剪影\.guardvibe-scripts-scan.json",
]

# 排除第三方路径
EXCLUDE = ['site-packages', 'packaging_env', '.venv', 'thirdparty', 'node_modules']

all_findings = []
seen_keys = set()  # 去重

for sf in SCAN_FILES:
    if not os.path.exists(sf):
        continue
    with open(sf, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for finding in data.get('findings', []):
        fpath = finding.get('file', '')
        if any(ex in fpath for ex in EXCLUDE):
            continue
        # 去重 key: file + line + id
        key = (fpath, finding.get('line'), finding.get('id'))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        all_findings.append(finding)

# 按严重程度统计
sev_counter = Counter(f.get('severity', 'unknown') for f in all_findings)
# 按规则统计
rule_counter = Counter((f.get('id', ''), f.get('name', '')) for f in all_findings)
# 按文件统计
file_counter = Counter(
    f.get('file', '').replace('D:\\拾光剪影\\', '').replace('\\', '/')
    for f in all_findings
)

print("=" * 80)
print("  拾光剪影 - GuardVibe 安全扫描综合报告")
print("=" * 80)
print()
print("扫描范围: app/ + app/core/ + app/modules/ + scripts/ + main_qt6.py")
print("排除路径: .venv312/, app/packaging_env/, thirdparty/, node_modules/")
print()
print("─" * 80)
print("【严重程度分布】")
for sev in ['critical', 'high', 'medium', 'low', 'unknown']:
    if sev_counter[sev]:
        print("  {:<10} {:>4}".format(sev.upper(), sev_counter[sev]))
print("  {:<10} {:>4}".format("总计", len(all_findings)))
print()

print("─" * 80)
print("【按规则分类】")
for (rid, rname), count in rule_counter.most_common():
    sev = next((f.get('severity', '?') for f in all_findings if f.get('id') == rid), '?')
    print("  {} {:<50} {:>3}  [{}]".format(rid, rname[:50], count, sev.upper()))
print()

print("─" * 80)
print("【涉及文件】")
for fpath, count in file_counter.most_common():
    print("  {:<70} {:>3}".format(fpath, count))
print()

print("─" * 80)
print("【全部发现详情】")
print("─" * 80)
for j, f in enumerate(all_findings, 1):
    fname = f.get('file', '').replace('D:\\拾光剪影\\', '')
    print()
    print("[{}/{}] {} - {}  [{}]".format(
        j, len(all_findings),
        f.get('id', ''),
        f.get('name', ''),
        str(f.get('severity', '')).upper()
    ))
    print("  OWASP:  {}".format(f.get('owasp', '')))
    print("  文件:   {}:{}".format(fname, f.get('line', '')))
    print("  代码:   {}".format(f.get('match', '')))
    print("  修复:   {}".format(f.get('fix', '')))
