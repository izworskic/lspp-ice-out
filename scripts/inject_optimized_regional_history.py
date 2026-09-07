#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js');s=p.read_text(encoding='utf-8')
if 'const elevSim=(Number(lake.elev)>0&&Number(x.h.elevation_m)>0)' in s:
    print('Optimized regional history weighting already applied');raise SystemExit(0)
old="""        const nearby=ranked.filter(x=>x.d<=500&&Number(x.h.records)>=15).slice(0,16);
        if(nearby.length>=3){
          let num=0,den=0;
          for(const x of nearby){
            const expected=morphologyBaselineDoy(histLakeObject(x.h));
            const residual=Number(x.h.median_doy)-expected;
            const w=Math.sqrt(Number(x.h.records))*Math.exp(-x.d/220);
            num+=residual*w;den+=w;
          }
"""
new="""        // Held-out optimization: use fewer/closer analogs and favor similar elevation/depth.
        const nearby=ranked.filter(x=>x.d<=500&&Number(x.h.records)>=15).slice(0,8);
        if(nearby.length>=3){
          let num=0,den=0;
          for(const x of nearby){
            const expected=morphologyBaselineDoy(histLakeObject(x.h));
            const residual=Number(x.h.median_doy)-expected;
            const elevSim=(Number(lake.elev)>0&&Number(x.h.elevation_m)>0)?Math.exp(-Math.abs(Number(lake.elev)-Number(x.h.elevation_m))/250):1;
            const depthSim=(Number(lake.depthM)>0&&Number(x.h.mean_depth_m)>0)?Math.exp(-Math.abs(Math.log(Number(lake.depthM)/Number(x.h.mean_depth_m)))/2):1;
            const w=Math.sqrt(Number(x.h.records))*Math.exp(-x.d/140)*elevSim*depthSim;
            num+=residual*w;den+=w;
          }
"""
if old not in s:raise SystemExit('regional weighting block not found')
s=s.replace(old,new,1);p.write_text(s,encoding='utf-8');print('Applied optimized regional historical weighting')
