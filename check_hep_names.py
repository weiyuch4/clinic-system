#!/usr/bin/env python3
"""
Check which names from the expected hepatitis patient list are found in IC files.
Run on PC1: python check_hep_names.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date
from collections import defaultdict
from database import _ic_main_files, _parse_dbf_cached, _hep_type, _roc_to_date

EXPECTED_NAMES = """王俐云
莊啟章
李張蒼美
薛安村
杜素媚
楊玉娟
蔡芳國
董格宏
陳美賢
許恭銘
魏貴招
陳錫龍
吳富貴
尤靜儀
陳冠蓁
陳美君
邱一立
張阜民
歐旻昊
劉詠婷
邱翊銘
黃麗蓉
王滄璇
于慶忠
許邱秀鑾
陳建翰
沈政敏
曾思倩
陳錦州
武玉文
莊吉智
陳鉞坤
鄭聰標
張博為
陳錫盈
余建志
林玉祥
洪秀英
廖順隆
林明輝
盧建君
林秀棠
簡保連
陳梁壽
蕭大仁
林月霞
簡宗榮
陳麗淑
張麗文
黃大誠
吳永芳
張文賢
楊培恩
謝進春
劉進焜
張雅萍
黃熒芳
陳凌玲
吳明倫
楊采紅
于正文
陳惠幸
林塘勝
洪瑛珍
廖士權
黃麗玉
張健志
江進義
陳雅芸
湯淑霞
陳品位
賴文鍾
林科仁
王曼沁
謝惠媚
莊文賓
張豐鑐
陳子茜
蔡雪雯
黃凱鈴
陳金財
林嘉玲
張淳媚
謝英源
林清祿
林香蘭
許維真
梁恩喬
易美麗
陳隆進
黃桂珠
劉淑娟
廖偲含
劉秀雲
趙世民
謝郭燕鳳
余貝倩
盧美秀
黃見揚
賴珍秀
紀漢昌
李秀嫚
林美金
孫堡源
黃沛晴
宋勝雄
黃秉豐
賴秀貞
林麗華
鄒金麟
陳智青
王秀足
陳欽沂
林俊孝
邱孟承
張隆傑
易玉忠
易依伶
柯文貴
林世佳
張謝寶珠
梁佑民
洪隆益
張乾琪
李煌誌
林東廷
翁維成
黃寶貴
陳密
賴玉芬
陳錫威
陳素真
劉洲權
李佳陵
賴錫棋
黃國慶
李兆章
蔣美蘭
林慧玉
賴姿羽
劉陳美華
葉權輝
李素秋
蘇百祥
蔡寶林
翁鉛如
林淑枝
陳瓊如
高銘澤
鍾由美
鄭建明
黃文炫
吳至萱
林泰山
洪采聘
李振勇
林文明
高金春
廖政威
李素香
詹素真
廖益新
陳玄宗
黃鈺媚
楊玉貞
李正傳
鄭景宸
紀淑玲
楊淑貞
李春芳
黃俊成
黃英雅
張詠筑
劉國淋
蔡譯稼
吳秉翰
游村松
李佳芸
洪浚凱
陳秋蘭
葉真惠
陳永青
古彩鳳
鄭焜年
蕭惠文
柯沐良
賴福立
李文欽
賴盧秀琴
黃晴
蔡銘岳
劉俊麟
阮氏娟
陳啟智
李崇
李麗華
林禮翔
陳忠霖
何依霖
謝雅惠
施文彬
黃璽誌
林榮德
陳冠宇
吳長運
鄭祐鈞
李家文
江俊柏
莊塗城
葉維新
黃佩菁
詹博升
葉又禎
石鎧豪
王盈舜
陳培瑋
楊仙維
施維軒
邱于軒
蘇威丞
溫曉嵐
石平文
陳美鳳
吳恭帆
張琦皇
黃文霖
陳東澤
黃瓊梅
蔡明亨
陳淑娟
廖淑莉
陳小玲
廖美蓮
劉育君
陳美華
陳昱孚
游鼎穎
黃志德
簡富祝
陳自堅
陳姿穎""".strip().splitlines()

expected = {n.strip() for n in EXPECTED_NAMES if n.strip()}
print(f"Expected patients: {len(expected)}\n")

# Scan all IC files for hepatitis patients
# found_by_name: name → {nat_id, birth, last_visit, hep_type, icd_codes, h_types}
found_by_name: dict[str, dict] = {}
# Also index by nat_id in case same person appears under slightly different name
found_by_id: dict[str, dict] = {}

ICD_FIELDS = ('ICD', 'ICD1', 'ICD2', 'ICD3', 'ICD4', 'ICD5')

files = _ic_main_files()
print(f"Scanning {len(files)} IC files...", flush=True)

for i, path in enumerate(files):
    if (i + 1) % 12 == 0:
        print(f"  ...{i+1}/{len(files)} files", flush=True)
    try:
        for r in _parse_dbf_cached(path):
            if r.get('H_TYPE', '') not in ('01西醫', 'AE連續'):
                continue
            hep = _hep_type(r)
            if not hep:
                continue
            nat_id = r.get('ID', '').strip()
            name   = r.get('NAME', '').strip()
            if not nat_id and not name:
                continue
            v_date = _roc_to_date(r.get('DATE', ''))
            birth  = _roc_to_date(r.get('BIRTH', ''))
            h_type = r.get('H_TYPE', '').strip()

            # Collect ICD codes that triggered hep detection
            codes = []
            for f in ICD_FIELDS:
                c = r.get(f, '').strip()
                if c:
                    codes.append(c)

            key = nat_id or name
            if key not in found_by_id:
                found_by_id[key] = {
                    'name': name, 'nat_id': nat_id, 'birth': birth,
                    'last_visit': v_date, 'hep_type': hep,
                    'icd_codes': set(codes), 'h_types': {h_type},
                }
            else:
                p = found_by_id[key]
                if name and not p['name']:
                    p['name'] = name
                if birth and not p['birth']:
                    p['birth'] = birth
                if v_date and (not p['last_visit'] or v_date > p['last_visit']):
                    p['last_visit'] = v_date
                if hep != p['hep_type'] and p['hep_type'] != 'BC':
                    p['hep_type'] = 'BC'
                p['icd_codes'].update(codes)
                p['h_types'].add(h_type)
    except Exception as e:
        print(f"  ERROR {os.path.basename(path)}: {e}")

# Build name → info lookup
name_to_info: dict[str, dict] = {}
for info in found_by_id.values():
    n = info['name']
    if n:
        if n not in name_to_info:
            name_to_info[n] = info
        else:
            # Keep the one with more recent last_visit
            existing = name_to_info[n]
            if info['last_visit'] and (not existing['last_visit'] or info['last_visit'] > existing['last_visit']):
                name_to_info[n] = info

print(f"Total unique hepatitis patients in IC files: {len(found_by_id)}\n")

today = date.today()

# Compare expected vs found
found_names     = []
not_found_names = []

for name in sorted(expected):
    if name in name_to_info:
        found_names.append(name)
    else:
        not_found_names.append(name)

print("=" * 60)
print(f"FOUND ({len(found_names)}/{len(expected)}):")
print("=" * 60)
for name in found_names:
    info = name_to_info[name]
    lv   = info['last_visit']
    days = (today - lv).days if lv else '?'
    codes = ', '.join(sorted(info['icd_codes']))
    hep  = info['hep_type']
    print(f"  {name:10s}  最後: {lv}  ({days}天前)  型別:{hep}  ICD:{codes}")

print()
print("=" * 60)
print(f"NOT FOUND ({len(not_found_names)}/{len(expected)}):")
print("=" * 60)
for name in not_found_names:
    print(f"  {name}")

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Expected:  {len(expected)}")
print(f"  Found:     {len(found_names)}")
print(f"  Not found: {len(not_found_names)}")

# Breakdown of found patients by overdue category
print()
print("Found patients — status breakdown:")
counts = {'還沒到期 (<161天)': 0, '待聯絡 (161-364天)': 0, '結案 (365-729天)': 0, '再收案 (730+天)': 0, '日期不明': 0}
for name in found_names:
    lv = name_to_info[name]['last_visit']
    if not lv:
        counts['日期不明'] += 1
    else:
        d = (today - lv).days
        if d < 161:
            counts['還沒到期 (<161天)'] += 1
        elif d < 365:
            counts['待聯絡 (161-364天)'] += 1
        elif d < 730:
            counts['結案 (365-729天)'] += 1
        else:
            counts['再收案 (730+天)'] += 1
for label, count in counts.items():
    if count:
        print(f"  {label}: {count}")
