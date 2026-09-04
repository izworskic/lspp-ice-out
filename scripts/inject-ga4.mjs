#!/usr/bin/env node
import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
const ROOT=process.cwd();
const OUTPUT=path.join(ROOT,'public');
const ID='G-Y5D2V2W7HN';
const TAG=`<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=${ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', '${ID}');
</script>`;
const SKIP=new Set(['.git','.vercel','node_modules','public','scripts','vercel.json']);
await rm(OUTPUT,{recursive:true,force:true});
await mkdir(OUTPUT,{recursive:true});
for(const e of await readdir(ROOT,{withFileTypes:true})){if(SKIP.has(e.name))continue;await cp(path.join(ROOT,e.name),path.join(OUTPUT,e.name),{recursive:true});}
let scanned=0,injected=0,alreadyTagged=0;
async function walk(dir){for(const e of await readdir(dir,{withFileTypes:true})){const f=path.join(dir,e.name);if(e.isDirectory()){await walk(f);continue;}if(!e.isFile()||!e.name.toLowerCase().endsWith('.html'))continue;scanned++;const h=await readFile(f,'utf8');if(h.includes(ID)){alreadyTagged++;continue;}if(!/<\/head>/i.test(h))throw new Error(`Missing </head> in ${path.relative(OUTPUT,f)}`);await writeFile(f,h.replace(/<\/head>/i,`${TAG}\n</head>`));injected++;}}
await walk(OUTPUT);
console.log(JSON.stringify({measurementId:ID,scanned,injected,alreadyTagged,output:'public'}));
