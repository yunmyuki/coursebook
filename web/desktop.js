(()=>{'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token='',courses=[],files=[],selected=new Set(),settings=null,role='parse',jobId=null,pollTimer,uploading=false;
let additionCourseId=null,additionPlan=null,additionResume=null;
const statusNames={complete:'已完成',review:'待复核表格',partial:'待补全',cancelled:'已暂停',blocked:'需检查 API',error:'处理失败',interrupted:'已中断'};
const stages={'extract':'提取本地文档','translation-context':'识别课程主题与翻译风格','document-parsing':'识别复杂页面','terminology':'统一课程术语','translation':'逐单元翻译','explanations':'历史解析阶段','page-complete':'已处理页面','page-error':'此页需要重试','blocked':'服务需要检查'};
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,6000);}
async function api(url,data){const response=await fetch(url,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Course-Token':token},body:data===undefined?undefined:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;}
function renderLibrary(){const query=$('#library-search').value.trim().toLowerCase(),rows=courses.filter(c=>c.title.toLowerCase().includes(query));$('#course-count').textContent=`全部课程 · ${courses.length}`;$('#course-nav').innerHTML=courses.map(c=>`<button data-open="${esc(c.id)}">▤ &nbsp;${esc(c.title)}</button>`).join('');$('#library-list').innerHTML=rows.length?rows.map(c=>`<article class="course-row"><span class="course-symbol">▤</span><div class="course-summary" data-open="${esc(c.id)}" tabindex="0" role="button"><strong>${esc(c.title)}</strong><div class="course-meta"><span>${c.pages} 页</span><span>${c.figures||0} 张原图</span><span>${new Date(c.updatedAt).toLocaleDateString('zh-CN')}</span><span class="status-tag ${esc(c.status)}">${statusNames[c.status]||'已保存'}${c.quality?.readingUncertain?' · 有待复核项':''}</span></div></div><div class="course-actions"><button data-open="${esc(c.id)}">阅读 ↗</button><button data-add-materials="${esc(c.id)}">＋ 材料</button><a href="${esc(c.downloadUrl)}" download>导出 ZIP</a>${!['complete','review'].includes(c.status)&&c.fileIds?.length?`<button data-resume="${esc(c.id)}">继续处理</button>`:''}</div></article>`).join(''):`<div class="empty-library"><strong>${query?'没有找到课程':'从第一份讲义开始'}</strong>${query?'试试其他关键词。':'导入一门课的讲义，生成可离线阅读的双语学习空间。'}${query?'':'<br><button class="primary-button" data-new>＋ 新建课程</button>'}</div>`;}
function showLibrary(){document.body.classList.remove('reading-course');$('#reader-frame').hidden=true;$('#library-view').hidden=false;$('#page-breadcrumb').textContent='学习空间 / 我的课程';$('#show-library').classList.add('active');}
function openCourse(id){const c=courses.find(c=>c.id===id);if(!c)return;document.body.classList.add('reading-course');$('#library-view').hidden=true;$('#reader-frame').hidden=false;$('#reader-frame').src=c.readerUrl;$('#page-breadcrumb').textContent='我的课程 / '+c.title;$('#show-library').classList.remove('active');}
function renderFiles(){$('#file-list').innerHTML=files.map(f=>`<label class="file-row"><input type="checkbox" data-file="${esc(f.id)}" ${selected.has(f.id)?'checked':''}><span>${esc(f.name)}</span><small>${(f.size/1048576).toFixed(1)} MB</small></label>`).join('');}
function resetAdditionPlan(){additionPlan=null;$('#addition-plan').hidden=true;$('#compile-start').textContent=additionCourseId?'预览插入位置 →':'开始编译 →';}
function newCourse(){if(!settings){toast('学习空间正在加载，请稍候。');return;}additionCourseId=null;selected.clear();resetAdditionPlan();$('#course-title').value='';$('#course-title').disabled=false;$('#import-dialog h2').textContent='新建课程';$('#extract-only').closest('label').hidden=false;renderFiles();$('#import-dialog').showModal();}
function addToCourse(cid){newCourse();additionCourseId=cid;$('#course-title').value=courses.find(c=>c.id===cid).title;$('#course-title').disabled=true;$('#import-dialog h2').textContent='添加课程材料';$('#extract-only').checked=false;$('#extract-only').closest('label').hidden=true;resetAdditionPlan();}
function renderAdditionPlan(){
  const p=additionPlan,positions=p.positions;
  const options=[...(positions.length?[{id:positions[0].id,label:'课程开头'}]:[]),...positions.map((c,i)=>({id:positions[i+1]?.id||'',label:'在「'+c.label+'」之后'})),...(!positions.length?[{id:'',label:'课程末尾'}]:[])];
  const sequence=[];
  for(const before of [...positions.map(c=>c.id),'']){for(const m of p.materials)if(m.beforeChapterId===before)sequence.push(`<li class="new-material">＋ ${esc(m.name)}</li>`);const ch=positions.find(c=>c.id===before);if(ch)sequence.push(`<li>${esc(ch.label)}</li>`);}
  $('#addition-plan').innerHTML=`<h3>确认插入位置</h3><p class="helper">根据文件编号和可提取文字给出建议。可调整位置与新材料顺序，确认后只处理新增材料。</p>${p.materials.map((m,i)=>`<div class="material-placement"><strong>${esc(m.name)}</strong><p class="helper">${esc(m.reason)}</p><label class="field">插入位置<select data-material-position="${i}">${options.map(o=>`<option value="${esc(o.id)}" ${o.id===m.beforeChapterId?'selected':''}>${esc(o.label)}</option>`).join('')}</select></label><div class="material-move"><button type="button" data-material-move="${i}" data-step="-1" ${i===0?'disabled':''}>↑ 上移</button><button type="button" data-material-move="${i}" data-step="1" ${i===p.materials.length-1?'disabled':''}>↓ 下移</button></div></div>`).join('')}<details class="material-preview" open><summary>加入后的阅读顺序</summary><ol>${sequence.join('')}</ol></details>`;
  $('#addition-plan').hidden=false;$('#compile-start').textContent='确认位置并添加 →';
}
async function startAddition(data){const result=await api('/api/materials/add',data);jobId=result.id;$('#import-dialog').close();showLibrary();$('#job-panel').hidden=false;pollJob();}
async function upload(list){uploading=true;$('#compile-start').disabled=true;try{for(const file of list){if(file.size>250*1048576)throw Error('单份讲义不能超过 250 MB');const response=await fetch('/api/upload',{method:'POST',headers:{'X-Course-Token':token,'X-Filename':encodeURIComponent(file.name)},body:file});const item=await response.json();if(!response.ok)throw Error(item.error);if(!files.some(f=>f.id===item.id))files.push(item);selected.add(item.id);if(!$('#course-title').value)$('#course-title').value=file.name.replace(/\.[^.]+$/,'');renderFiles();}}finally{uploading=false;$('#compile-start').disabled=false;$('#file-input').value='';}}
function captureProfile(){
  if(!settings)return;
  const p=settings.profiles[role], simple=settings.settingsMode==='simple';
  p.inherit=!simple&&role!=='parse'&&Boolean($('#inherit-profile')?.checked);
  if(!$('#profile-baseUrl'))return;
  const previousUrl=p.baseUrl;
  for(const key of ['provider','baseUrl','model'])if($('#profile-'+key))p[key]=$('#profile-'+key).value.trim();
  p.apiKey=$('#profile-apiKey')?.value||'';
  p.engine='vision';p.authScheme='Bearer';
  if(simple&&(!p.provider||p.baseUrl!==previousUrl))p.provider=providerForUrl(p.baseUrl);
}
function providerForUrl(url){try{return new URL(url).hostname==='api.siliconflow.cn'?'siliconflow':'openai';}catch{return 'openai';}}
function isLegacyProfile(p){return p.engine&&p.engine!=='vision';}
function requireVisualProfile(p){if(isLegacyProfile(p))throw Error('请先将旧解析连接更换为支持图片和文字的视觉模型。');}
function renderProfile(){
  const simple=settings.settingsMode==='simple';if(simple)role='parse';
  $('#settings-role-tabs').hidden=simple;
  $('#settings-mode-help').textContent=simple?'解析、翻译和AI 助手共用此连接。请选择支持图片和文字的视觉模型。':'文档解析使用视觉模型；翻译和AI 助手可共用连接，也可单独选择文本模型。';
  document.querySelectorAll('[data-settings-mode]').forEach(b=>b.classList.toggle('active',b.dataset.settingsMode===settings.settingsMode));
  const p=settings.profiles[role],inherit=!simple&&role!=='parse'&&p.inherit;
  const field=(key,label,placeholder='')=>`<label class="field">${label}<input id="profile-${key}" type="${key==='apiKey'?'password':key==='baseUrl'?'url':'text'}" value="${esc(p[key]||'')}" placeholder="${esc(placeholder)}" autocomplete="off"></label>`;
  const presetsHtml=simple?'':`<div class="profile-preset">${(role==='parse'?[['sf','硅基流动 · Qwen']]:[['sf','硅基流动 · Qwen'],['aliyun','阿里云 · 通义'],['deepseek','DeepSeek']]).map(([id,name])=>`<button type="button" data-preset="${id}">${name}</button>`).join('')}</div>`;
  const legacy=`<p class="helper" id="legacy-profile-notice">此连接使用旧版专用解析服务。请更换为视觉模型，再填写服务地址与模型名称；原连接在保存前保持不变。</p><button type="button" class="quiet-button" data-preset="sf">改用视觉模型</button>`;
  const fields=`${presetsHtml}${field('baseUrl','API 地址','https://api.siliconflow.cn/v1')}${field('apiKey','API Key',p.hasApiKey?'已保存；同一地址留空保留':'填写密钥')}${field('model','模型名称',role==='parse'?'支持图片和文字的模型':'支持文字的模型')}${!simple?`<details class="connection-options"><summary>接口兼容选项</summary><label class="field">接口格式<select id="profile-provider">${[['openai','OpenAI 兼容'],['siliconflow','硅基流动'],['anthropic','Anthropic 兼容']].map(([v,t])=>`<option value="${v}" ${p.provider===v?'selected':''}>${t}</option>`).join('')}</select></label></details>`:''}<p class="helper">${role==='parse'?'复杂页由视觉模型一次识别正文、表格和图片位置。图表从原页裁切，保留在正文中。':'本阶段只发送文字，可使用独立的文本模型。'} 密钥加密保存在本机。</p>`;
  $('#profile-fields').innerHTML=`${!simple&&role!=='parse'?`<label class="profile-inherit"><input id="inherit-profile" type="checkbox" ${inherit?'checked':''}>使用文档解析的同一连接</label>`:''}${inherit?'<p class="helper">本阶段共用文档解析连接，无需重复填写。</p>':isLegacyProfile(p)?legacy:fields}`;
  document.querySelectorAll('[data-role]').forEach(b=>b.classList.toggle('active',b.dataset.role===role));
}
const searchServices={
  bocha:{name:'博查',url:'https://open.bochaai.com/',help:'返回网页摘要，使用博查的独立搜索密钥。'},
  baidu:{name:'百度 · 千帆',url:'https://ai.baidu.com/ai-doc/AppBuilder/pmaxd1hvy',help:'使用千帆 AppBuilder 的百度搜索 API Key，查询网页片段；不是百度地图或通用 AK / SK。'},
  tavily:{name:'Tavily',url:'https://app.tavily.com/',help:'固定使用基础搜索，关闭自动升级深度和额外答案生成。'},
  exa:{name:'Exa',url:'https://dashboard.exa.ai/',help:'使用 Fast 搜索与相关片段，不启用深度研究或额外 AI 总结。'},
  brave:{name:'Brave Search',url:'https://api-dashboard.search.brave.com/',help:'使用 Search 套餐的密钥。额度、支付验证和网络可用性以服务商为准。'},
  serpapi:{name:'SerpApi',url:'https://serpapi.com/manage-api-key',help:'第三方服务商 SerpApi 提供所选引擎的搜索结果。填写 SerpApi Key，不是 Google、微软或百度账户的密钥。'}
};
let searchDrafts={},searchProvider='bocha';
function initSearchSettings(){
  const saved=settings.webSearch||{};searchProvider=Object.hasOwn(searchServices,saved.provider)?saved.provider:'bocha';
  searchDrafts=Object.fromEntries(Object.keys(searchServices).map(id=>[id,{...(saved.profiles?.[id]||{}),apiKey:'',clearKey:false}]));
  if(!saved.profiles)searchDrafts[searchProvider].hasApiKey=!!saved.hasApiKey;
  renderSearchSettings();$('#search-connection-result').textContent='测试使用固定示例，消耗一次该服务的搜索额度。';
}
function captureSearchSettings(){
  const p=searchDrafts[searchProvider];p.apiKey=$('#search-api-key').value.trim();p.clearKey=$('#clear-search-key').checked;
  if(searchProvider==='serpapi')p.engine=$('#search-engine').value;
}
function renderSearchSettings(){
  const p=searchDrafts[searchProvider],service=searchServices[searchProvider];
  $('#search-provider').value=searchProvider;$('#search-engine-field').hidden=searchProvider!=='serpapi';$('#search-engine').value=p.engine||'google';
  $('#search-key-label').textContent=service.name+' API Key';$('#search-api-key').value=p.apiKey||'';$('#clear-search-key').checked=!!p.clearKey;
  $('#search-api-key').placeholder=p.hasApiKey?'此服务已保存；留空保留':'填写此服务的密钥';
  $('#search-service-help').textContent=service.help;$('#search-key-link').href=service.url;
}
$('#search-provider').onchange=()=>{captureSearchSettings();searchProvider=$('#search-provider').value;renderSearchSettings();$('#search-connection-result').textContent='测试使用固定示例，消耗一次该服务的搜索额度。';};
$('#test-search-connection').onclick=async()=>{
  captureSearchSettings();const provider=searchProvider,button=$('#test-search-connection');button.disabled=true;$('#search-provider').disabled=true;$('#search-engine').disabled=true;
  $('#search-connection-result').textContent='正在测试 '+searchServices[provider].name+'…';
  try{const result=await api('/api/search/probe',{provider,...searchDrafts[provider]});$('#search-connection-result').textContent=result.message;}
  catch(e){$('#search-connection-result').textContent=e.message;}
  finally{button.disabled=false;$('#search-provider').disabled=false;$('#search-engine').disabled=false;}
};
let advancedDraft=null;
async function showSettings(){try{settings=await api('/api/settings');}catch(e){toast(e.message);return;}advancedDraft=null;role='parse';renderProfile();initSearchSettings();$('#connection-result').textContent='测试使用内置样本，会产生少量 API 用量。';$('#request-limit').value=settings.requestLimit||1000;$('#parse-mode').value=settings.parseMode;$('#workers').value=settings.workers;$('#settings-dialog').showModal();}
const presets={sf:{provider:'siliconflow',baseUrl:'https://api.siliconflow.cn/v1',model:'Qwen/Qwen3.8-27B',engine:'vision'},aliyun:{provider:'openai',baseUrl:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus',engine:'vision'},deepseek:{provider:'openai',baseUrl:'https://api.deepseek.com',model:'deepseek-flash',engine:'vision'}};
async function startCompile(data){const result=await api('/api/compile',data);jobId=result.id;$('#import-dialog').close();showLibrary();$('#job-panel').hidden=false;$('#job-title').textContent=data.title||'正在处理课程';pollJob();}
async function pollJob(){
  clearTimeout(pollTimer);
  try{
    const job=await api('/api/jobs/'+jobId),p=job.progress||{};$('#job-panel').hidden=false;$('#job-title').textContent=job.title;
    const done=job.processedPages||0,total=p.total||job.quality?.pages||0;
    $('#job-message').textContent=`${stages[p.stage]||'准备中'} · 已处理 ${done} / ${total||'…'} 页 · ${p.message||''}`;
    $('#job-fill').style.width=(total?Math.min(100,done/total*100):0)+'%';
    $('#job-events').textContent=(job.events||[]).map(e=>`${stages[e.stage]||e.stage} · ${e.current}/${e.total} · ${e.message}`).join('\n');
    $('#cancel-job').hidden=job.status!=='running';
    if(job.status==='running'){pollTimer=setTimeout(pollJob,2000);return;}
    const m=job.metrics||{};
    $('#job-message').textContent=(job.error||`${statusNames[job.status]||job.status}${job.quality?' · '+job.quality.readingTranslated+'/'+job.quality.readingUnits+' 个单元已翻译':''}`)+(m.requests!==undefined?` · 实际请求 ${m.requests} 次 · 缓存 ${m.cacheHits} 次`:'');
    additionResume=job.kind==='addition'&&!job.committed?job.additionRequest:null;
    $('#job-results').innerHTML=(job.readerUrl?`<button class="primary-button" data-open="${esc(job.id)}">打开课程 →</button> <a class="quiet-button" href="${esc(job.downloadUrl)}" download>导出静态网站</a>`:'')+(additionResume?'<button type="button" class="quiet-button" data-resume-addition>继续添加材料</button>':'');
    courses=await api('/api/library');renderLibrary();
  }catch(e){toast(e.message);}
}
$('#test-connection').onclick=async()=>{
  captureProfile();const button=$('#test-connection');button.disabled=true;$('#connection-result').textContent='正在验证所选连接…';
  try{const profile=settings.profiles[role].inherit?settings.profiles.parse:settings.profiles[role];requireVisualProfile(profile);const result=await api('/api/probe',{role:settings.profiles[role].inherit?'parse':role,profile});$('#connection-result').textContent=result.message;}
  catch(e){$('#connection-result').textContent=e.message;}finally{button.disabled=false;}
};
document.addEventListener('click',e=>{
  const b=e.target.closest('button,a,[data-open]');if(!b)return;
  if(b.dataset.close){$('#'+b.dataset.close).close();return;}
  if(b.dataset.open){openCourse(b.dataset.open);return;}
  if(b.hasAttribute('data-new')){newCourse();return;}
  if(b.dataset.addMaterials){addToCourse(b.dataset.addMaterials);return;}
  if(b.hasAttribute('data-resume-addition')&&additionResume){startAddition(additionResume).catch(e=>toast(e.message));return;}
  if(b.dataset.materialMove!==undefined){const i=Number(b.dataset.materialMove),j=i+Number(b.dataset.step);if(j>=0&&j<additionPlan.materials.length){[additionPlan.materials[i],additionPlan.materials[j]]=[additionPlan.materials[j],additionPlan.materials[i]];renderAdditionPlan();}return;}
  if(b.dataset.resume){const c=courses.find(c=>c.id===b.dataset.resume);startCompile({files:c.fileIds,title:c.title,explanations:false}).catch(e=>toast(e.message));return;}
  if(b.dataset.settingsMode){
    captureProfile();const mode=b.dataset.settingsMode;
    if(mode==='simple'&&settings.settingsMode!=='simple')advancedDraft=structuredClone(settings.profiles);
    else if(mode==='advanced'&&advancedDraft){settings.profiles={...advancedDraft,parse:settings.profiles.parse};advancedDraft=null;}
    settings.settingsMode=mode;role='parse';renderProfile();return;
  }
  if(b.dataset.role){captureProfile();role=b.dataset.role;renderProfile();return;}
  if(b.dataset.preset&&presets[b.dataset.preset]){captureProfile();settings.profiles[role]={...presets[b.dataset.preset],inherit:false,apiKey:'',hasApiKey:false};renderProfile();}
});
$('#profile-fields').addEventListener('change',e=>{if(e.target.id==='inherit-profile'){captureProfile();renderProfile();}});
$('#settings-form').addEventListener('submit',async e=>{e.preventDefault();try{captureProfile();captureSearchSettings();settings.webSearch={provider:searchProvider,profiles:searchDrafts};settings.requestLimit=Number($('#request-limit').value);if(settings.settingsMode==='simple')for(const r of ['translation','explanation'])settings.profiles[r]={inherit:true};for(const p of Object.values(settings.profiles))if(!p.inherit)requireVisualProfile(p);settings.workers=Number($('#workers').value);settings.parseMode=$('#parse-mode').value;settings=await api('/api/settings',settings);$('#settings-dialog').close();toast('模型配置已安全保存在本机。');}catch(e){toast(e.message);}});
$('#import-form').addEventListener('submit',async e=>{e.preventDefault();if(uploading)return;const b=$('#compile-start');b.disabled=true;try{if(additionCourseId){if(!additionPlan){additionPlan=await api('/api/materials/plan',{courseId:additionCourseId,files:[...selected]});renderAdditionPlan();}else await startAddition({...additionPlan,explanations:false});}else await startCompile({title:$('#course-title').value,files:[...selected],extractOnly:$('#extract-only').checked,explanations:false});}catch(e){toast(e.message);}finally{b.disabled=false;}});
$('#file-list').insertAdjacentHTML('afterend','<section id="addition-plan" hidden></section>');
$('#addition-plan').addEventListener('change',e=>{if(e.target.dataset.materialPosition!==undefined){additionPlan.materials[Number(e.target.dataset.materialPosition)].beforeChapterId=e.target.value;renderAdditionPlan();}});
$('#file-list').addEventListener('change',resetAdditionPlan);
$('#file-input').addEventListener('change',resetAdditionPlan);$('#dropzone').addEventListener('drop',resetAdditionPlan);
$('#file-list').addEventListener('change',e=>{if(e.target.dataset.file)e.target.checked?selected.add(e.target.dataset.file):selected.delete(e.target.dataset.file);});$('#file-input').addEventListener('change',e=>upload(e.target.files).catch(e=>toast(e.message)));$('#dropzone').addEventListener('dragover',e=>{e.preventDefault();$('#dropzone').classList.add('dragover');});$('#dropzone').addEventListener('dragleave',()=>$('#dropzone').classList.remove('dragover'));$('#dropzone').addEventListener('drop',e=>{e.preventDefault();$('#dropzone').classList.remove('dragover');upload(e.dataTransfer.files).catch(e=>toast(e.message));});
$('#new-course').onclick=$('#top-new').onclick=newCourse;$('#show-library').onclick=$('#back-library').onclick=showLibrary;$('#show-settings').onclick=showSettings;$('#import-settings').onclick=()=>{$('#import-dialog').close();showSettings();};$('#library-search').oninput=renderLibrary;$('#cancel-job').onclick=()=>api('/api/cancel/'+jobId,{}).then(()=>toast('当前请求结束后停止，已完成的页面会保留。')).catch(e=>toast(e.message));
$('#import-course').onclick=()=>$('#course-zip-input').click();$('#course-zip-input').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{toast('正在导入课程到本机…');const r=await fetch('/api/import-course',{method:'POST',headers:{'X-Course-Token':token},body:file});const value=await r.json();if(!r.ok)throw Error(value.error);courses=await api('/api/library');renderLibrary();openCourse(value.id);toast('课程已导入。');}catch(e){toast(e.message);}finally{e.target.value='';}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]'))showLibrary();if(e.key==='Enter'&&e.target.dataset.open)openCourse(e.target.dataset.open);});
async function init(){const status=await api('/api/status');token=status.token;courses=status.courses;files=status.files;settings=status.settings;$('#storage-path').textContent=status.dataPath;$('#office-status').textContent=status.converterAvailable?'Office 文档转换组件可用。':'PPT / PPTX 视觉渲染需要 LibreOffice 转换组件。';renderLibrary();const jobs=await api('/api/jobs');const running=jobs.find(j=>j.status==='running')||jobs.filter(j=>j.kind==='addition'&&!j.committed).sort((a,b)=>b.startedAt.localeCompare(a.startedAt))[0];if(running){jobId=running.id;pollJob();}}
init().catch(e=>toast(e.message));
})();
