from pathlib import Path
p=Path('north-america/app.js')
s=p.read_text()

old="""  function indexedLakeRecord(r){
    if(!Array.isArray(r)||r.length<8)return null;
    const lat=Number(r[5]),lng=Number(r[6]);if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    return {id:String(r[0]),name:String(r[1]||'Unnamed lake'),regionCode:String(r[2]||''),region:String(r[3]||r[2]||'United States'),country:String(r[4]||'US'),lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'USGS GNIS lake database',sourceId:String(r[0]).replace(/^gnis-/,''),featureClass:String(r[7]||'Lake'),county:String(r[8]||'')};
  }
  async function searchStaticUSLakeIndex(value){
    const parsed=splitLakeRegionQuery(value);if(!parsed.nameQuery||parsed.nameQuery.length<2)return [];
    const r=await fetch(`/api/lake-search?q=${encodeURIComponent(value)}`,{cache:'no-store'});
    if(!r.ok)throw new Error(`Lake database ${r.status}`);
    const payload=await r.json();
    let rows=(Array.isArray(payload?.rows)?payload.rows:[]).map(indexedLakeRecord).filter(Boolean).filter(x=>x.country==='US');
    if(parsed.regionCode)rows=rows.filter(x=>x.regionCode===parsed.regionCode);
    return rankLakeResults(parsed.nameQuery,rows,40);
  }
"""
new="""  function indexedLakeRecord(r){
    if(!Array.isArray(r)||r.length<8)return null;
    const lat=Number(r[5]),lng=Number(r[6]);if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    const country=String(r[4]||'US'), extra=String(r[8]||'');
    return {id:String(r[0]),name:String(r[1]||'Unnamed lake'),regionCode:String(r[2]||''),region:String(r[3]||r[2]||(country==='CA'?'Canada':'United States')),country,lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:country==='CA'?'NRCan CGNDB lake database':'USGS GNIS lake database',sourceId:String(r[0]).replace(/^(gnis|cgndb)-/,''),featureClass:String(r[7]||'Lake'),county:country==='US'?extra:'',location:country==='CA'?extra:''};
  }
  async function searchStaticLakeIndex(value){
    const r=await fetch(`/api/lake-search?q=${encodeURIComponent(value)}`,{cache:'no-store'});
    if(!r.ok)throw new Error(`Lake database ${r.status}`);
    const payload=await r.json();
    const rows=(Array.isArray(payload?.rows)?payload.rows:[]).map(indexedLakeRecord).filter(Boolean);
    return rankLakeResults(payload?.name_query||value,rows,50);
  }
"""
if old not in s: raise SystemExit('static lake search block not found')
s=s.replace(old,new,1)

old="""    const place=lake.county?`${lake.county} County · ${lake.region}`:lake.region;
"""
new="""    const place=lake.country==='US'&&lake.county?`${lake.county} County · ${lake.region}`:lake.country==='CA'&&lake.location?`${lake.location} · ${lake.region}`:lake.region;
"""
if old not in s: raise SystemExit('selected place block not found')
s=s.replace(old,new,1)

old="""    const metricLabels=document.querySelectorAll('.grid3 .metric span');
"""
new="""    const metricLabels=document.querySelectorAll('.metrics .metric span');
"""
if old not in s: raise SystemExit('metric selector not found')
s=s.replace(old,new,1)

old="""  function nearMarkup(arr,target){return arr.map(x=>{const m=lakeModel(x.lake,target),place=x.lake.county?`${x.lake.county} County · ${x.lake.region}`:x.lake.region;return `<div class=\"nearitem\" data-id=\"${escapeHtml(x.lake.id)}\"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(place)}</small></div><div class=\"np\">${Math.round(m.probability*100)}%</div></div>`;}).join('');}
"""
new="""  function nearMarkup(arr,target){return arr.map(x=>{const m=lakeModel(x.lake,target),place=x.lake.country==='US'&&x.lake.county?`${x.lake.county} County · ${x.lake.region}`:x.lake.country==='CA'&&x.lake.location?`${x.lake.location} · ${x.lake.region}`:x.lake.region;return `<div class=\"nearitem\" data-id=\"${escapeHtml(x.lake.id)}\"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(place)}</small></div><div class=\"np\">${Math.round(m.probability*100)}%</div></div>`;}).join('');}
"""
if old not in s: raise SystemExit('near markup not found')
s=s.replace(old,new,1)

old="""    if(remote.length){rows.push('<div class=\"result-head\">Official lake database</div>');remote.forEach(l=>{const place=l.county?`${l.county} County · ${l.region}`:l.region;rows.push(`<div class=\"result\" data-id=\"${escapeHtml(l.id)}\"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(place)} · ${escapeHtml(l.source)} · morphology auto-match</span></div>`);});}
"""
new="""    if(remote.length){rows.push('<div class=\"result-head\">Official North America lake search</div>');remote.forEach(l=>{const place=l.country==='US'&&l.county?`${l.county} County · ${l.region}`:l.country==='CA'&&l.location?`${l.location} · ${l.region}`:l.region;rows.push(`<div class=\"result\" data-id=\"${escapeHtml(l.id)}\"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(place)} · ${l.country==='CA'?'Canada':'United States'} · ${escapeHtml(l.source)}</span></div>`);});}
"""
if old not in s: raise SystemExit('result markup not found')
s=s.replace(old,new,1)

start=s.index('  async function runOfficialSearch(q,local){')
end=s.index('\n  function bindSearchResults()', start)
newfn="""  async function runOfficialSearch(q,local){
    const seq=++state.searchSeq;
    $('results').innerHTML=resultMarkup(local,[])+`<div class=\"result loading-row\"><span>Searching official U.S. + Canadian lakes…</span></div>`;
    $('results').classList.add('show'); bindSearchResults();
    try{
      const remote=(await searchStaticLakeIndex(q)).map(rememberLake);
      if(seq!==state.searchSeq||normalizeLakeSearchName($('search').value)!==normalizeLakeSearchName(q))return;
      const dedup=new Map();remote.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});
      $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,32),[]);$('results').classList.add('show');bindSearchResults();
    }catch(e){
      if(seq!==state.searchSeq)return;
      $('results').innerHTML=resultMarkup(local,[],[e.message||'lookup error']);$('results').classList.add('show');bindSearchResults();
    }
  }
"""
s=s[:start]+newfn+s[end:]

p.write_text(s)
print('patched browser search for unified North America endpoint and country-aware labels')
