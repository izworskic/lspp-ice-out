from pathlib import Path

p = Path('north-america/app.js')
s = p.read_text()

# Insert normalized search/ranking helpers before registry adapters.
needle = "  // OFFICIAL LAKE REGISTRIES\n"
helpers = r'''  // OFFICIAL LAKE SEARCH RANKING
  // Registry APIs can return many same-name hydrographic features. Build a larger
  // candidate pool, then rank exact/normalized matches locally so the wanted lake
  // is not lost just because it was not in the first alphabetical page.
  function normalizeLakeSearchName(value){
    return String(value||'')
      .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
      .toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  }
  function coreLakeSearchName(value){
    return normalizeLakeSearchName(value)
      .split(/\s+/).filter(x=>x && !['lake','lac','reservoir','pond','flowage'].includes(x)).join(' ');
  }
  function searchVariants(value){
    const raw=normalizeLakeSearchName(value), core=coreLakeSearchName(value);
    const variants=[];
    [raw,core].forEach(v=>{if(v.length>=2&&!variants.includes(v))variants.push(v);});
    // A long distinctive token is a useful fallback for names such as "Lake Opeongo"
    // where the registry stores the generic word in a different position.
    const tokens=core.split(/\s+/).filter(x=>x.length>=5).sort((a,b)=>b.length-a.length);
    tokens.slice(0,2).forEach(v=>{if(!variants.includes(v))variants.push(v);});
    return variants.slice(0,4);
  }
  function lakeSearchScore(query,lake){
    const q=normalizeLakeSearchName(query), qc=coreLakeSearchName(query);
    const n=normalizeLakeSearchName(lake?.name), nc=coreLakeSearchName(lake?.name);
    if(!q||!n)return -1;
    let score=0;
    if(n===q)score=1200;
    else if(nc&&qc&&nc===qc)score=1150;
    else if(n.startsWith(q))score=950;
    else if(nc&&qc&&nc.startsWith(qc))score=925;
    else if(n.includes(q))score=800;
    else if(nc&&qc&&nc.includes(qc))score=775;
    else {
      const qt=(qc||q).split(/\s+/).filter(Boolean), nt=new Set((nc||n).split(/\s+/).filter(Boolean));
      const hits=qt.filter(t=>nt.has(t)).length;
      if(hits===qt.length&&hits)score=650+hits*20;
      else if(hits)score=400+hits*20;
    }
    // Favor shorter name-distance once match quality is otherwise similar.
    score-=Math.min(80,Math.abs(n.length-q.length));
    return score;
  }
  function rankLakeResults(query,rows,limit=24){
    const dedup=new Map();
    rows.filter(Boolean).forEach(l=>{const key=l.id||`${l.source}:${l.sourceId}`;if(!dedup.has(key))dedup.set(key,l);});
    return [...dedup.values()]
      .map(l=>({l,score:lakeSearchScore(query,l)})).filter(x=>x.score>0)
      .sort((a,b)=>b.score-a.score || a.l.name.localeCompare(b.l.name) || String(a.l.region).localeCompare(String(b.l.region)))
      .slice(0,limit).map(x=>x.l);
  }

'''
if 'function normalizeLakeSearchName' not in s:
    assert needle in s
    s = s.replace(needle, helpers + needle, 1)

old_us = r'''  async function searchUSOfficial(q){
    const clean=q.replace(/'/g,"''");
    const params=new URLSearchParams({where:`gaz_name LIKE '%${clean}%'`,outFields:'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:'8',orderByFields:'gaz_name'});
    const r=await fetch(`${US_GNIS}?${params.toString()}`,{headers:{Accept:'application/geo+json,application/json'}});
    if(!r.ok)throw new Error(`USGS names ${r.status}`);
    const j=await r.json();
    return (j.features||[]).map(usFeatureToLake).filter(Boolean).filter(l=>/lake|reservoir|pond|flowage/i.test(l.featureClass));
  }
'''
new_us = r'''  async function searchUSOfficial(q){
    const variants=searchVariants(q), rows=[];
    const settled=await Promise.allSettled(variants.map(async term=>{
      const clean=term.replace(/'/g,"''");
      const params=new URLSearchParams({where:`gaz_name LIKE '%${clean}%'`,outFields:'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:'75'});
      const r=await fetch(`${US_GNIS}?${params.toString()}`,{headers:{Accept:'application/geo+json,application/json'}});
      if(!r.ok)throw new Error(`USGS names ${r.status}`);
      const j=await r.json(); return (j.features||[]).map(usFeatureToLake).filter(Boolean);
    }));
    settled.forEach(x=>{if(x.status==='fulfilled')rows.push(...x.value);});
    if(!rows.length && settled.some(x=>x.status==='rejected'))throw settled.find(x=>x.status==='rejected').reason;
    // Layer 7 is already USGS "Other Hydrographic Features"; do not discard a valid
    // lake merely because its feature-class label is not one of our old four strings.
    return rankLakeResults(q,rows,24);
  }
'''
assert old_us in s
s = s.replace(old_us, new_us, 1)

old_ca = r'''  async function searchCAOfficial(q){
    const params=new URLSearchParams({q,category:'O',concise:'LAKE',num:'8','sort-field':'name',expand:'items.concise,items.province',select:'items.concise.term,items.province.description'});
    const r=await fetch(`${CA_NAMES}?${params.toString()}`,{headers:{Accept:'application/json'}});
    if(!r.ok)throw new Error(`NRCan names ${r.status}`);
    const j=await r.json(); const items=Array.isArray(j)?j:(j.items||j.results||[]);
    return items.map(caItemToLake).filter(Boolean);
  }
'''
new_ca = r'''  async function searchCAOfficial(q){
    const variants=searchVariants(q), rows=[];
    const settled=await Promise.allSettled(variants.map(async term=>{
      const params=new URLSearchParams({q:term,category:'O',concise:'LAKE',num:'75','sort-field':'name',expand:'items.concise,items.province',select:'items.concise.term,items.province.description'});
      const r=await fetch(`${CA_NAMES}?${params.toString()}`,{headers:{Accept:'application/json'}});
      if(!r.ok)throw new Error(`NRCan names ${r.status}`);
      const j=await r.json(); const items=Array.isArray(j)?j:(j.items||j.results||[]);
      return items.map(caItemToLake).filter(Boolean);
    }));
    settled.forEach(x=>{if(x.status==='fulfilled')rows.push(...x.value);});
    if(!rows.length && settled.some(x=>x.status==='rejected'))throw settled.find(x=>x.status==='rejected').reason;
    return rankLakeResults(q,rows,24);
  }
'''
assert old_ca in s
s = s.replace(old_ca, new_ca, 1)

old_run = "    const remote=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake);\n    const dedup=new Map(); remote.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});\n    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,14),errors); $('results').classList.add('show'); bindSearchResults();\n"
new_run = "    const remote=rankLakeResults(rawSearchQuery||q,settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake),24);\n    const dedup=new Map(); remote.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});\n    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,24),errors); $('results').classList.add('show'); bindSearchResults();\n"
# We do not have rawSearchQuery yet; patch the whole function below instead of using this fragment.

old_run_fn = r'''  async function runOfficialSearch(q,local){
    const seq=++state.searchSeq;
    $('results').innerHTML=resultMarkup(local,[])+`<div class="result loading-row"><span>Searching USGS + NRCan official lake names…</span></div>`;
    $('results').classList.add('show'); bindSearchResults();
    const settled=await Promise.allSettled([searchUSOfficial(q),searchCAOfficial(q)]);
    if(seq!==state.searchSeq||$('search').value.trim().toLowerCase()!==q.toLowerCase())return;
    const errors=settled.filter(x=>x.status==='rejected').map(x=>x.reason?.message||'lookup error');
    const remote=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake);
    const dedup=new Map(); remote.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});
    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,14),errors); $('results').classList.add('show'); bindSearchResults();
  }
'''
new_run_fn = r'''  async function runOfficialSearch(q,local){
    const seq=++state.searchSeq;
    $('results').innerHTML=resultMarkup(local,[])+`<div class="result loading-row"><span>Searching USGS + NRCan official lake names…</span></div>`;
    $('results').classList.add('show'); bindSearchResults();
    const settled=await Promise.allSettled([searchUSOfficial(q),searchCAOfficial(q)]);
    if(seq!==state.searchSeq||normalizeLakeSearchName($('search').value)!==normalizeLakeSearchName(q))return;
    const errors=settled.filter(x=>x.status==='rejected').map(x=>x.reason?.message||'lookup error');
    const ranked=rankLakeResults(q,settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake),24);
    const dedup=new Map(); ranked.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});
    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,24),errors); $('results').classList.add('show'); bindSearchResults();
  }
'''
assert old_run_fn in s
s = s.replace(old_run_fn, new_run_fn, 1)

old_update = r'''  function updateSearch(){
    const raw=$('search').value.trim(); const q=raw.toLowerCase(); clearTimeout(searchTimer); state.searchSeq++;
    if(!q){$('results').classList.remove('show');return;}
    const local=benchmarkLakes.filter(l=>`${l.name} ${l.region} ${l.country}`.toLowerCase().includes(q)).slice(0,8);
    $('results').innerHTML=resultMarkup(local,[]); $('results').classList.add('show'); bindSearchResults();
    if(raw.length>=3) searchTimer=setTimeout(()=>runOfficialSearch(raw,local),320);
  }
'''
new_update = r'''  function updateSearch(){
    const raw=$('search').value.trim(); const q=normalizeLakeSearchName(raw); clearTimeout(searchTimer); state.searchSeq++;
    if(!q){$('results').classList.remove('show');return;}
    const local=rankLakeResults(raw,benchmarkLakes.filter(l=>lakeSearchScore(raw,l)>0),8);
    $('results').innerHTML=resultMarkup(local,[]); $('results').classList.add('show'); bindSearchResults();
    if(q.length>=2) searchTimer=setTimeout(()=>runOfficialSearch(raw,local),260);
  }
'''
assert old_update in s
s = s.replace(old_update, new_update, 1)

p.write_text(s)
