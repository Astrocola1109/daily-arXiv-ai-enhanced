import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {escapeHtml,filterPapers,safeArxivUrl} from '../web/utils.mjs';

test('Private database denies anonymous and other authenticated users; flags merge atomically',async()=>{
  const db=new PGlite();
  await db.exec(`create schema auth; create table auth.users(id uuid primary key);
    create role anon; create role authenticated; create role service_role bypassrls;
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid; $$;
    grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;
    insert into auth.users values ('11111111-1111-1111-1111-111111111111'),('22222222-2222-2222-2222-222222222222');`);
  await db.exec(await readFile(new URL('../supabase/schema.sql',import.meta.url),'utf8'));
  await db.exec(`insert into public.digest_owners values ('11111111-1111-1111-1111-111111111111');
    insert into public.papers values ('11111111-1111-1111-1111-111111111111','2610.00001','2610.00001v1','2026-10-07','{"private":"secret"}');
    insert into public.research_profiles(user_id,profile) values ('11111111-1111-1111-1111-111111111111','{"research_lines":["private direction"]}');
    set role anon;`);
  await assert.rejects(db.query('select * from public.papers'),/permission denied/);
  await db.exec(`reset role; set role authenticated; select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',false);`);
  assert.equal((await db.query('select * from public.papers')).rows.length,0);
  assert.equal((await db.query('select * from public.research_profiles')).rows.length,0);
  await assert.rejects(db.query(`select * from public.set_reading_flag('2610.00001','favorite',true)`),/Not authorized/);
  await assert.rejects(db.query(`insert into public.digest_owners values ('22222222-2222-2222-2222-222222222222')`),/permission denied/);
  await db.exec(`select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',false);`);
  assert.equal((await db.query('select * from public.papers')).rows.length,1);
  await db.query(`select * from public.set_reading_flag('2610.00001','favorite',true)`);
  await db.query(`select * from public.set_reading_flag('2610.00001','is_read',true)`);
  const state=(await db.query('select * from public.reading_states')).rows[0];
  assert.equal(state.favorite,true);assert.equal(state.is_read,true);assert.equal(state.disliked,false);
  await assert.rejects(db.query(`insert into public.reading_states(user_id,paper_id) values ('22222222-2222-2222-2222-222222222222','2610.00002')`),/row-level security/);
  await assert.rejects(db.query(`update public.papers set payload='{}'`),/permission denied/);
  await assert.rejects(db.query(`select * from public.set_reading_flag('2610.00001','admin',true)`),/Invalid reading flag/);
  await db.close();
});

test('Untrusted paper strings and links are not rendered as executable HTML',()=>{
  assert.equal(escapeHtml('<img src=x onerror=alert(1)>'),'&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(safeArxivUrl('javascript:alert(1)'),'#');
  assert.equal(safeArxivUrl('2610.08091v1'),'https://arxiv.org/abs/2610.08091v1');
});
test('Revision and extension sections work without direct papers; disliked items remain recoverable',()=>{
  const papers=[{id:'a',title:'A',relevance:'extension',event:'new'},{id:'b',title:'B',relevance:'direct',event:'revision'}];
  assert.equal(filterPapers(papers,{},'direct').length,0);
  assert.equal(filterPapers(papers,{},'extension').length,1);
  assert.equal(filterPapers(papers,{},'revision').length,1);
  assert.equal(filterPapers(papers,{a:{disliked:true}},'extension').length,0);
  assert.equal(filterPapers(papers,{a:{disliked:true}},'disliked').length,1);
});
