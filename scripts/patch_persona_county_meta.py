from pathlib import Path

p=Path('north-america/app.js')
s=p.read_text()

old="""    const historyTag=lake.history?.type==='direct'?` · ${lake.history.records} historical ice-out dates`:lake.history?.type==='regional'?` · ${lake.history.stationCount}-lake regional history calibration`:'';
    const meta=(isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`)+historyTag;
"""
new="""    const historyTag=lake.history?.type==='direct'?` · ${lake.history.records} historical ice-out dates`:lake.history?.type==='regional'?` · ${lake.history.stationCount}-lake regional history calibration`:'';
    const place=lake.county?`${lake.county} County · ${lake.region}`:lake.region;
    const meta=(isOfficial(lake)&&lake.enriched
      ? `${place} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${place} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${place} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`)+historyTag;
"""
if old not in s: raise SystemExit('renderModel meta block not found')
s=s.replace(old,new,1)

old2="return {id:`gnis-${fid}`,name:p.gaz_name||'Unnamed lake',region:p.state_alpha||p.county_name||'United States',country:'US',lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'USGS GNIS',sourceId:fid,featureClass:p.gaz_featureclass||'Hydrographic feature'};"
new2="return {id:`gnis-${fid}`,name:p.gaz_name||'Unnamed lake',region:p.state_alpha||p.county_name||'United States',country:'US',lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'USGS GNIS',sourceId:fid,featureClass:p.gaz_featureclass||'Hydrographic feature',county:String(p.county_name||'')};"
if old2 not in s: raise SystemExit('US feature mapping block not found')
s=s.replace(old2,new2,1)

old3="function nearMarkup(arr,target){return arr.map(x=>{const m=lakeModel(x.lake,target);return `<div class=\"nearitem\" data-id=\"${escapeHtml(x.lake.id)}\"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(x.lake.region)}</small></div><div class=\"np\">${Math.round(m.probability*100)}%</div></div>`;}).join('');}"
new3="function nearMarkup(arr,target){return arr.map(x=>{const m=lakeModel(x.lake,target),place=x.lake.county?`${x.lake.county} County · ${x.lake.region}`:x.lake.region;return `<div class=\"nearitem\" data-id=\"${escapeHtml(x.lake.id)}\"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(place)}</small></div><div class=\"np\">${Math.round(m.probability*100)}%</div></div>`;}).join('');}"
if old3 not in s: raise SystemExit('nearby markup block not found')
s=s.replace(old3,new3,1)

p.write_text(s)
print('patched county identity through selected and nearby lake UI')
