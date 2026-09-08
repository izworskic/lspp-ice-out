'use strict';

const DATA_COMMIT='32ff7eb7a5d39e368d14294e38f59b9f46dd415d';
const US_INDEX_BASE=`https://cdn.jsdelivr.net/gh/izworskic/lspp-ice-out@${DATA_COMMIT}/north-america/data/lake-index`;
const CA_NAMES='https://geogratis.gc.ca/services/geoname/en/geonames.json';

const US_REGIONS={al:'AL',alabama:'AL',ak:'AK',alaska:'AK',az:'AZ',arizona:'AZ',ar:'AR',arkansas:'AR',ca:'CA',california:'CA',co:'CO',colorado:'CO',ct:'CT',connecticut:'CT',de:'DE',delaware:'DE',fl:'FL',florida:'FL',ga:'GA',georgia:'GA',hi:'HI',hawaii:'HI',id:'ID',idaho:'ID',il:'IL',illinois:'IL',in:'IN',indiana:'IN',ia:'IA',iowa:'IA',ks:'KS',kansas:'KS',ky:'KY',kentucky:'KY',la:'LA',louisiana:'LA',me:'ME',maine:'ME',md:'MD',maryland:'MD',ma:'MA',massachusetts:'MA',mi:'MI',michigan:'MI',mn:'MN',minnesota:'MN',ms:'MS',mississippi:'MS',mo:'MO',missouri:'MO',mt:'MT',montana:'MT',ne:'NE',nebraska:'NE',nv:'NV',nevada:'NV',nh:'NH','new hampshire':'NH',nj:'NJ','new jersey':'NJ',nm:'NM','new mexico':'NM',ny:'NY','new york':'NY',nc:'NC','north carolina':'NC',nd:'ND','north dakota':'ND',oh:'OH',ohio:'OH',ok:'OK',oklahoma:'OK',or:'OR',oregon:'OR',pa:'PA',pennsylvania:'PA',ri:'RI','rhode island':'RI',sc:'SC','south carolina':'SC',sd:'SD','south dakota':'SD',tn:'TN',tennessee:'TN',tx:'TX',texas:'TX',ut:'UT',utah:'UT',vt:'VT',vermont:'VT',va:'VA',virginia:'VA',wa:'WA',washington:'WA',wv:'WV','west virginia':'WV',wi:'WI',wisconsin:'WI',wy:'WY',wyoming:'WY',dc:'DC','district of columbia':'DC'};
const CA_REGIONS={ab:'AB',alberta:'AB',bc:'BC','british columbia':'BC',mb:'MB',manitoba:'MB',nb:'NB','new brunswick':'NB',nl:'NL','newfoundland and labrador':'NL',newfoundland:'NL',labrador:'NL',ns:'NS','nova scotia':'NS',nt:'NT','northwest territories':'NT','northwest territory':'NT',nwt:'NT',nu:'NU',nunavut:'NU',on:'ON',ontario:'ON',pe:'PE',pei:'PE','prince edward island':'PE',qc:'QC',quebec:'QC',québec:'QC',sk:'SK',saskatchewan:'SK',yt:'YT',yukon:'YT'};
const CA_REGION_NAMES={AB:'Alberta',BC:'British Columbia',MB:'Manitoba',NB:'New Brunswick',NL:'Newfoundland and Labrador',NS:'Nova Scotia',NT:'Northwest Territories',NU:'Nunavut',ON:'Ontario',PE:'Prince Edward Island',QC:'Quebec',SK:'Saskatchewan',YT:'Yukon'};
const CA_CODE_BY_NAME=Object.fromEntries(Object.entries(CA_REGION_NAMES).map(([k,v])=>[normalize(v),k]));

function normalize(v){return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();}
function core(v){return normalize(v).split(/\s+/).filter(x=>x&&!['lake','lac','reservoir','pond','flowage'].includes(x)).join(' ');}
function shardKey(v){const c=(core(v)||normalize(v)).replace(/[^a-z0-9]/g,'');return c.length>=2?c.slice(0,2):`${c}_`.slice(0,2);}
function splitQuery(v){
  let q=normalize(v),country=null,regionCode=null;
  const countryAliases=[['united states','US'],['usa','US'],['u s','US'],['canada','CA']];
  for(const [label,code] of countryAliases){if(q===label){q='';country=code;break;}if(q.endsWith(` ${label}`)){q=q.slice(0,-label.length-1).trim();country=code;break;}}
  const candidates=[];
  Object.entries(US_REGIONS).forEach(([k,code])=>candidates.push([k,code,'US']));
  Object.entries(CA_REGIONS).forEach(([k,code])=>candidates.push([k,code,'CA']));
  candidates.sort((a,b)=>b[0].length-a[0].length);
  for(const [label,code,c] of candidates){
    if(q===label){q='';regionCode=code;country=c;break;}
    if(q.endsWith(` ${label}`)){q=q.slice(0,-label.length-1).trim();regionCode=code;country=c;break;}
  }
  return{nameQuery:q,regionCode,country};
}
function score(query,row){const q=normalize(query),qc=core(query),n=normalize(row?.[1]),nc=core(row?.[1]);if(!q||!n)return-1;let s=0;if(n===q)s=1200;else if(nc&&qc&&nc===qc)s=1150;else if(n.startsWith(q))s=950;else if(nc&&qc&&nc.startsWith(qc))s=925;else if(n.includes(q))s=800;else if(nc&&qc&&nc.includes(qc))s=775;else{const qt=(qc||q).split(/\s+/).filter(Boolean),nt=new Set((nc||n).split(/\s+/).filter(Boolean));const hits=qt.filter(t=>nt.has(t)).length;if(hits===qt.length&&hits)s=650+hits*20;else if(hits)s=400+hits*20;}return s-Math.min(80,Math.abs(n.length-q.length));}
function rank(query,rows,limit=50){const seen=new Map();for(const row of rows){if(!Array.isArray(row))continue;const key=`${row[4]}:${row[0]}`;if(!seen.has(key))seen.set(key,row);}return [...seen.values()].map(x=>({x,s:score(query,x)})).filter(o=>o.s>0).sort((a,b)=>b.s-a.s||String(a.x[1]).localeCompare(String(b.x[1]))||String(a.x[3]).localeCompare(String(b.x[3]))).slice(0,limit).map(o=>o.x);}

async function searchUS(parsed,key){
  if(parsed.country==='CA')return [];
  const r=await fetch(`${US_INDEX_BASE}/${key}.json`,{headers:{Accept:'application/json'}});
  if(!r.ok)throw new Error(`US lake shard ${r.status}`);
  let rows=await r.json(); rows=(Array.isArray(rows)?rows:[]).filter(x=>Array.isArray(x)&&x[4]==='US');
  if(parsed.regionCode&&parsed.country==='US')rows=rows.filter(x=>x[2]===parsed.regionCode);
  return rows;
}
function provinceCode(item){const p=item?.province?.description||item?.province?.term||item?.province||'';return CA_CODE_BY_NAME[normalize(p)]||CA_REGIONS[normalize(p)]||'';}
async function searchCanada(parsed){
  if(parsed.country==='US')return [];
  const params=new URLSearchParams({q:parsed.nameQuery,category:'O,P,M',concise:'LAKE',num:'100','sort-field':'name',expand:'items.status,items.concise,items.generic,items.province',select:'items.status.term,items.concise.term,items.generic.term,items.province.description'});
  const r=await fetch(`${CA_NAMES}?${params.toString()}`,{headers:{Accept:'application/json','User-Agent':'ChrisIzworski-LakeIceOut/1.0'}});
  if(!r.ok)throw new Error(`NRCan CGNDB ${r.status}`);
  const j=await r.json(); const items=Array.isArray(j)?j:(j.items||j.results||[]); const rows=[];
  for(const item of items){
    const lat=Number(item.latitude??item.lat),lon=Number(item.longitude??item.lon);if(!Number.isFinite(lat)||!Number.isFinite(lon))continue;
    const pc=provinceCode(item);if(!pc)continue;if(parsed.regionCode&&parsed.country==='CA'&&pc!==parsed.regionCode)continue;
    const name=item.name||item.geoname;if(!name)continue;const key=String(item.key||item.cgndb_key||item.toponymicFeature||`${lat},${lon}`);
    rows.push([`cgndb-${key}`,String(name),pc,CA_REGION_NAMES[pc],'CA',lat,lon,'Lake',String(item.location||'')]);
  }
  return rows;
}

module.exports=async function handler(req,res){
  if(req.method!=='GET'){res.statusCode=405;res.setHeader('Allow','GET');return res.end(JSON.stringify({error:'method_not_allowed'}));}
  const q=String(req.query?.q||'').trim(),parsed=splitQuery(q);
  if(parsed.nameQuery.length<2){res.statusCode=400;return res.end(JSON.stringify({error:'query_too_short'}));}
  const key=shardKey(parsed.nameQuery);
  const settled=await Promise.allSettled([searchUS(parsed,key),searchCanada(parsed)]);
  const rows=rank(parsed.nameQuery,settled.flatMap(x=>x.status==='fulfilled'?x.value:[]),50);
  if(!rows.length&&settled.every(x=>x.status==='rejected')){res.statusCode=502;res.setHeader('Cache-Control','no-store');return res.end(JSON.stringify({error:'lake_search_unavailable',detail:settled.map(x=>x.reason?.message).filter(Boolean).join('; ')}));}
  res.setHeader('Content-Type','application/json; charset=utf-8');
  res.setHeader('Cache-Control','public, s-maxage=21600, stale-while-revalidate=604800');
  return res.end(JSON.stringify({query:q,name_query:parsed.nameQuery,region:parsed.regionCode,country:parsed.country,shard:key,count:rows.length,rows,sources:{US:'USGS GNIS static index',CA:'NRCan CGNDB'}}));
};
