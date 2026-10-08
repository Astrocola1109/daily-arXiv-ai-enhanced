import {build} from 'esbuild';
import {mkdir,copyFile,writeFile,readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const out=path.join(root,'site');await mkdir(out,{recursive:true});
await build({entryPoints:[path.join(root,'web/app.js')],bundle:true,minify:true,outdir:out,format:'esm',loader:{'.woff2':'file','.woff':'file','.ttf':'file'},assetNames:'fonts/[name]-[hash]',legalComments:'eof'});
await copyFile(path.join(root,'web/index.html'),path.join(out,'index.html'));
let cfg={supabaseUrl:process.env.SUPABASE_URL??'',supabaseAnonKey:process.env.SUPABASE_ANON_KEY??''};
if(!cfg.supabaseUrl){try{cfg=JSON.parse(await readFile(path.join(root,'web/config.json'),'utf8'));}catch{}}
// Only these two public values may enter the website. Never copy .env or runtime.
if(cfg.supabaseAnonKey.startsWith('sb_secret_'))throw new Error('Refusing secret key in frontend');
if(cfg.supabaseAnonKey.split('.').length===3){const claims=JSON.parse(Buffer.from(cfg.supabaseAnonKey.split('.')[1],'base64url').toString());if(claims.role!=='anon')throw new Error('Only anon JWT keys are allowed in frontend');}
await writeFile(path.join(out,'config.json'),JSON.stringify({supabaseUrl:cfg.supabaseUrl,supabaseAnonKey:cfg.supabaseAnonKey}));
await writeFile(path.join(out,'.nojekyll'),'');
console.log('Built public UI only:',out);
