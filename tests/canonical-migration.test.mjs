import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
const read=p=>readFileSync(new URL('../'+p,import.meta.url),'utf8');
const canonical='https://chrisizworski.com/national-tools/ice-out/';
const local='https://lspp-ice-out.vercel.app/';
test('only legacy national entry points redirect permanently, not local park or assets',()=>{
 const config=JSON.parse(read('vercel.json'));
 assert.deepEqual(config.redirects.map(x=>x.source),['/north-america','/north-america/','/north-america/index.html']);
 assert.ok(config.redirects.every(x=>x.destination===canonical&&x.permanent===true));
 assert.match(read('index.html'),/<link rel="canonical" href="https:\/\/lspp-ice-out\.vercel\.app\/"/);
 const header=config.headers.find(x=>x.source==='/north-america/data/:path*');
 assert.deepEqual(header.headers,[{key:'Access-Control-Allow-Origin',value:'https://chrisizworski.com'}]);
});
test('canonical, social and discovery metadata agree without cross-host sitemap entries',()=>{
 const h=read('north-america/index.html');
 assert.ok(h.includes('rel="canonical" href="'+canonical+'"'));
 assert.ok(h.includes('property="og:url" content="'+canonical+'"'));
 assert.ok(h.includes('https://chrisizworski.com/#person'));
 assert.ok(read('llms.txt').includes(canonical));
 assert.deepEqual([...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m=>m[1]),[local]);
 assert.ok(read('robots.txt').includes(local+'sitemap.xml'));
});
test('branded page fetches model assets from their real origin, while same-origin API proxies remain',()=>{
 const a=read('north-america/app.js');
 for(const name of ['HYDRO_BASE','HISTORY_URL','PHYSICS_MODELS_URL','REGIONAL_PHYSICS_MODELS_URL','PHYSICS_PROBABILITY_URL','PHYSICS_INTERVALS_URL']){
  assert.ok(a.includes("const "+name+" = '"+local+"north-america/data/"),name);
 }
 assert.ok(a.includes('fetch(\x60/api/seasonal-physics?'));
 assert.ok(a.includes('fetch(\x60/api/lake-search?'));
 if(existsSync(new URL('../public/',import.meta.url))){
  for(const p of ['north-america/app.js','north-america/data/hydrolakes/manifest.json','north-america/data/ice-history/nsidc-calibration.json','north-america/data/seasonal-physics/lead-models.json','sitemap.xml','index.html'])assert.ok(existsSync(new URL('../public/'+p,import.meta.url)),p);
  assert.equal(existsSync(new URL('../public/tests/',import.meta.url)),false);
 }
});
