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
  p.engine=$('#profile-engine')?.value||p.engine||'vision';p.authScheme=$('#profile-authScheme')?.value||p.authScheme||'Bearer';
  if($('#profile-ocrFlavor'))p.ocrFlavor=$('#profile-ocrFlavor').value;
  if($('#profile-maxOcrRegions'))p.maxOcrRegions=Number($('#profile-maxOcrRegions').value);
  if(simple&&(!p.provider||p.baseUrl!==previousUrl))p.provider=providerForUrl(p.baseUrl);
}
document.addEventListener('change',e=>{if(e.target.id==='profile-engine'){captureProfile();renderProfile();}});
function providerForUrl(url){try{return new URL(url).hostname==='api.siliconflow.cn'?'siliconflow':'openai';}catch{return 'openai';}}
function isLegacyProfile(p){return p.engine&&!['vision','glm-ocr','paddle-layout','local-layout-ocr'].includes(p.engine);}
function requireVisualProfile(p){if(isLegacyProfile(p))throw Error('请先将旧解析连接更换为支持图片和文字的视觉模型。');}
function renderProfile(){
  const simple=settings.settingsMode==='simple';if(simple&&role==='explanation')role='translation';
  $('#settings-role-tabs').hidden=false;
  $('[data-role="parse"]').textContent=simple?'1 · OCR 识别':'文档解析';
  $('[data-role="translation"]').textContent=simple?'2 · 翻译与助手':'翻译';
  $('[data-role="explanation"]').hidden=simple;
  $('#settings-mode-help').textContent=simple?'需要两个模型：OCR 负责读讲义，文本模型负责翻译与回答。同一服务商的 Key 可以填入两组，但模型名称应分别选择。':'解析、翻译和 AI 助手分别配置；专用 OCR 模型不能用于翻译或聊天。';
  $('#test-connection').textContent=simple?(role==='parse'?'测试 OCR 连接':'测试翻译与助手连接'):'测试当前连接';
  document.querySelectorAll('[data-settings-mode]').forEach(b=>b.classList.toggle('active',b.dataset.settingsMode===settings.settingsMode));
  const p=settings.profiles[role],inherit=!simple&&role!=='parse'&&p.inherit;
  const field=(key,label,placeholder='')=>`<label class="field">${label}<input id="profile-${key}" type="${key==='apiKey'?'password':key==='baseUrl'?'url':'text'}" value="${esc(p[key]||'')}" placeholder="${esc(placeholder)}" autocomplete="off"></label>`;
  const presetsHtml=`<div class="profile-preset">${(role==='parse'?(simple?[['hybrid','填入硅基 OCR 预设']]:[['hybrid','本地版面 · 硅基 OCR（默认）'],['sf','硅基流动 · Qwen'],['glm','智谱 · GLM-OCR 版面服务']]):[['sf','硅基流动 · Qwen'],['aliyun','阿里云 · 通义'],['deepseek','DeepSeek']]).map(([id,name])=>`<button type="button" data-preset="${id}">${name}</button>`).join('')}</div>`;
  const legacy=`<p class="helper" id="legacy-profile-notice">此连接使用旧版专用解析服务。请更换为视觉模型，再填写服务地址与模型名称；原连接在保存前保持不变。</p><button type="button" class="quiet-button" data-preset="sf">改用视觉模型</button>`;
  const engineField=!simple&&role==='parse'?`<label class="field">解析接口<select id="profile-engine">${[['local-layout-ocr','本地版面 + 云端区域 OCR（默认）'],['vision','通用视觉模型'],['glm-ocr','GLM-OCR · 完整版面解析'],['paddle-layout','PaddleOCR-VL · 完整解析服务']].map(([v,t])=>`<option value="${v}" ${p.engine===v?'selected':''}>${t}</option>`).join('')}</select></label>${p.engine==='paddle-layout'?`<label class="field">认证方式<select id="profile-authScheme"><option value="Bearer" ${p.authScheme!=='token'?'selected':''}>Bearer</option><option value="token" ${p.authScheme==='token'?'selected':''}>token</option></select></label><p class="helper">填写完整 /layout-parsing 服务地址；不能使用硅基流动的 OCR 聊天端点。</p>`:''}`:'';
  const fields=`${presetsHtml}${engineField}${field('baseUrl','API 地址','https://api.siliconflow.cn/v1')}${field('apiKey','API Key',p.hasApiKey?'已保存；同一地址留空保留':'填写密钥')}${field('model','模型名称',role==='parse'?'例如 PaddlePaddle/PaddleOCR-VL-1.5':'选择文本对话模型，不要填写 OCR 模型')}${!simple?`<details class="connection-options"><summary>接口兼容选项</summary><label class="field">接口格式<select id="profile-provider">${[['openai','OpenAI 兼容'],['siliconflow','硅基流动'],['anthropic','Anthropic 兼容']].map(([v,t])=>`<option value="${v}" ${p.provider===v?'selected':''}>${t}</option>`).join('')}</select></label></details>`:''}<p class="helper">${role==='parse'?(p.engine==='local-layout-ocr'?'本地版面与区域 OCR 分工；图表保留原图，翻译和 AI 助手单独配置文本模型。':p.engine==='vision'?'复杂页由视觉模型识别，另做本地版面校验；图表保留原图。':'使用完整文档解析接口返回文字、表格和区域位置；翻译与 AI 助手请单独配置文本模型。'):'本阶段只发送文字，可使用独立的文本模型。'} 密钥加密保存在本机。</p>`;
  $('#profile-fields').innerHTML=`${!simple&&role!=='parse'?`<label class="profile-inherit"><input id="inherit-profile" type="checkbox" ${inherit?'checked':''}>使用文档解析的同一连接</label>`:''}${inherit?'<p class="helper">本阶段共用文档解析连接，无需重复填写。</p>':isLegacyProfile(p)?legacy:fields}`;
  document.querySelectorAll('[data-role]').forEach(b=>b.classList.toggle('active',b.dataset.role===role));
  if(!inherit&&p.engine==='local-layout-ocr'){
    $('#profile-fields').insertAdjacentHTML('beforeend',`<details class="connection-options"><summary>OCR 区域识别选项</summary><label class="field">区域识别协议<select id="profile-ocrFlavor">${[['auto','根据模型名称自动选择'],['paddle','PaddleOCR-VL'],['glm','GLM-OCR · 区域聊天接口'],['deepseek','DeepSeek-OCR'],['vision','通用视觉模型']].map(([v,t])=>`<option value="${v}" ${(p.ocrFlavor||'auto')===v?'selected':''}>${t}</option>`).join('')}</select></label><label class="field">单页 OCR 区域上限<input id="profile-maxOcrRegions" type="number" min="1" max="100" value="${Number(p.maxOcrRegions)||32}"></label><p class="helper">每页先在本机检测版面；可靠文字层直接复用，表格、公式和图像按区域识别。请求计入总上限。GLM 官方 /layout_parsing 属于完整服务，应在高级配置选择对应接口。</p></details><div class="helper" id="layout-component-status" role="status">正在检查本地版面组件…</div><button type="button" id="install-layout-component" class="quiet-button">下载版面组件 · 131 MB</button> <label class="quiet-button">导入模型<input id="import-layout-component" type="file" accept=".onnx" hidden></label>`);
    refreshLayoutComponent();
  }
}
let layoutPoll;
async function refreshLayoutComponent(){
  clearTimeout(layoutPoll);
  try{const s=await api('/api/layout-component'),el=$('#layout-component-status');if(!el)return;
    el.textContent=s.downloading?`正在下载版面组件 · ${Math.round(s.downloadedBytes/s.bytes*100)}%`:s.error||(s.ready?'PP-DocLayoutV3 已就绪 · CPU 本地运行':!s.runtimeAvailable?'当前开发环境缺少 ONNX Runtime，请安装 requirements-layout.txt。':`尚未安装模型。可下载，或导入官方固定版本 inference.onnx。`);
    $('#install-layout-component').disabled=Boolean(s.downloading||s.ready);
    $('#import-layout-component').disabled=Boolean(s.downloading);
    if(s.downloading)layoutPoll=setTimeout(refreshLayoutComponent,1500);
  }catch(e){if($('#layout-component-status'))$('#layout-component-status').textContent=e.message;}
}
document.addEventListener('click',async e=>{if(e.target.id==='install-layout-component'){try{e.target.disabled=true;await api('/api/layout-component/install',{});refreshLayoutComponent();}catch(error){toast(error.message);e.target.disabled=false;}}});
document.addEventListener('change',async e=>{if(e.target.id==='import-layout-component'&&e.target.files[0]){const file=e.target.files[0];try{e.target.disabled=true;const response=await fetch('/api/layout-component/import',{method:'POST',headers:{'X-Course-Token':token},body:file});const result=await response.json();if(!response.ok)throw Error(result.error);toast('版面组件校验通过，已安装。');}catch(error){toast(error.message);}finally{refreshLayoutComponent();}}});
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
const presets={hybrid:{provider:'siliconflow',baseUrl:'https://api.siliconflow.cn/v1',model:'PaddlePaddle/PaddleOCR-VL-1.5',engine:'local-layout-ocr',ocrFlavor:'paddle',maxOcrRegions:32},glm:{provider:'openai',baseUrl:'https://open.bigmodel.cn/api/paas/v4',model:'glm-ocr',engine:'glm-ocr'},sf:{provider:'siliconflow',baseUrl:'https://api.siliconflow.cn/v1',model:'Qwen/Qwen3.8-27B',engine:'vision'},aliyun:{provider:'openai',baseUrl:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus',engine:'vision'},deepseek:{provider:'openai',baseUrl:'https://api.deepseek.com',model:'deepseek-flash',engine:'vision'}};
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
    if(mode==='simple'&&settings.settingsMode!=='simple'){
      advancedDraft=structuredClone(settings.profiles);
      if(settings.profiles.translation.inherit){
        // Materialize an inherited text connection only when the parser is a general model.
        // A saved parse key remains in its original role; re-enter it for the new text role.
        const p=settings.profiles.parse;
        settings.profiles.translation=p.engine==='vision'?{...structuredClone(p),inherit:false,hasApiKey:false}:{...presets.sf,inherit:false,apiKey:'',hasApiKey:false};
      }
    }
    else if(mode==='advanced'&&advancedDraft){settings.profiles.explanation=advancedDraft.explanation;advancedDraft=null;}
    settings.settingsMode=mode;role='parse';renderProfile();return;
  }
  if(b.dataset.role){captureProfile();role=b.dataset.role;renderProfile();$('#connection-result').textContent='测试当前所选连接；不会自动调用模型。';return;}
  if(b.dataset.preset&&presets[b.dataset.preset]){captureProfile();const old=settings.profiles[role],preset=presets[b.dataset.preset],same=old.baseUrl===preset.baseUrl;settings.profiles[role]={...preset,inherit:false,apiKey:same?old.apiKey:'',hasApiKey:same&&old.hasApiKey};renderProfile();}
});
$('#profile-fields').addEventListener('change',e=>{if(e.target.id==='inherit-profile'){captureProfile();renderProfile();}});
$('#settings-form').addEventListener('submit',async e=>{e.preventDefault();try{captureProfile();captureSearchSettings();settings.webSearch={provider:searchProvider,profiles:searchDrafts};settings.requestLimit=Number($('#request-limit').value);if(settings.settingsMode==='simple')settings.profiles.explanation=structuredClone(settings.profiles.translation);for(const p of Object.values(settings.profiles))if(!p.inherit)requireVisualProfile(p);for(const r of ['translation','explanation']){const p=settings.profiles[r].inherit?settings.profiles.parse:settings.profiles[r];if(p.engine!=='vision'||/ocr/i.test(p.model))throw Error('翻译与助手需要文本对话模型，不能使用专用 OCR 模型。');}settings.workers=Number($('#workers').value);settings.parseMode=$('#parse-mode').value;settings=await api('/api/settings',settings);$('#settings-dialog').close();toast('模型配置已安全保存在本机。');if(guideAwaitSettings){guideAwaitSettings=false;guideTip.hidden=true;await openGuide(2);}}catch(e){toast(e.message);}});
$('#import-form').addEventListener('submit',async e=>{e.preventDefault();if(uploading)return;const b=$('#compile-start');b.disabled=true;try{if(additionCourseId){if(!additionPlan){additionPlan=await api('/api/materials/plan',{courseId:additionCourseId,files:[...selected]});renderAdditionPlan();}else await startAddition({...additionPlan,explanations:false});}else await startCompile({title:$('#course-title').value,files:[...selected],extractOnly:$('#extract-only').checked,explanations:false});}catch(e){toast(e.message);}finally{b.disabled=false;}});
$('#file-list').insertAdjacentHTML('afterend','<section id="addition-plan" hidden></section>');
$('#addition-plan').addEventListener('change',e=>{if(e.target.dataset.materialPosition!==undefined){additionPlan.materials[Number(e.target.dataset.materialPosition)].beforeChapterId=e.target.value;renderAdditionPlan();}});
$('#file-list').addEventListener('change',resetAdditionPlan);
$('#file-input').addEventListener('change',resetAdditionPlan);$('#dropzone').addEventListener('drop',resetAdditionPlan);
$('#file-list').addEventListener('change',e=>{if(e.target.dataset.file)e.target.checked?selected.add(e.target.dataset.file):selected.delete(e.target.dataset.file);});$('#file-input').addEventListener('change',e=>upload(e.target.files).catch(e=>toast(e.message)));$('#dropzone').addEventListener('dragover',e=>{e.preventDefault();$('#dropzone').classList.add('dragover');});$('#dropzone').addEventListener('dragleave',()=>$('#dropzone').classList.remove('dragover'));$('#dropzone').addEventListener('drop',e=>{e.preventDefault();$('#dropzone').classList.remove('dragover');upload(e.dataTransfer.files).catch(e=>toast(e.message));});
$('#new-course').onclick=$('#top-new').onclick=newCourse;$('#show-library').onclick=$('#back-library').onclick=showLibrary;$('#show-settings').onclick=showSettings;$('#import-settings').onclick=()=>{$('#import-dialog').close();showSettings();};$('#library-search').oninput=renderLibrary;$('#cancel-job').onclick=()=>api('/api/cancel/'+jobId,{}).then(()=>toast('当前请求结束后停止，已完成的页面会保留。')).catch(e=>toast(e.message));
$('#import-course').onclick=()=>$('#course-zip-input').click();$('#course-zip-input').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{toast('正在导入课程到本机…');const r=await fetch('/api/import-course',{method:'POST',headers:{'X-Course-Token':token},body:file});const value=await r.json();if(!r.ok)throw Error(value.error);courses=await api('/api/library');renderLibrary();openCourse(value.id);toast('课程已导入。');}catch(e){toast(e.message);}finally{e.target.value='';}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]'))showLibrary();if(e.key==='Enter'&&e.target.dataset.open)openCourse(e.target.dataset.open);});

const apiSetupHelp=`<p><strong>第一次配置，推荐从硅基流动开始（不是广告）。</strong>一个账号可同时调用 OCR 和文本模型，便于入门。PaddleOCR-VL-1.5 在官方价格页标为免费；翻译与助手模型可能收费，免费范围、限流和模型可用性以控制台实时显示为准。</p>
<ol class="api-setup-steps"><li><strong>注册并登录。</strong>打开 <a href="https://cloud.siliconflow.cn/" target="_blank" rel="noopener noreferrer">硅基流动控制台 ↗</a>，按平台要求完成实名认证。这里是管理账号的网站，不要把它填进 API 地址。</li>
<li><strong>创建自己的 Key。</strong>进入 <a href="https://cloud.siliconflow.cn/account/ak" target="_blank" rel="noopener noreferrer">API 密钥 ↗</a>，点击「新建 API 密钥」，备注可填 Coursebook，再复制完整密钥。Key 相当于调用模型的密码，不是登录密码；不要发给别人或放进截图。</li>
<li><strong>填写「1 · OCR 识别」。</strong>在简单配置中点击「填入硅基 OCR 预设」，地址为 <code>https://api.siliconflow.cn/v1</code>，模型为 <code>PaddlePaddle/PaddleOCR-VL-1.5</code>，将 Key 粘贴到 API Key 框。本地版面组件需显示「已就绪」；轻量环境可按提示下载。</li>
<li><strong>填写「2 · 翻译与助手」。</strong>点击「硅基流动 · Qwen」预设，填入同一个 Key。在 <a href="https://cloud.siliconflow.cn/models" target="_blank" rel="noopener noreferrer">模型广场 ↗</a> 确认预设模型可用及价格，也可以复制其他文本对话模型的完整 ID。这里不能再填写 OCR 模型；免费 OCR 不代表翻译和问答也免费。</li>
<li><strong>分别测试，再保存。</strong>在两个标签内分别点击测试连接，成功后保存。测试会发起少量请求，按服务商规则计费；先用几页讲义试用，再处理整门课。收费模型需要账户有可用额度。</li></ol>
<p class="helper">API 地址是应用调用模型的入口，模型名称决定使用哪个模型，API Key 证明你的调用权限。两组可以使用不同服务商；高级配置还可将翻译和助手拆开。联网搜索是额外功能，可稍后设置。</p>
<p class="helper">401/403：检查 Key、实名认证与权限；404：检查 API 地址和完整模型名；429：检查限流或额度，稍后重试或降低同时处理页数。不要重复充值来解决地址或模型名错误。</p>
<p class="helper"><a href="https://docs.siliconflow.cn/docs/userguide/quickstart" target="_blank" rel="noopener noreferrer">官方获取 Key 教程 ↗</a> · <a href="https://siliconflow.cn/pricing" target="_blank" rel="noopener noreferrer">官方实时价格 ↗</a>。推荐仅为降低上手门槛，你可以自由选择兼容服务。</p>`;
const apiHelp=document.createElement('details');apiHelp.className='connection-options api-setup-help';apiHelp.id='api-setup-help';apiHelp.innerHTML='<summary>第一次配置？从注册账号到填入 API Key</summary>'+apiSetupHelp;$('#settings-mode-help').after(apiHelp);
let guideProgress={state:'new',step:0},guideAwaitSettings=false;
const guide=document.createElement('dialog');guide.id='onboarding-dialog';guide.className='onboarding-dialog';guide.setAttribute('aria-labelledby','guide-title');
guide.innerHTML=`<div class="dialog-heading"><div><span id="guide-progress" class="helper"></span><h2 id="guide-title"></h2></div><button type="button" id="guide-dismiss" class="icon-button" aria-label="暂时跳过教程">×</button></div><div id="guide-body"></div><p id="guide-error" role="status"></p><div class="dialog-footer"><button type="button" id="guide-prev" class="quiet-button">上一步</button><button type="button" id="guide-skip" class="quiet-button">暂时跳过</button><button type="button" id="guide-action" class="quiet-button"></button><button type="button" id="guide-next" class="primary-button">下一步</button></div>`;document.body.append(guide);
const guideSteps=[
 ['欢迎使用 Coursebook','<p>把课程讲义，变成可以读、查、问、记的双语学习空间。</p><div class="guide-grid"><p><strong>读</strong>原文与译文逐段对照，随时查看原页。</p><p><strong>查</strong>按目录或全文搜索定位知识。</p><p><strong>问</strong>选中正文，向右侧 AI 助手提问。</p><p><strong>记</strong>高亮、笔记和书签跟随对应正文。</p></div><p class="helper">课程和学习记录留在本机。只有主动使用云端识别、翻译或助手时，相关内容才发送给配置的服务。</p>'],
 ['配置两个模型：OCR ＋ 翻译与助手',apiSetupHelp],
 ['先用几页讲义试一试','<ol><li>新建课程，导入 PDF、PPTX 或 PPT，确认顺序。</li><li>先用少量页面检查识别和翻译；请求上限可控制用量。</li><li>打开课程，对照原页检查疑点。PPT 渲染需要 LibreOffice。</li><li>在「页面清洗」预览并勾选重复页码与固定页尾标注；可随时恢复。</li></ol><p class="helper">还没有 API Key？可勾选「仅提取原文」，或导入已经编译好的课程 ZIP。</p>'],
 ['开始阅读，也可以修正正文','<p>正文旁的 ✎ 或页角「编辑」可修改原文、译文、表格单元与公式；顶部「编辑正文」可以搜索并定位所有内容。</p><p>只修正原文也能保存，旧译文会标记为待更新。需要模型翻译时，主动生成草稿并确认。原始文本和修改历史始终保留。</p><p>选中文字可提问或高亮，右侧记录笔记。支持左右/上下双语对照和字体切换；导出 ZIP 后可直接打开 index.html 离线阅读。</p><p class="helper">纯静态网站不连接本地应用，正文编辑和页面清洗请在 Coursebook 中完成，再重新导出。</p>']
];
const guideHelp=document.createElement('button');guideHelp.id='show-onboarding';guideHelp.className='side-action';guideHelp.innerHTML='<span>？</span>使用教程';guideHelp.setAttribute('aria-label','使用教程');$('#show-settings').after(guideHelp);
const guideTip=document.createElement('aside');guideTip.id='guide-settings-note';guideTip.hidden=true;guideTip.className='guide-settings-note';guideTip.textContent='配置指引：先填 OCR，再填「翻译与助手」，两组分别测试后保存。硅基流动可共用一个 Key，但要选不同模型。展开下方教程可查看注册和获取 Key 的每一步。';$('#settings-form .dialog-heading').after(guideTip);
async function rememberGuide(state,step){guideProgress=await api('/api/onboarding',{state,step});}
function renderGuide(){const step=guideProgress.step;$('#guide-progress').textContent=`使用教程 · ${step+1} / 4`;$('#guide-title').textContent=guideSteps[step][0];$('#guide-body').innerHTML=guideSteps[step][1];$('#guide-prev').hidden=step===0;$('#guide-action').hidden=![1,3].includes(step);$('#guide-action').textContent=step===1?'打开模型配置':'新建课程';$('#guide-next').textContent=step===3?'完成教程':'下一步';$('#guide-error').textContent='';}
async function openGuide(step=guideProgress.step){try{await rememberGuide('active',step);renderGuide();if(!guide.open)guide.showModal();}catch(e){toast(e.message);}}
async function dismissGuide(){try{await rememberGuide('dismissed',guideProgress.step);guide.close();}catch(e){$('#guide-error').textContent=e.message;}}
guideHelp.onclick=()=>openGuide(guideProgress.state==='complete'?0:guideProgress.step);
$('#guide-dismiss').onclick=$('#guide-skip').onclick=dismissGuide;guide.addEventListener('cancel',e=>{e.preventDefault();dismissGuide();});
$('#guide-prev').onclick=()=>openGuide(Math.max(0,guideProgress.step-1));
$('#guide-next').onclick=async()=>{if(guideProgress.step<3){await openGuide(guideProgress.step+1);return;}try{await rememberGuide('complete',3);guide.close();}catch(e){$('#guide-error').textContent=e.message;}};
$('#guide-action').onclick=async()=>{try{if(guideProgress.step===1){guide.close();guideAwaitSettings=true;await showSettings();guideTip.hidden=false;}else{await rememberGuide('complete',3);guide.close();newCourse();}}catch(e){toast(e.message);}};
async function initGuide(){guideProgress=await api('/api/onboarding');if(guideProgress.state==='active'||guideProgress.state==='new')await openGuide();}

async function init(){const status=await api('/api/status');token=status.token;courses=status.courses;files=status.files;settings=status.settings;$('#storage-path').textContent=status.dataPath;$('#workspace-origin').textContent='课程与笔记读取自此电脑的工作区，更新或重新下载程序会保留已有记录。';$('#workspace-origin-path').textContent=status.dataPath;$('#office-status').textContent=status.converterAvailable?'Office 文档转换组件可用。':'PPT / PPTX 视觉渲染需要 LibreOffice 转换组件。';renderLibrary();const jobs=await api('/api/jobs');const running=jobs.find(j=>j.status==='running')||jobs.filter(j=>j.kind==='addition'&&!j.committed).sort((a,b)=>b.startedAt.localeCompare(a.startedAt))[0];if(running){jobId=running.id;pollJob();}await initGuide();}
init().catch(e=>toast(e.message));
})();
