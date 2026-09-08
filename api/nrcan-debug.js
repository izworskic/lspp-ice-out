'use strict';
module.exports=async function handler(req,res){
  const q=String(req.query?.q||'Lake Nipigon');
  const params=new URLSearchParams({q,category:'O,P,M',concise:'LAKE',num:'20','sort-field':'name',expand:'items.status,items.concise,items.generic,items.province',select:'items.status.term,items.concise.term,items.generic.term,items.province.description'});
  const url=`https://geogratis.gc.ca/services/geoname/en/geonames.json?${params}`;
  try{const r=await fetch(url,{headers:{Accept:'application/json','User-Agent':'ChrisIzworski-LakeIceOut/1.0'}});const text=await r.text();res.setHeader('Content-Type','application/json');res.end(JSON.stringify({url,status:r.status,contentType:r.headers.get('content-type'),body:text.slice(0,12000)}));}catch(e){res.statusCode=500;res.end(JSON.stringify({url,error:e.message}));}
};
