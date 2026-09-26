/* Run against the packaged EXE with an isolated data directory. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,chromePath}=require('../tests/runtime.cjs');
(async()=>{
 const base=process.env.RELEASE_TEST_URL||'http://127.0.0.1:8772';
 const browser=await chromium.launch({executablePath:chromePath,headless:true,args:['--no-proxy-server']});
 const errors=[],remote=[];
 try{
  const page=await browser.newPage({viewport:{width:1512,height:982}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(base))remote.push(r.url());});
  let status=await(await page.request.get(base+'/api/status')).json();assert.equal(status.version,'2.0.0');
  assert.equal(status.courses.length,0,'Use a fresh isolated workspace');
  for(const p of Object.values(status.settings.profiles))assert.equal(p.hasApiKey,false);
  const zip=fs.readFileSync('release/2.0.0/CourseCompiler-Demo.zip');
  const imported=await page.request.post(base+'/api/import-course',{headers:{'X-Course-Token':status.token,'Content-Type':'application/zip'},data:zip});assert.equal(imported.ok(),true);
  status=await(await page.request.get(base+'/api/status')).json();assert.equal(status.courses.length,1);
  const cid=status.courses[0].id;
  await page.goto(base);await page.waitForSelector('.course-row');
  await page.click('#show-settings');await page.waitForSelector('#profile-baseUrl');
  assert.equal(await page.inputValue('#profile-apiKey'),'');
  await page.screenshot({path:'docs/images/settings.png'});
  await page.goto(base+'/courses/'+cid+'/index.html');await page.waitForSelector('.unit');
  await page.waitForFunction(()=>!document.querySelector('.flash'));
  await page.screenshot({path:'docs/images/reader.png'});
  await page.click('.reading-preferences summary');await page.selectOption('#bilingual-layout','columns');await page.selectOption('#body-font','serif');await page.click('.reading-preferences summary');
  assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('bilingual-columns')),true);
  await page.click('#new-note');await page.fill('#note-text','Synthetic release verification note');await page.click('#note-form button[type="submit"]');
  await page.waitForTimeout(300);await page.reload();await page.click('[data-tab="notes"]');assert.match(await page.locator('#notebook-content').textContent(),/Synthetic release verification note/);
  // Export through the real frozen app, then open the extracted files without a server.
  const exported=await page.request.get(base+'/download/'+cid+'.zip');assert.equal(exported.ok(),true);
  fs.writeFileSync('tmp/release-export.zip',await exported.body());
  const unauthorized=await page.request.post(base+'/api/settings',{data:{}});assert.equal(unauthorized.status(),403);
  const foreign=await page.request.get(base+'/api/status',{headers:{Origin:'https://example.invalid'}});assert.equal(foreign.status(),403);
  const leak=await page.request.get(base+'/courses/'+cid+'/%2e%2e/%2e%2e/settings.json');assert.notEqual(leak.status(),200);
  const {execFileSync}=require('node:child_process');
  execFileSync(process.env.RELEASE_PYTHON||'python',['-c',"import zipfile; z=zipfile.ZipFile('tmp/release-export.zip'); assert z.testzip() is None; assert not any(x.endswith('settings.json') or '/notes/' in x or '/assistant/' in x for x in z.namelist()); z.extractall('tmp/release-static')"]);
  await page.goto('file:///'+path.resolve('tmp/release-static/index.html').replaceAll('\\','/'));await page.waitForSelector('.unit');
  await page.click('[data-tab="assistant"]');assert.equal(await page.locator('#assistant-send').isDisabled(),true);
  await page.click('[data-mode="translation"]');assert.equal(await page.locator('.source-copy').first().isVisible(),false);
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);assert.deepEqual(remote,[]);
  fs.writeFileSync('release/2.0.0/browser-smoke.json',JSON.stringify({ok:true,frozenServer:true,publicDemo:true,import:true,export:true,offline:true,notesPersist:true,originGuard:true,tokenGuard:true,remoteRequests:remote.length,jsErrors:errors},null,2));
  console.log('Packaged EXE browser checks passed: import, settings, bilingual reader, persisted notes, export, offline mobile, request guards.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
