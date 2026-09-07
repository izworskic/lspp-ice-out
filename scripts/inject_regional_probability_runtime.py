#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js')
s=p.read_text(encoding='utf-8')
marker="const scale = lake.history?.type==='regional' ? 6.5 : Math.max(4.8, spread/2.1);"
if marker in s:
    print('Regional probability scale already applied');raise SystemExit(0)
old="    const scale = Math.max(4.8, spread/2.1);"
new="    // Held-out regional calibration benchmark selected a 6.5-day logistic scale.\n    const scale = lake.history?.type==='regional' ? 6.5 : Math.max(4.8, spread/2.1);"
if old not in s:raise SystemExit('scale marker not found')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('Applied validated 6.5-day regional probability scale')
