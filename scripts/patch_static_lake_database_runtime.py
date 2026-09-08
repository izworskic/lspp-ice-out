from pathlib import Path

p=Path('north-america/app.js')
s=p.read_text()

s=s.replace("  const CA_NAMES = 'https://geogratis.gc.ca/services/geoname/en/geonames.json';\n", "  const CA_NAMES = 'https://geogratis.gc.ca/services/geoname/en/geonames.json';\n  const LAKE_INDEX_BASE = 'data/lake-index';\n",1)

needle="  function searchVariants(value){\n"
helpers=r'''  const US_STATE_ALIASES = {
    al:'AL',alabama:'AL',ak:'AK',alaska:'AK',az:'AZ',arizona:'AZ',ar:'AR',arkansas:'AR',ca:'CA',california:'CA',co:'CO',colorado:'CO',ct:'CT',connecticut:'CT',de:'DE',delaware:'DE',fl:'FL',florida:'FL',ga:'GA',georgia:'GA',hi:'HI',hawaii:'HI',id:'ID',idaho:'ID',il:'IL',illinois:'IL',in:'IN',indiana:'IN',ia:'IA',iowa:'IA',ks:'KS',kansas:'KS',ky:'KY',kentucky:'KY',la:'LA',louisiana:'LA',me:'ME',maine:'ME',md:'MD',maryland:'MD',ma:'MA',massachusetts:'MA',mi:'MI',michigan:'MI',mn:'MN',minnesota:'MN',ms:'MS',mississippi:'MS',mo:'MO',missouri:'MO',mt:'MT',montana:'MT',ne:'NE',nebraska:'NE',nv:'NV',nevada:'NV',nh:'NH','new hampshire':'NH',nj:'NJ','new jersey':'NJ',nm:'NM','new mexico':'NM',ny:'NY','new york':'NY',nc:'NC','north carolina':'NC',nd:'ND','north dakota':'ND',oh:'OH',ohio:'OH',ok:'OK',oklahoma:'OK',or:'OR',oregon:'OR',pa:'PA',pennsylvania:'PA',ri:'RI','rhode island':'RI',sc:'SC','south carolina':'SC',sd:'SD','south dakota':'SD',tn:'TN',tennessee:'TN',tx:'TX',texas:'TX',ut:'UT',utah:'UT',vt:'VT',vermont:'VT',va:'VA',virginia:'VA',wa:'WA',washington:'WA',wv:'WV','west virginia':'WV',wi:'WI',wisconsin:'WI',wy:'WY',wyoming:'WY',dc:'DC','district of columbia':'DC'
  };
  function splitLakeRegionQuery(value){
    const q=normalizeLakeSearchName(value), keys=Object.keys(US_STATE_ALIASES).sort((a,b)=>b.length-a.length);
    for(const key of keys){
      if(q===key)return {nameQuery:'',regionCode:US_STATE_ALIASES[key]};
      if(q.endsWith(` ${key}`))return {nameQuery:q.slice(0,-key.length-1).trim(),regionCode:US_STATE_ALIASES[key]};
    }
    return {nameQuery:q,regionCode:null};
  }
  function lakeIndexShardKey(value){
    const c=(coreLakeSearchName(value)||normalizeLakeSearchName(value)).replace(/[^a-z0-9]/g,'');
    return c.length>=2?c.slice(0,2):`${c}_`.slice(0,2);
  }
  function indexedLakeRecord(r){
    if(!Array.isArray(r)||r.length<8)return null;
    const lat=Number(r[5]),lng=Number(r[6]);if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    return {id:String(r[0]),name:String(r[1]||'Unnamed lake'),regionCode:String(r[2]||''),region:String(r[3]||r[2]||'United States'),country:String(r[4]||'US'),lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'USGS GNIS lake database',sourceId:String(r[0]).replace(/^gnis-/,''),featureClass:String(r[7]||'Lake'),county:String(r[8]||'')};
  }
  async function searchStaticUSLakeIndex(value){
    const parsed=splitLakeRegionQuery(value);if(!parsed.nameQuery||parsed.nameQuery.length<2)return [];
    const key=lakeIndexShardKey(parsed.nameQuery);if(!key)return [];
    const r=await fetch(`${LAKE_INDEX_BASE}/${key}.json`,{cache:'force-cache'});if(!r.ok)throw new Error(`Lake database ${r.status}`);
    const raw=await r.json();let rows=(Array.isArray(raw)?raw:[]).map(indexedLakeRecord).filter(Boolean).filter(x=>x.country==='US');
    if(parsed.regionCode)rows=rows.filter(x=>x.regionCode===parsed.regionCode);
    return rankLakeResults(parsed.nameQuery,rows,40);
  }

'''
assert needle in s
s=s.replace(needle,helpers+needle,1)

old_us=r'''  async function searchUSOfficial(q){
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
new_us=r'''  async function searchUSOfficial(q){
    const parsed=splitLakeRegionQuery(q), variants=searchVariants(parsed.nameQuery||q), rows=[];
    const settled=await Promise.allSettled(variants.map(async term=>{
      const clean=term.replace(/'/g,"''");
      const stateClause=parsed.regionCode?` AND state_alpha='${parsed.regionCode}'`:'';
      const params=new URLSearchParams({where:`gaz_name LIKE '%${clean}%'${stateClause}`,outFields:'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:'75'});
      const r=await fetch(`${US_GNIS}?${params.toString()}`,{headers:{Accept:'application/geo+json,application/json'}});
      if(!r.ok)throw new Error(`USGS names ${r.status}`);
      const j=await r.json(); return (j.features||[]).map(usFeatureToLake).filter(Boolean).map(x=>({...x,regionCode:x.region}));
    }));
    settled.forEach(x=>{if(x.status==='fulfilled')rows.push(...x.value);});
    if(!rows.length && settled.some(x=>x.status==='rejected'))throw settled.find(x=>x.status==='rejected').reason;
    return rankLakeResults(parsed.nameQuery||q,rows,24);
  }
'''
assert old_us in s
s=s.replace(old_us,new_us,1)

old_run=r'''  async function runOfficialSearch(q,local){
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
new_run=r'''  async function runOfficialSearch(q,local){
    const seq=++state.searchSeq, parsed=splitLakeRegionQuery(q);
    $('results').innerHTML=resultMarkup(local,[])+`<div class="result loading-row"><span>Searching lake database + official registries…</span></div>`;
    $('results').classList.add('show'); bindSearchResults();
    const tasks=[searchStaticUSLakeIndex(q),searchUSOfficial(q)];
    if(!parsed.regionCode)tasks.push(searchCAOfficial(q));
    const settled=await Promise.allSettled(tasks);
    if(seq!==state.searchSeq||normalizeLakeSearchName($('search').value)!==normalizeLakeSearchName(q))return;
    const errors=settled.filter(x=>x.status==='rejected').map(x=>x.reason?.message||'lookup error');
    let rows=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake);
    if(parsed.regionCode)rows=rows.filter(x=>x.country!=='US'||x.regionCode===parsed.regionCode||x.region===parsed.regionCode);
    const ranked=rankLakeResults(parsed.nameQuery||q,rows,32);
    const dedup=new Map(); ranked.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});
    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,28),errors); $('results').classList.add('show'); bindSearchResults();
  }
'''
assert old_run in s
s=s.replace(old_run,new_run,1)

old_update="    const local=rankLakeResults(raw,benchmarkLakes.filter(l=>lakeSearchScore(raw,l)>0),8);\n"
new_update="    const parsed=splitLakeRegionQuery(raw);\n    const local=rankLakeResults(parsed.nameQuery||raw,benchmarkLakes.filter(l=>(!parsed.regionCode||l.country!=='US'||l.region===parsed.regionCode||l.regionCode===parsed.regionCode)&&lakeSearchScore(parsed.nameQuery||raw,l)>0),8);\n"
assert old_update in s
s=s.replace(old_update,new_update,1)

p.write_text(s)
