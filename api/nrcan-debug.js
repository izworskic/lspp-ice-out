'use strict';
const names={AB:'Alberta',BC:'British Columbia',MB:'Manitoba',NB:'New Brunswick',NL:'Newfoundland and Labrador',NS:'Nova Scotia',NT:'Northwest Territories',NU:'Nunavut',ON:'Ontario',PE:'Prince Edward Island',QC:'Quebec',SK:'Saskatchewan',YT:'Yukon'};
const norm=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const byName=Object.fromEntries(Object.entries(names).map(([k,v])=>[norm(v),k]));
module.exports=async function handler(req,res){
  const q=String(req.query?.q||'Lake Nipigon');
  const params=new URLSearchParams({q,category:'O,P,M',concise:'LAKE',num:'20','sort-field':'name',expand:'items.status,items.concise,items.generic,items.province',select:'items.status.term,items.concise.term,items.generic.term,items.province.description'});
  const url=`https://geogratis.gc.ca/services/geoname/en/geonames.json?${params}`;
  try{const r=await fetch(url,{headers:{Accept:'application/json','User-Agent':'ChrisIzworski-LakeIceOut/1.0'}});const j=await r.json();const items=Array.isArray(j)?j:(j.items||j.results||[]);const mapped=items.map(item=>({id:item.id,name:item.name,province:item?.province?.description,pc:byName[norm(item?.province?.description)],lat:item.latitude,lon:item.longitude,location:item.location,category:item.category,concise:item?.concise?.code}));res.setHeader('Content-Type','application/json');res.end(JSON.stringify({url,status:r.status,count:items.length,mapped}));}catch(e){res.statusCode=500;res.end(JSON.stringify({url,error:e.message,stack:e.stack}));}
};
