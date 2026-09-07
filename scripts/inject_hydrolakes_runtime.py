#!/usr/bin/env python3
from pathlib import Path

P = Path('north-america/app.js')
s = P.read_text(encoding='utf-8')


def rep(old, new):
    global s
    if old not in s:
        raise SystemExit(f'Expected app.js anchor not found:\n{old[:160]}')
    s = s.replace(old, new, 1)

rep("  const dynamicLakes = new Map();\n  const state = {",
    "  const dynamicLakes = new Map();\n  const hydrolakesCache = new Map();\n  let hydroManifest = null;\n  const state = {")
rep("    searchSeq:0, nearbySeq:0\n", "    searchSeq:0, nearbySeq:0, enrichSeq:0\n")
rep("  const CA_NAMES = 'https://geogratis.gc.ca/services/geoname/en/geonames.json';\n",
    "  const CA_NAMES = 'https://geogratis.gc.ca/services/geoname/en/geonames.json';\n  const HYDRO_BASE = 'data/hydrolakes';\n")
rep("  function isRegional(lake){return lake.registry==='official';}\n",
"""  function isOfficial(lake){return lake?.registry==='official';}
  function isRegional(lake){return isOfficial(lake) && !lake.enriched;}
  function areaClass(km2){
    if(!Number.isFinite(km2))return 'medium';
    if(km2<2)return 'small'; if(km2<50)return 'medium'; if(km2<500)return 'large'; return 'huge';
  }
  function depthClass(m){
    if(!Number.isFinite(m)||m<=0)return 'medium';
    if(m<3)return 'shallow'; if(m<12)return 'medium'; if(m<35)return 'deep'; return 'verydeep';
  }
""")
rep("    if(isRegional(lake)) spread = lake.lat>60 ? 22 : 18;\n",
    "    if(isRegional(lake)) spread = lake.lat>60 ? 22 : 18;\n    else if(isOfficial(lake) && lake.enriched) spread = Math.max(spread,13);\n")
rep("    let confidence = isRegional(lake) ? 'Low' : 'Moderate';\n",
    "    let confidence = isRegional(lake) ? 'Low' : isOfficial(lake) ? 'Moderate' : 'Moderate';\n")

reason_anchor = """    if(!activeSeason(today)) return `For ${targetText}, this beta uses ${lake.name}'s latitude, elevation, basin depth class and size to establish a transparent regional climatology. Live weather is shown below but is not applied outside the spring breakup season.`;
"""
reason_new = """    if(isOfficial(lake) && lake.enriched){
      const morph=`${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km², ${lake.depthM>0?`${lake.depthM.toFixed(1)} m estimated mean depth`:'depth unavailable'}, ${Math.round(lake.elev||0)} m elevation`;
      if(!activeSeason(today)) return `${lake.name} has been matched to HydroLAKES morphology (${morph}). That sharpens the regional climatology, but historical lake-specific ice-out calibration is still pending.`;
      if(m.applyWeather) return `HydroLAKES morphology (${morph}) and the current 7-day thaw trajectory are both active. Historical lake-specific ice-out calibration is still pending, so confidence remains moderate.`;
      return `HydroLAKES morphology is attached (${morph}); historical lake-specific ice-out calibration is still pending.`;
    }
    if(!activeSeason(today)) return `For ${targetText}, this beta uses ${lake.name}'s latitude, elevation, basin depth class and size to establish a transparent regional climatology. Live weather is shown below but is not applied outside the spring breakup season.`;
"""
rep(reason_anchor, reason_new)

hydro_runtime = r'''
  // HYDROLAKES MORPHOMETRY — derived static shards, no database server required.
  async function getHydroManifest(){
    if(hydroManifest)return hydroManifest;
    const r=await fetch(`${HYDRO_BASE}/manifest.json`,{cache:'force-cache'});
    if(!r.ok)throw new Error(`HydroLAKES manifest ${r.status}`);
    hydroManifest=await r.json(); return hydroManifest;
  }
  function hydroShardKey(lat,lon,size){
    const y=Math.floor(lat/size)*size, x=Math.floor(lon/size)*size;
    const ys=y>=0?`+${String(y).padStart(2,'0')}`:`-${String(Math.abs(y)).padStart(2,'0')}`;
    const xs=x>=0?`+${String(x).padStart(3,'0')}`:`-${String(Math.abs(x)).padStart(3,'0')}`;
    return `lat${ys}_lon${xs}`;
  }
  async function loadHydroShard(key){
    if(hydrolakesCache.has(key))return hydrolakesCache.get(key);
    const p=fetch(`${HYDRO_BASE}/${key}.json`,{cache:'force-cache'}).then(async r=>r.ok?await r.json():[]).catch(()=>[]);
    hydrolakesCache.set(key,p); return p;
  }
  function chooseHydroMatch(rows,lake){
    const c=rows.map(r=>({row:r,d:distanceKm(lake,{lat:Number(r[1]),lng:Number(r[2])})})).filter(x=>Number.isFinite(x.d)).sort((a,b)=>a.d-b.d);
    const first=c[0],second=c[1]; if(!first)return null;
    const clear=first.d<=1.5 || (first.d<=5 && (!second||second.d>first.d*1.8)) || (first.d<=10 && (!second||second.d>first.d*3));
    if(!clear)return null;
    const r=first.row;
    return {hydrolakesId:Number(r[0]),hydroDistanceKm:first.d,areaKm2:Number(r[3]),depthM:Number(r[4]),elev:Number(r[5]),shoreDev:Number(r[6]),volumeMcm:Number(r[7]),lakeType:Number(r[8])};
  }
  async function findHydroMatch(lake){
    const mf=await getHydroManifest(),size=Number(mf.shard_size_degrees)||2;
    const center=hydroShardKey(lake.lat,lake.lng,size);
    const core=await loadHydroShard(center);
    let match=chooseHydroMatch(core,lake); if(match)return match;
    const y0=Math.floor(lake.lat/size)*size,x0=Math.floor(lake.lng/size)*size,keys=[];
    for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
      const k=hydroShardKey(y0+dy*size,x0+dx*size,size); if(k!==center)keys.push(k);
    }
    const rows=[...core,...(await Promise.all(keys.map(loadHydroShard))).flat()];
    return chooseHydroMatch(rows,lake);
  }
  async function enrichLake(lake){
    if(!isOfficial(lake)||lake.enriched||lake.enrichAttempted)return;
    lake.enrichAttempted=true; const token=++state.enrichSeq;
    try{
      const match=await findHydroMatch(lake); if(!match)return;
      Object.assign(lake,match,{enriched:true}); lake.area=areaClass(lake.areaKm2); lake.depth=depthClass(lake.depthM);
      if(state.lake.id===lake.id&&token===state.enrichSeq){
        if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
        ensureMarker(lake).setIcon(markerIcon(true,false)); renderModel();
      }
    }catch(e){console.warn('HydroLAKES enrichment unavailable',e);}
  }

'''
rep("  // MAP\n", hydro_runtime + "  // MAP\n")
rep("  map.attributionControl.addAttribution('Lake names: USGS GNIS / NRCan CGNDB');\n",
    "  map.attributionControl.addAttribution('Lake names: USGS GNIS / NRCan CGNDB');\n  map.attributionControl.addAttribution('Morphometry: HydroLAKES / HydroSHEDS');\n")
rep("  function rememberLake(lake){if(isRegional(lake))dynamicLakes.set(lake.id,lake);return lake;}\n",
    "  function rememberLake(lake){if(isOfficial(lake))dynamicLakes.set(lake.id,lake);return lake;}\n")
old_meta = """    const meta=isRegional(lake)
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
      : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`;
"""
new_meta = """    const meta=isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`;
"""
rep(old_meta,new_meta)
rep("    if(fly)map.flyTo([lake.lat,lake.lng], isRegional(lake)?8:(lake.area==='huge'?6:7),{duration:.65});\n    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather();\n",
    "    if(fly)map.flyTo([lake.lat,lake.lng], isOfficial(lake)?8:(lake.area==='huge'?6:7),{duration:.65});\n    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather(); enrichLake(lake);\n")
rep(" · regional estimate</span></div>`));}", " · morphology auto-match</span></div>`));}")
rep("  $('fitBtn').addEventListener('click',()=>map.flyTo([state.lake.lat,state.lake.lng],isRegional(state.lake)?8:(state.lake.area==='huge'?6:7),{duration:.6}));\n",
    "  $('fitBtn').addEventListener('click',()=>map.flyTo([state.lake.lat,state.lake.lng],isOfficial(state.lake)?8:(state.lake.area==='huge'?6:7),{duration:.6}));\n")

P.write_text(s,encoding='utf-8')
print('HydroLAKES runtime injected')
