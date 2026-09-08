'use strict';

const POWER='https://power.larc.nasa.gov/api/temporal/daily/point';
const BRANDED_ORIGIN='https://chrisizworski.com';

function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
function median(xs){
  const a=xs.filter(Number.isFinite).sort((x,y)=>x-y);
  if(!a.length)return null;
  const m=Math.floor(a.length/2);
  return a.length%2?a[m]:(a[m-1]+a[m])/2;
}
function doyUTC(d){return Math.floor((Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())-Date.UTC(d.getUTCFullYear(),0,0))/86400000);}
function dateFromDoy(year,n){const d=new Date(Date.UTC(year,0,1));d.setUTCDate(n);return d;}
function ymd(d){return `${d.getUTCFullYear()}${String(d.getUTCMonth()+1).padStart(2,'0')}${String(d.getUTCDate()).padStart(2,'0')}`;}
function roundPowerGrid(lat,lon){
  return {lat:Math.round(lat/0.5)*0.5,lon:Math.round(lon/0.625)*0.625};
}
function periodFeature(weather,year,cutoffDoy){
  const end=dateFromDoy(year,cutoffDoy);
  const start=new Date(Date.UTC(year-1,10,1));
  if(end<=start)return null;
  const vals=[];
  for(let t=start.getTime();t<=end.getTime();t+=86400000){
    const d=new Date(t),key=d.toISOString().slice(0,10),temp=weather.get(key);
    if(Number.isFinite(temp))vals.push({d,temp});
  }
  const expected=Math.round((end-start)/86400000)+1;
  if(vals.length<expected*0.9)return null;
  let fdd=0,tdd=0,warm14=0;const jan1=Date.UTC(year,0,1),lastStart=end.getTime()-14*86400000,last=[];
  for(const x of vals){
    fdd+=Math.max(0,-x.temp);
    if(x.d.getTime()>=jan1)tdd+=Math.max(0,x.temp);
    if(x.d.getTime()>lastStart){last.push(x.temp);warm14+=Math.max(0,x.temp);}
  }
  if(last.length<10)return null;
  return {fdd,tdd,last14:last.reduce((a,b)=>a+b,0)/last.length,warm14};
}
async function fetchPower(lat,lon,start,end){
  const u=new URL(POWER);
  u.searchParams.set('parameters','T2M');
  u.searchParams.set('community','AG');
  u.searchParams.set('longitude',String(lon));
  u.searchParams.set('latitude',String(lat));
  u.searchParams.set('start',ymd(start));
  u.searchParams.set('end',ymd(end));
  u.searchParams.set('format','JSON');
  u.searchParams.set('time-standard','UTC');
  const r=await fetch(u,{headers:{'User-Agent':'chrisizworski-ice-out/1.0'},signal:AbortSignal.timeout(20000)});
  if(!r.ok){const txt=(await r.text()).slice(0,300);throw new Error(`NASA POWER ${r.status}: ${txt}`);}
  const j=await r.json();const p=j?.properties?.parameter?.T2M||{};const out=new Map();
  for(const [k,v] of Object.entries(p)){
    const n=Number(v);if(!Number.isFinite(n)||n<=-900)continue;
    const key=`${k.slice(0,4)}-${k.slice(4,6)}-${k.slice(6,8)}`;out.set(key,n);
  }
  return out;
}

module.exports=async function handler(req,res){
  res.setHeader('Access-Control-Allow-Origin',BRANDED_ORIGIN);
  res.setHeader('Vary','Origin');
  if(req.method!=='GET'){res.setHeader('Allow','GET');return res.status(405).json({error:'GET only'});}
  try{
    const lat=Number(req.query.lat),lon=Number(req.query.lon);
    if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<24||lat>73||lon<-171||lon>-49)return res.status(400).json({error:'lat/lon outside supported North America ice-out domain'});
    let asOf=req.query.date?new Date(`${String(req.query.date)}T12:00:00Z`):new Date();
    if(Number.isNaN(asOf.getTime()))return res.status(400).json({error:'invalid date'});
    asOf=new Date(Date.UTC(asOf.getUTCFullYear(),asOf.getUTCMonth(),asOf.getUTCDate()));
    const month=asOf.getUTCMonth();
    if(month<0||month>6)return res.status(200).json({active:false,as_of:asOf.toISOString().slice(0,10),reason:'seasonal physics is only evaluated January through July'});
    const year=asOf.getUTCFullYear(),cutoffDoy=doyUTC(asOf),grid=roundPowerGrid(lat,lon);
    const start=new Date(Date.UTC(year-21,10,1));
    const weather=await fetchPower(grid.lat,grid.lon,start,asOf);
    const current=periodFeature(weather,year,cutoffDoy);
    if(!current)throw new Error('insufficient current-season POWER coverage');
    const prior=[];
    for(let y=year-20;y<year;y++){
      const f=periodFeature(weather,y,cutoffDoy);if(f)prior.push({year:y,...f});
    }
    if(prior.length<8)throw new Error(`insufficient prior climate years: ${prior.length}`);
    const med={fdd:median(prior.map(x=>x.fdd)),tdd:median(prior.map(x=>x.tdd)),last14:median(prior.map(x=>x.last14)),warm14:median(prior.map(x=>x.warm14))};
    const features=[(current.fdd-med.fdd)/100,(current.tdd-med.tdd)/50,current.last14-med.last14,(current.warm14-med.warm14)/50];
    res.setHeader('Cache-Control','public, s-maxage=21600, stale-while-revalidate=86400');
    res.setHeader('Content-Type','application/json; charset=utf-8');
    return res.status(200).json({
      active:true,source:'NASA POWER daily T2M UTC',as_of:asOf.toISOString().slice(0,10),cutoff_doy:cutoffDoy,
      requested:{lat,lon},power_grid:grid,prior_years:prior.length,
      feature_order:['fdd_anom_per_100Cday','tdd_anom_per_50Cday','last14_temp_anom_C','warm14_anom_per_50Cday'],
      features:features.map(v=>Number(v.toFixed(6))),
      raw_current:Object.fromEntries(Object.entries(current).map(([k,v])=>[k,Number(v.toFixed(3))])),
      prior_median:Object.fromEntries(Object.entries(med).map(([k,v])=>[k,Number(v.toFixed(3))]))
    });
  }catch(e){
    res.setHeader('Cache-Control','no-store');
    return res.status(502).json({error:'seasonal physics unavailable',detail:String(e?.message||e).slice(0,500)});
  }
};
