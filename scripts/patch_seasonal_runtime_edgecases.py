#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js');s=p.read_text(encoding='utf-8');changed=False
for old,new in [
("Math.abs(m.shift).toFixed(1)","Math.abs(m.forecastShift).toFixed(1)"),
("const dir = m.shift>1 ? 'pulling the window earlier' : m.shift<-1 ? 'pushing the window later' : 'close to climatological pace';","const dir = m.forecastShift>1 ? 'pulling the window earlier' : m.forecastShift<-1 ? 'pushing the window later' : 'close to climatological pace';"),
("Math.abs(m.shift).toFixed(1)","Math.abs(m.forecastShift).toFixed(1)")
]:
    if old in s:s=s.replace(old,new,1);changed=True
old="""    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather(); enrichLake(lake).finally(()=>attachHistory(lake));
"""
new="""    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather();
    if(lake.history?.type==='direct'||lake.history?.type==='regional')refreshSeasonalPhysics(lake);
    enrichLake(lake).finally(()=>attachHistory(lake));
"""
if old in s:s=s.replace(old,new,1);changed=True
if not changed:
    if "refreshSeasonalPhysics(lake);\n    enrichLake" not in s:raise SystemExit('Expected seasonal runtime edge-case markers not found')
    print('Seasonal runtime edge cases already patched');raise SystemExit(0)
p.write_text(s,encoding='utf-8');print('Patched seasonal runtime edge cases')
