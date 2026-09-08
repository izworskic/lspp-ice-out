from pathlib import Path
p=Path('north-america/app.js')
s=p.read_text()
old="""  async function searchStaticUSLakeIndex(value){
    const parsed=splitLakeRegionQuery(value);if(!parsed.nameQuery||parsed.nameQuery.length<2)return [];
    const key=lakeIndexShardKey(parsed.nameQuery);if(!key)return [];
    const r=await fetch(`${LAKE_INDEX_BASE}/${key}.json`,{cache:'force-cache'});if(!r.ok)throw new Error(`Lake database ${r.status}`);
    const raw=await r.json();let rows=(Array.isArray(raw)?raw:[]).map(indexedLakeRecord).filter(Boolean).filter(x=>x.country==='US');
    if(parsed.regionCode)rows=rows.filter(x=>x.regionCode===parsed.regionCode);
    return rankLakeResults(parsed.nameQuery,rows,40);
  }
"""
new="""  async function searchStaticUSLakeIndex(value){
    const parsed=splitLakeRegionQuery(value);if(!parsed.nameQuery||parsed.nameQuery.length<2)return [];
    const r=await fetch(`/api/lake-search?q=${encodeURIComponent(value)}`,{cache:'no-store'});
    if(!r.ok)throw new Error(`Lake database ${r.status}`);
    const payload=await r.json();
    let rows=(Array.isArray(payload?.rows)?payload.rows:[]).map(indexedLakeRecord).filter(Boolean).filter(x=>x.country==='US');
    if(parsed.regionCode)rows=rows.filter(x=>x.regionCode===parsed.regionCode);
    return rankLakeResults(parsed.nameQuery,rows,40);
  }
"""
if old not in s: raise SystemExit('target block not found')
s=s.replace(old,new,1)
p.write_text(s)
print('patched direct same-origin lake search')
