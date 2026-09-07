#!/usr/bin/env python3
import csv, json, urllib.request
from pathlib import Path

BASE='https://noaadata.apps.nsidc.org/NOAA/G01377/'
FILES=['liag_freeze_thaw_table.csv','liag_physical_character_table.csv']
OUT=Path('north-america/data/ice-history/nsidc-schema.json')
OUT.parent.mkdir(parents=True,exist_ok=True)
result={'source':'NSIDC G01377','base_url':BASE,'files':{}}
for name in FILES:
    req=urllib.request.Request(BASE+name,headers={'User-Agent':'ChrisIzworski-IceOut/1.0'})
    with urllib.request.urlopen(req,timeout=120) as r:
        text=r.read().decode('utf-8-sig','replace')
    rows=list(csv.DictReader(text.splitlines()))
    result['files'][name]={
        'columns':list(rows[0].keys()) if rows else [],
        'row_count':len(rows),
        'sample_rows':rows[:3]
    }
OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:{'rows':v['row_count'],'columns':v['columns']} for k,v in result['files'].items()},indent=2))
