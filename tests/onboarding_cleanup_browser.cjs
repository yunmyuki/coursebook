const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn,execFileSync}=require('node:child_process');
const {chromium,chromePath}=require('./runtime.cjs');
(async()=>{
 const python=process.env.TEST_PYTHON||'python',root=path.resolve('tmp','onboarding-qa-'+Date.now());fs.mkdirSync(root,{recursive:true});
 const port=8789,base='http://127.0.0.1:'+port;
 const packagedExe=process.env.COURSEBOOK_TEST_EXE;
 if(packagedExe)execFileSync(python,['tests/iteration_server.py',root,String(port),'--prepare-only']);
 const server=packagedExe?spawn(packagedExe,['--serve-only','--port',String(port),'--data-dir',root+'/workspace'],{windowsHide:true,stdio:['ignore','pipe','pipe']}):spawn(python,['tests/iteration_server.py',root,String(port)],{windowsHide:true,stdio:['ignore','pipe','pipe']});
 let logs='';server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 let browser;
 try{
  let ready=false;
  for(let i=0;i<200;i++){try{const status=await(await fetch(base+'/api/status')).json();if(path.resolve(status.dataPath)===path.resolve(root,'workspace')&&(packagedExe||logs.includes('ready'))){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}
  assert.ok(ready,'Isolated server failed to start: '+logs);
  browser=await chromium.launch({executablePath:chromePath,headless:true,args:['--no-proxy-server']});const page=await browser.newPage({viewport:{width:1440,height:950}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let probes=0;await page.route('**/api/probe',route=>{probes++;return route.fulfill({json:{message:'测试夹具：连接成功'}});});
  await page.goto(base);await page.waitForSelector('#onboarding-dialog[open]');assert.equal(probes,0);
  await page.screenshot({path:root+'/onboarding.png'});await page.click('#guide-skip');await page.reload();await page.waitForSelector('#show-onboarding');assert.equal(await page.locator('#onboarding-dialog').evaluate(e=>e.open),false);
  await page.click('#show-onboarding');await page.click('#guide-next');await page.click('#guide-action');await page.waitForSelector('#settings-dialog[open]');assert.equal(await page.locator('#guide-settings-note').isVisible(),true);
  await page.fill('#profile-apiKey','fixture-only-not-a-real-key');await page.click('#test-connection');await page.waitForFunction(()=>document.querySelector('#connection-result').textContent.includes('连接成功'));assert.equal(probes,1);
  await page.click('#settings-form button[type=submit]');await page.waitForSelector('#onboarding-dialog[open]');assert.match(await page.locator('#guide-progress').textContent(),/3 \/ 4/);
  await page.click('#guide-next');await page.click('#guide-next');await page.reload();await page.waitForSelector('#show-onboarding');assert.equal(await page.locator('#onboarding-dialog').evaluate(e=>e.open),false);
  const status=await(await page.request.get(base+'/api/status')).json();const headers={'X-Course-Token':status.token};
  const bad=await page.request.post(base+'/api/onboarding',{headers,data:{state:'complete',step:999,apiKey:'never-persist'}});assert.equal(bad.status(),400);
  const progress=await(await page.request.get(base+'/api/onboarding')).json();assert.deepEqual(progress,{state:'complete',step:3});
  const response=await page.request.post(base+'/api/import-course',{headers:{...headers,'Content-Type':'application/zip'},data:fs.readFileSync(root+'/fixture.zip')});assert.equal(response.ok(),true);const imported=await response.json();
  await page.goto(base+'/courses/'+imported.id+'/index.html');await page.waitForSelector('.unit');await page.waitForSelector('#edit-content-open');
  const id=await page.locator('.type-paragraph').first().getAttribute('id');
  await page.click('#new-note');await page.fill('#note-text','Note kept after editing');await page.click('#note-form button[type=submit]');
  await page.locator(`[data-review-unit="${id}"]`).first().click({force:true});await page.fill('#review-source','A corrected sentence for focused reading.');
  await page.click('#review-save-stay');await page.waitForFunction(()=>document.querySelector('#review-error').textContent.includes('已保存'));assert.equal(await page.inputValue('#review-translation'),'');assert.match(await page.locator('#review-history').textContent(),/previousTranslation/);
  await page.fill('#review-translation','用于专注阅读的修正句子。');await page.click('#review-save-stay');await page.waitForFunction(()=>document.querySelector('#review-error').textContent==='已保存。');
  await page.fill('#review-source','A corrected sentence for focused reading!');await page.click('#review-close');assert.equal(await page.locator('#review-dialog').evaluate(e=>e.open),true);assert.match(await page.locator('#review-error').textContent(),/未保存/);
  await page.check('#review-confirm-translation');await page.click('#review-save-stay');await page.waitForFunction(()=>document.querySelector('#review-error').textContent==='已保存。');assert.equal(await page.inputValue('#review-translation'),'用于专注阅读的修正句子。');
  await page.fill('#review-search','focused reading');assert.equal(await page.locator('#review-list button').count(),1);
  await page.waitForFunction(()=>document.querySelector('#review-page-image').naturalWidth>0);await page.screenshot({path:root+'/editing.png'});await page.click('#review-close');await page.reload();await page.waitForSelector('#edit-content-open');assert.match(await page.locator('#'+id).textContent(),/A corrected sentence/);
  await page.click('[data-tab=notes]');assert.match(await page.locator('#notebook-content').textContent(),/Note kept after editing/);
  await page.click('#cleanup-open');await page.waitForSelector('.cleanup-group');assert.equal(await page.locator('.cleanup-group').count(),1);await page.screenshot({path:root+'/cleanup.png'});
  await page.check('.cleanup-group input');await page.click('#cleanup-hide');await page.waitForSelector('.cleanup-archive');assert.equal(await page.locator('.cleanup-archive .source-copy').first().isVisible(),false);
  const course=await(await page.request.get(base+'/courses/'+imported.id+'/course.json')).json();assert.equal(course.quality.cleanedUnits,3);assert.equal(course.quality.unresolvedCandidates,0);
  const hidden=course.files[0].pages[0].units.find(u=>u.cleanupHidden);await page.evaluate(id=>document.dispatchEvent(new CustomEvent('course-navigate',{detail:id})),hidden.id);await page.waitForFunction(id=>document.getElementById(id)?.getClientRects().length,hidden.id);
  const exported=await page.request.get(base+'/download/'+imported.id+'.zip');assert.equal(exported.ok(),true);fs.writeFileSync(root+'/export.zip',await exported.body());
  execFileSync(python,['-c',"import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); assert 'FUDAN' not in z.read('transcript.md').decode(); z.extractall(sys.argv[2])",root+'/export.zip',root+'/offline']);
  const offline=await browser.newPage();await offline.goto('file:///'+(root+'/offline/index.html').replaceAll('\\','/'));await offline.waitForSelector('.unit');assert.match(await offline.locator('#'+id).textContent(),/用于专注阅读/);assert.equal(await offline.locator('[data-review-unit]').count(),0);assert.equal(await offline.locator('.cleanup-archive .source-copy').first().isVisible(),false);await offline.close();
  await page.click('#cleanup-open');await page.waitForSelector('.cleanup-group');await page.click('#cleanup-restore-all');await page.waitForFunction(()=>!document.querySelector('.cleanup-archive'));assert.equal(await page.locator('.source-copy').filter({hasText:'FUDAN'}).count(),1);
  await page.setViewportSize({width:390,height:844});await page.click('#edit-content-open');await page.waitForFunction(()=>document.querySelector('#review-page-image').naturalWidth>0);assert.ok((await page.locator('#review-page-image').boundingBox()).height>100);await page.screenshot({path:root+'/mobile-editing.png'});await page.locator('#review-save-stay').scrollIntoViewIfNeeded();assert.ok(await page.locator('#review-save-stay').isVisible());assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);fs.writeFileSync(root+'/result.json',JSON.stringify({ok:true,probes,errors,onboarding:true,editing:true,cleanup:true,offline:true,notesPreserved:true},null,2));console.log('PASS '+root);
 }finally{if(browser)await browser.close();server.kill();fs.writeFileSync(root+'/server.log',logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
