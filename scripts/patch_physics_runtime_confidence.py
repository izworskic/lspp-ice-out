#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js')
s=p.read_text(encoding='utf-8')
changed=False
old="if(state.weatherError && activeSeason(today)) confidence='Low';"
new="if(state.weatherError && activeSeason(today) && !seasonalPhysicsApplied) confidence='Low';"
if old in s:
    s=s.replace(old,new,1);changed=True
old_comment="// A positive seasonal shift means breakup is running early, so compare target+shift to history."
new_comment="// correctionDays is positive for a later season, so evaluate the historical CDF against target-correction."
if old_comment in s:
    s=s.replace(old_comment,new_comment,1);changed=True
if changed:
    p.write_text(s,encoding='utf-8');print('Patched seasonal physics confidence/comment logic')
else:
    if new not in s:raise SystemExit('Expected physics confidence marker not found')
    print('Seasonal physics confidence patch already present')
