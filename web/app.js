/* Offline reader: no network, no dynamic code, all document strings are escaped. */
(async function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const validRange = (h, text) => Number.isInteger(h.start) && Number.isInteger(h.end) && h.start >= 0 && h.end > h.start && h.end <= text.length;
  const cleanBullet = (text,u) => u.type==='bullet' ? String(text).replace(/^\s*[•●▪◦]\s*/,'') : text;
  function reanchorHighlight(h,text){
    if(validRange(h,text)&&text.slice(h.start,h.end)===h.text)return {...h,stale:false};
    const at=typeof h.text==='string'&&h.text.length?text.indexOf(h.text):-1;
    if(at>=0&&text.indexOf(h.text,at+1)<0)return {...h,start:at,end:at+h.text.length,stale:false};
    return {...h,stale:true};
  }
  function highlighted(text, ranges) {
    const valid = ranges.filter(h => !h.stale&&validRange(h,text)).sort((a,b) => a.start-b.start);
    let end=0, html='';
    for (const h of valid) {
      const start=Math.max(end,h.start);
      if(h.end<=start) continue;
      html+=esc(text.slice(end,start))+'<mark class="user-highlight">'+esc(text.slice(start,h.end))+'</mark>';
      end=h.end;
    }
    return html+esc(text.slice(end));
  }
  const unique = values => [...new Set(values)];
  const safeUrl = url => /^(https?:|mailto:)/i.test(String(url||'')) ? url : null;
  // Pure helpers are available to the regression suite without a browser.
  if (typeof module !== 'undefined' && module.exports) { module.exports={esc,highlighted,validRange,safeUrl,reanchorHighlight,cleanBullet}; return; }
  const C = window.COURSE_DATA;
  if (!C?.files?.length) { document.getElementById('lecture-content').textContent='没有课程数据。请使用本地编译器生成课程，并保留 course-data.js。'; return; }
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const pageMap = new Map(), unitMap = new Map(), figureMap=new Map(), figureOrigins=new Map(), anchorMap = new Map(), anchorAliases=new Map(), explanationMap=new Map(), related=new Map(), chapters=[];
  const allPages=C.files.flatMap(f=>f.pages);
  C.files.forEach(f=>{
    anchorMap.set(f.id,f.pages[0]);
    f.chapters.forEach(ch=>{chapters.push({...ch,file:f});anchorMap.set(ch.id,pageMap.get(ch.pageIds[0])||f.pages.find(p=>p.id===ch.pageIds[0]));});
    f.pages.forEach(p=>{
      p.file=f;pageMap.set(p.id,p);anchorMap.set(p.id,p);
      p.units.forEach(u=>{unitMap.set(u.id,u);anchorMap.set(u.id,p);if(u.tableId)anchorMap.set(u.tableId,p);});
      (p.figures||[]).forEach(f=>{figureMap.set(f.id,f);anchorMap.set(f.id,p);});
      Object.entries(p.tableAliases||{}).forEach(([oldId,newId])=>{anchorMap.set(oldId,p);anchorAliases.set(oldId,newId);});
    });
  });
  if(Array.isArray(C.readingOrder)){
    const order=new Map(C.readingOrder.map((id,i)=>[id,i]));chapters.sort((a,b)=>(order.get(a.id)??Infinity)-(order.get(b.id)??Infinity));
    const pagesInOrder=new Map(chapters.flatMap(c=>c.pageIds).map((id,i)=>[id,i]));allPages.sort((a,b)=>(pagesInOrder.get(a.id)??Infinity)-(pagesInOrder.get(b.id)??Infinity));
  }
  for(const p of allPages)for(const u of p.units){
    if(u.reviewOnly||u.type==='table-cell')continue;
    const refs=(u.figureIds||[]).filter(id=>figureMap.has(id));
    if(!refs.length&&Array.isArray(u.position))for(const f of p.figures||[]){
      const a=u.position,b=f.position;if(!Array.isArray(b))continue;
      const overlap=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));
      const nearChart=f.kind==='chart'&&u.origin!=='text-layer'&&u.sourceText.length<100&&a[0]>=b[0]-.09&&a[1]>=b[1]-.07&&a[2]<=b[2]+.03&&a[3]<=b[3]+.04;
      if(f.relatedContentIds?.includes(u.id)||nearChart||overlap/Math.max(.000001,(a[2]-a[0])*(a[3]-a[1]))>=.6)refs.push(f.id);
    }
    if(refs.length||u.contentOrigin==='figure-transcription')figureOrigins.set(u.id,{refs,label:'图中文字提取'});
  }
  C.explanations.forEach(e=>{explanationMap.set(e.id,e);anchorMap.set(e.id,anchorMap.get(e.relatedContentIds[0]));e.relatedContentIds.forEach(id=>related.set(id,[...(related.get(id)||[]),e]));});
  const storageKey='course-compiler:v1:'+C.id;
  let storageWarning=false;
  const freshState=()=>({version:1,courseId:C.id,notes:[],highlights:[],bookmarks:[],read:[],mode:'bilingual',font:15,lastAnchor:null});
  let state=freshState();
  function validateState(value) {
    if(!value || value.courseId!==C.id || value.version!==1) throw Error('这份备份属于其他课程或格式不兼容。');
    for(const key of ['notes','highlights','bookmarks','read']) if(!Array.isArray(value[key]))throw Error('备份数据不完整。');
    if(value.notes.length+value.highlights.length>50000)throw Error('备份数据过大。');
    const normalized={...freshState(),...value};
    normalized.notes=value.notes.filter(n=>typeof n.id==='string'&&anchorMap.has(n.contentId)&&typeof n.text==='string'&&n.text.length<=20000);
    normalized.highlights=value.highlights.filter(h=>typeof h.id==='string'&&typeof h.text==='string'&&unitMap.has(h.contentId)&&['source','translation'].includes(h.layer)).map(h=>{const u=unitMap.get(h.contentId);return reanchorHighlight(h,cleanBullet(h.layer==='source'?u.sourceText:u.translatedText||'',u));});
    normalized.bookmarks=value.bookmarks.filter(b=>typeof b.id==='string'&&anchorMap.has(b.contentId));
    normalized.read=unique(value.read.filter(id=>pageMap.has(id)));
    if(!['bilingual','original','translation'].includes(normalized.mode))normalized.mode='bilingual';
    normalized.font=[15,17,19].includes(normalized.font)?normalized.font:15;
    return normalized;
  }
  try { const data=localStorage.getItem(storageKey);if(data)state=validateState(JSON.parse(data)); } catch(e) { storageWarning=true; }
  let hostToken=null;
  if(location.protocol==='http:'&&/^\/courses\/course-[a-f0-9]{16}\//.test(location.pathname)){
    try{
      const [status,saved]=await Promise.all([fetch('/api/status').then(r=>r.json()),fetch('/api/learning/'+C.id).then(r=>r.json())]);
      hostToken=status.token;
      if(hostToken&&$('#learning-storage-label'))$('#learning-storage-label').textContent='个人记录保存在本机文件';
      if(saved.state&&(!state.savedAt||!saved.state.savedAt||saved.state.savedAt>=state.savedAt))state=validateState(saved.state);
    }catch(e){storageWarning=true;}
  }
  let currentChapter, currentPage, notebookTab='assistant', selectedExplanation=null, insightFilter=null, outlineMode='outline', observer, navigationLock=false, noteTarget=null, editingNote=null, selectedRanges=[];
  function save() { state.savedAt=Date.now();try {localStorage.setItem(storageKey,JSON.stringify(state));} catch(e){storageWarning=true;toast('浏览器无法保存记录，请及时导出备份。');}
    if(hostToken){const body=JSON.stringify(state);fetch('/api/learning/'+C.id,{method:'POST',headers:{'Content-Type':'application/json','X-Course-Token':hostToken},body,keepalive:new Blob([body]).size<60000}).then(r=>{if(!r.ok)throw Error();}).catch(()=>toast('本地文件保存未成功，浏览器副本仍保留，请导出备份。'));}
  }
  function toast(text) { $('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,3500); }
  const uuid = () => globalThis.crypto?.randomUUID?.() || 'local-'+Date.now()+'-'+Math.random().toString(36).slice(2);
  const date = () => new Date().toISOString();
  const pageLabel = p => `Lecture ${String(p.file.order).padStart(2,'0')} · Page ${p.number}`;
  function displayText(u,layer) { return cleanBullet(layer==='source'?u.sourceText:u.translatedText||'',u); }
  function drawText(u,layer) {
    const text=displayText(u,layer);
    return highlighted(text,state.highlights.filter(h=>h.contentId===u.id&&h.layer===layer));
  }
  function unitHTML(u) {
    const figureOrigin=figureOrigins.get(u.id);
    const same=u.translationStatus==='complete'&&u.sourceText===u.translatedText&&(['table-cell','formula','code'].includes(u.type)||figureOrigin)&&!state.highlights.some(h=>h.contentId===u.id&&h.layer==='translation');
    let source=drawText(u,'source');
    if(u.latex&&window.katex)try{source=katex.renderToString(u.latex,{displayMode:true,throwOnError:true,trust:false,strict:'warn'});}catch(e){source=drawText(u,'source');}
    const translated=u.translationStatus==='complete' ? `<div class="translation-copy" data-layer="translation" lang="zh-CN">${u.latex?source:drawText(u,'translation')}</div>` : '<em class="translation-pending" title="译文尚未完成，请对照原页">待译</em>';
    return `<div class="unit type-${esc(u.type)}${same?' same-copy':''}${figureOrigin?' figure-derived':''}${figureOrigin&&u.sourceText.length<20?' figure-label':''}" id="${esc(u.id)}" data-unit="${esc(u.id)}" style="--level:${Math.min(6,Math.max(0,u.level||0))}" tabindex="-1">
      ${figureOrigin?`<div class="figure-origin"><span>${esc(figureOrigin.label)}</span><button ${figureOrigin.refs.length?`data-jump="${esc(figureOrigin.refs[0])}"`:`data-source="${esc(anchorMap.get(u.id).id)}"`} title="对照原图">查看图表 ↗</button></div>`:''}
      <div class="source-copy" data-layer="source" lang="en">${source}</div>${translated}
      ${u.uncertain?'<span class="uncertain-tag" title="识别存疑，请对照原页" aria-label="识别存疑，请对照原页">!</span>':''}

      <div class="unit-actions"><button data-ask="${esc(u.id)}" title="用此内容向助手提问" aria-label="用此内容向助手提问">✧</button><button data-note="${esc(u.id)}" title="为此段落写笔记" aria-label="为此段落写笔记">＋</button><button data-bookmark="${esc(u.id)}" title="收藏此段落" aria-label="收藏此段落">☆</button><button data-copy="${esc(u.id)}" title="复制定位链接" aria-label="复制定位链接">↗</button><button data-raw="${esc(u.id)}" title="查看识别原文与修正记录" aria-label="查看识别原文与修正记录">≡</button></div>
    </div>`;
  }
  function headingHTML(group) {
    const members=group.contentIds.map(id=>unitMap.get(id)).filter(Boolean);
    const pieces=layer=>members.map((u,index)=>{
      const text=layer==='translation'&&u.translationStatus!=='complete'?'译文待核对':drawText(u,layer);
      const id=layer==='source'?u.id:'translation-'+u.id;
      const actions=`<span class="unit-actions"><button data-note="${esc(u.id)}" aria-label="为标题写笔记">＋</button><button data-bookmark="${esc(u.id)}" aria-label="收藏标题">☆</button><button data-copy="${esc(u.id)}" aria-label="复制标题定位">↗</button><button data-raw="${esc(u.id)}" aria-label="查看此处识别记录">≡</button></span>`;
      const previous=members[index-1];const join=index&&(layer==='source'||!/[\u3400-\u9fff]$/.test(previous?.translatedText||'')||!/^\p{Script=Han}/u.test(u.translatedText||''))?' ':'';
      return `${group.lineBreakBefore?.includes(u.id)?'<br>':join}<span class="heading-piece" id="${esc(id)}" data-unit="${esc(u.id)}" tabindex="-1"><span class="${layer==='source'?'source':'translation'}-copy" data-layer="${layer}">${text}</span>${actions}</span>`;
    }).join('');
    return `<div class="heading-group" id="${esc(group.id)}" data-heading="${esc(group.id)}"><h3 class="heading-original" lang="en">${pieces('source')}</h3><div class="heading-translated" lang="zh-CN">${pieces('translation')}</div>${members.some(u=>u.uncertain)?'<span class="uncertain-tag" title="识别存疑，请对照原页" aria-label="识别存疑，请对照原页">!</span>':''}</div>`;
  }
  function tableHTML(tableId,units) {
    const rows=new Map(),occupied=new Set(),emitted=new Set();
    units.forEach(u=>{const row=Math.max(0,Math.min(1000,u.row||0));rows.set(row,[...(rows.get(row)||[]),u]);});
    const width=Math.min(100,Math.max(...units.map(u=>(u.col||0)+(u.colSpan||1))));
    const html=[...rows.entries()].sort((a,b)=>a[0]-b[0]).map(([ri,row])=>{
      const cells=new Map();row.forEach(u=>{const col=Math.max(0,Math.min(99,u.col||0));cells.set(col,[...(cells.get(col)||[]),u]);});let out='';
      for(let ci=0;ci<width;ci++){
        if(occupied.has(ri+':'+ci))continue;
        const group=cells.get(ci);if(!group){out+='<td></td>';continue;}const u=group[0];
        const rs=Math.max(1,Math.min(100,u.rowSpan||1)),cs=Math.max(1,Math.min(width-ci,u.colSpan||1));
        for(let r=ri;r<ri+rs;r++)for(let c=ci;c<ci+cs;c++)occupied.add(r+':'+c);
        out+=`<td rowspan="${rs}" colspan="${cs}">${group.map(unitHTML).join('')}</td>`;
        group.forEach(v=>emitted.add(v.id));
      }return '<tr>'+out+'</tr>';
    }).join('');
    const remainder=units.filter(u=>!emitted.has(u.id));
    return `<div class="table-wrap" id="${esc(tableId)}"><table aria-label="原讲义表格，中英逐单元格对照"><tbody>${html}</tbody></table>${remainder.length?`<div class="page-status">单元格位置待核对：</div>${remainder.map(unitHTML).join('')}`:''}<button class="table-note" data-note="${esc(tableId)}" title="为整个表格写笔记" aria-label="为整个表格写笔记">＋ 笔记</button></div>`;
  }
  function pageHTML(p) {
    const renderedTables=new Set(),renderedHeadings=new Set(),renderedFigureText=new Set(),renderedFigures=new Set();
    const headingGroups=new Map((p.headingGroups||[]).map(g=>[g.id,g]));
    const main=p.units.filter(u=>!u.reviewOnly),candidates=p.units.filter(u=>u.reviewOnly);
    const flow=[...main,...(p.figures||[]).map(f=>({...f,isFigure:true}))];
    const ordered=flow.filter(u=>Number.isFinite(u.readingOrder));
    const order=u=>Number.isFinite(u.readingOrder)?u.readingOrder:ordered.length?ordered.reduce((a,b)=>Math.abs((a.position?.[1]??0)-(u.position?.[1]??0))<Math.abs((b.position?.[1]??0)-(u.position?.[1]??0))?a:b).readingOrder+.5:(u.position?.[1]??2);
    flow.sort((a,b)=>order(a)-order(b));
    const drawFigure=u=>{
      if(renderedFigures.has(u.id))return '';renderedFigures.add(u.id);
      return `<figure class="lecture-figure" id="${esc(u.id)}" tabindex="-1"><img src="${esc(u.image)}" width="${Number(u.width)}" height="${Number(u.height)}" loading="lazy" alt="原讲义第 ${p.number} 页图表或图片" data-source="${esc(p.id)}"><figcaption><span>原讲义${u.kind==='chart'?'图表':'图片'} · Page ${p.number}</span><button data-note="${esc(u.id)}">＋ 笔记</button><button data-copy="${esc(u.id)}">复制定位 ↗</button></figcaption>${u.relatedContentIds?.length?`<div class="figure-links">${u.relatedContentIds.slice(0,3).map((id,i)=>`<button data-jump="${esc(id)}">对应文字 ${i+1} ↗</button>`).join('')}</div>`:''}</figure>`;
    };
    const units=flow.map(u=>{
      if(u.isFigure)return drawFigure(u);
      if(u.type==='table-cell'&&u.tableId){if(renderedTables.has(u.tableId))return '';renderedTables.add(u.tableId);return tableHTML(u.tableId,main.filter(v=>v.type==='table-cell'&&v.tableId===u.tableId));}
      const origin=figureOrigins.get(u.id),figureId=origin?.refs[0];
      if(figureId){
        if(renderedFigureText.has(figureId))return '';renderedFigureText.add(figureId);
        const members=flow.filter(v=>!v.isFigure&&figureOrigins.get(v.id)?.refs[0]===figureId);
        const label='图中文字提取';
        return drawFigure(figureMap.get(figureId))+`<aside class="figure-text-group" aria-label="${label}"><div class="figure-origin"><span>${label}</span><button data-jump="${esc(figureId)}">查看图表 ↗</button></div>${members.map(unitHTML).join('')}</aside>`;
      }
      if(u.headingGroupId&&headingGroups.has(u.headingGroupId)&&!headingGroups.get(u.headingGroupId).contentIds.some(id=>figureOrigins.has(id))){if(renderedHeadings.has(u.headingGroupId))return '';renderedHeadings.add(u.headingGroupId);return headingHTML(headingGroups.get(u.headingGroupId));}
      return unitHTML(u);
    }).join('');
    const review=candidates.length?`<details class="ocr-review"><summary>展开图表 OCR 核对记录 · ${candidates.length} 个单元</summary><p class="small muted">保留的自动识别候选，可能含扫描噪点、重复文字或错位数字。已核对内容在正文中显示；其余请结合原页使用。所有候选均可搜索、定位和记笔记。</p>${candidates.map(unitHTML).join('')}</details>`:'';
    const isRead=state.read.includes(p.id), bookmark=state.bookmarks.some(b=>b.contentId===p.id);
    const incomplete=p.visualStatus!=='complete'||p.transcriptionStatus!=='complete'||main.some(u=>u.translationStatus!=='complete');
    const hasUncertainty=main.some(u=>u.uncertain);
    return `<section class="slide" id="${esc(p.id)}" data-page="${esc(p.id)}" aria-label="${esc(pageLabel(p))}">
      <div class="slide-header"><span class="slide-number">PAGE ${String(p.number).padStart(3,'0')}</span><span class="slide-divider">/</span><span class="slide-source" title="${esc(p.source.file)}">${esc(p.source.file)}</span><div class="slide-tools"><button data-source="${esc(p.id)}">查看原页 ↗</button><button data-bookmark="${esc(p.id)}" class="${bookmark?'saved':''}" aria-label="${bookmark?'移除':'添加'}页面书签">${bookmark?'★':'☆'}</button><button data-read="${esc(p.id)}" aria-label="${isRead?'标记为未读':'标记为已学'}" title="${isRead?'已学完此页':'标记学完此页'}"><span class="read-check ${isRead?'checked':''}">${isRead?'✓':''}</span></button></div></div>
      ${units||'<div class="page-status">此页为图片内容，文字识别待完成。原始页面已保留如下。</div>'}
      ${p.links?.some(l=>safeUrl(l.url))?`<div class="small muted">讲义中的链接：${p.links.filter(l=>safeUrl(l.url)).map(l=>`<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.url)} ↗</a>`).join(' · ')}</div>`:''}
      <details ${!main.length?'open':''}><summary class="original-toggle">原始页面 · 视觉核对</summary><figure class="original-preview"><img src="${esc(p.image)}" width="${Number(p.width)||612}" height="${Number(p.height)||792}" loading="lazy" alt="${esc(p.source.file)} 第 ${p.number} 页原始图像" data-source="${esc(p.id)}"><figcaption>原讲义截图 · ${esc(pageLabel(p))} · 原图中的信息以讲义为准</figcaption></figure></details>${review}
    </section>`;
  }
  function renderChapter(chapterId) {
    currentChapter=chapters.find(c=>c.id===chapterId)||chapters[0];
    const ch=currentChapter, first=pageMap.get(ch.pageIds[0]);
    const title=ch.title.replace(/^(Part|Chapter|Lecture|Week)\s*(\d+)\s*[:.：-]\s*/i,'');
    const part=ch.title.match(/^(Part|Chapter|Lecture|Week)\s*(\d+)/i)?.[0]||'COURSE OVERVIEW';
    $('#chapter-intro').innerHTML=`<div class="eyebrow"><span class="part-tag">${esc(part)}</span><span>LECTURE ${String(ch.file.order).padStart(2,'0')}</span></div><h2>${esc(title)}</h2><div class="chapter-description"><span>${ch.pageIds.length} 页讲义</span><span>Page ${first.number}–${pageMap.get(ch.pageIds.at(-1)).number}</span><span>原讲义顺序</span></div>`;
    const issues=ch.pageIds.map(id=>pageMap.get(id)).filter(p=>p.reviewRequired||p.warnings.length||p.visualStatus!=='complete'||p.transcriptionStatus!=='complete'||p.units.some(u=>!u.reviewOnly&&(u.uncertain||u.translationStatus!=='complete')));
    $('#chapter-intro').insertAdjacentHTML('beforeend',`<details class="chapter-reading-notes"><summary>阅读说明${issues.length?' · '+issues.length+' 页待核对':''}</summary><div><p>双语逐单元对应；相同的数字与公式合并显示，可在阅读设置中展开。</p><p>图中文字提取以原图为准；选中文字，可向右侧 AI 助手提问。</p>${C.translationContext?`<p>翻译主题：${esc(C.translationContext.subject)}。${esc(C.translationContext.style)}${C.translationContext.warning?' '+esc(C.translationContext.warning):''}</p>`:''}${issues.map(p=>`<p><button data-jump="${esc(p.id)}">Page ${p.number} ↗</button> ${esc(p.reviewReasons?.join(' ')||p.warnings.join('；')||'有待译或存疑内容，请对照原页。')}</p>`).join('')}</div></details>`);
    $('#lecture-content').innerHTML=ch.pageIds.map(id=>pageHTML(pageMap.get(id))).join('');
    const ci=chapters.indexOf(ch);
    $('#chapter-pagination').innerHTML=`<div class="chapter-pagination">${ci>0?`<button data-jump="${esc(chapters[ci-1].id)}">← 上一章节</button>`:'<span></span>'}${ci<chapters.length-1?`<button data-jump="${esc(chapters[ci+1].id)}">下一章节 →</button>`:'<span>已到课程末尾</span>'}</div>`;
    observer?.disconnect();
    observer=new IntersectionObserver(entries=>{
      if(navigationLock)return;
      const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);
      if(visible[0])setCurrentPage(pageMap.get(visible[0].target.id));
    },{root:$('#reader-scroll'),rootMargin:'-10% 0px -62% 0px',threshold:0});
    $$('.slide').forEach(p=>observer.observe(p));
    renderOutline();
  }
  function setCurrentPage(page) {
    if(!page)return;
    const changed=currentPage?.id!==page.id;
    currentPage=page;
    $('#breadcrumb').textContent=`Lecture ${String(page.file.order).padStart(2,'0')}  /  Page ${String(page.number).padStart(3,'0')}`;
    $$('.page-link').forEach(el=>{const active=el.dataset.jump===page.id;el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','location');else el.removeAttribute('aria-current');});
    if(changed){state.lastAnchor=page.id;save();if(!selectedExplanation){insightFilter=null;renderNotebook();}}
  }
  function navigate(id, options={}) {
    id=anchorAliases.get(id)||id;
    const e=explanationMap.get(id);
    const page=anchorMap.get(id);
    if(!page){toast('此定位已不存在。请在目录中选择页面。');return false;}
    navigationLock=true;
    if(currentChapter?.id!==page.chapterId)renderChapter(page.chapterId);
    setCurrentPage(page);
    if(e)id=e.relatedContentIds[0];
    if(!options.noHash){history.pushState(null,'','#'+encodeURIComponent(id));state.lastAnchor=id;save();}
    requestAnimationFrame(()=>{
      let target=document.getElementById(id)||document.getElementById(page.id);
      if(target&&!target.getClientRects().length)target=document.getElementById('translation-'+id)||target;
      for(let parent=target?.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
      target?.scrollIntoView({behavior:options.instant?'instant':'smooth',block:'start'});
      target?.classList.remove('flash');void target?.offsetWidth;target?.classList.add('flash');
      setTimeout(()=>{navigationLock=false;target?.classList.remove('flash');},options.instant?100:1100);
    });
    if(innerWidth<=700)$('#sidebar').classList.remove('mobile-open');
    if(options.closeNotebook&&innerWidth<=1020)$('#notebook').classList.remove('mobile-open');
    return true;
  }
  function renderOutline() {
    if(outlineMode==='topics'){
      $('#outline').innerHTML=allPages.map(p=>`<button class="topic-card" data-jump="${esc(p.id)}">${esc(p.title)}<small>${esc(pageLabel(p))}</small></button>`).join('');
      return;
    }
    $('#outline').innerHTML=chapters.map((ch,index)=>{
      const f=ch.file,header=chapters[index-1]?.file.id!==f.id?`<button class="file-title text-button" data-jump="${esc(ch.id)}" title="${esc(f.name)}">LECTURE ${String(f.order).padStart(2,'0')} · ${esc(f.name)}</button>`:'';
      const complete=ch.pageIds.filter(id=>state.read.includes(id)).length,active=ch.id===currentChapter?.id;
      return header+`<details class="chapter-nav ${active?'active':''}" ${active?'open':''} data-chapter="${esc(ch.id)}"><summary><span class="chapter-name">${esc(ch.title)}</span><span class="chapter-progress">${complete}/${ch.pageIds.length}</span></summary><button class="chapter-start text-button" data-jump="${esc(ch.id)}">从章节开头阅读 ↗</button>${ch.pageIds.map(id=>{const p=pageMap.get(id);return `<a class="page-link ${currentPage?.id===id?'active':''}" href="#${esc(id)}" data-jump="${esc(id)}"><span class="page-num">${String(p.number).padStart(2,'0')}</span><span class="page-title">${esc(p.title)}</span>${state.read.includes(id)?'<span class="read-dot">✓</span>':''}</a>`;}).join('')}</details>`;
    }).join('');
  }
  function renderProgress(){const count=state.read.length,pct=Math.round(count/allPages.length*100);$('#progress-text').textContent=pct+'%';$('#progress-fill').style.width=pct+'%';$('#progress-sub').textContent=`已学 ${count} / ${allPages.length} 页 · 点击页码旁方框标记`;}
  function recordContext(id) { return unitMap.get(id)?.sourceText||explanationMap.get(id)?.title||figureMap.get(id)?.caption||(figureMap.has(id)?'讲义原图 · Page '+figureMap.get(id).source.page:null)||pageMap.get(id)?.title||'表格笔记'; }
  function renderNotebook() {
    $$('.notebook-tabs button').forEach(b=>{const active=b.dataset.tab===notebookTab;b.classList.toggle('active',active);b.setAttribute('aria-selected',active);});
    const box=$('#notebook-content');
    box.hidden=notebookTab==='assistant';$('#assistant-panel').hidden=notebookTab!=='assistant';$('#note-editor').hidden=notebookTab!=='notes'||!noteTarget;
    $('#notebook').classList.toggle('assistant-active',notebookTab==='assistant');
    if(notebookTab==='assistant'){box.innerHTML='';document.dispatchEvent(new CustomEvent('assistant-activate'));return;
    }else if(notebookTab==='notes'){
      box.innerHTML='<div class="notebook-kicker">PERSONAL NOTES · 我的想法</div>'+(state.notes.length?[...state.notes].sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).map(n=>`<article class="record-card"><button class="record-context" data-jump="${esc(n.contentId)}">↗ ${esc(recordContext(n.contentId))}</button><div class="record-text">${esc(n.text)}</div><div class="record-actions"><time>${esc(new Date(n.updatedAt).toLocaleDateString())}</time><button data-edit-note="${esc(n.id)}">编辑</button><button class="delete" data-delete-note="${esc(n.id)}">删除</button></div></article>`).join(''):'<div class="empty-state"><span class="empty-symbol">✎</span>把知识变成自己的理解<br>选中文字或点击段落旁的 ＋ 写笔记。<br><button class="button" id="empty-new-note" style="margin-top:20px">＋ 写下第一条笔记</button></div>');
    }else if(notebookTab==='highlights'){
      box.innerHTML='<div class="notebook-kicker">HIGHLIGHTS · 阅读痕迹</div>'+(state.highlights.length?state.highlights.map(h=>`<article class="record-card"><button class="record-context" data-jump="${esc(h.contentId)}">${esc(pageLabel(anchorMap.get(h.contentId)))} · ${h.layer==='source'?'原文':'译文'} ↗</button><div class="record-text"><mark>${esc(h.text)}</mark></div>${h.stale?'<p class="small muted">正文已更新，原高亮文字已保留；请重新选择对应范围。</p>':''}<div class="record-actions"><button data-note="${esc(h.contentId)}">＋ 写笔记</button><button class="delete" data-delete-highlight="${esc(h.id)}">移除高亮</button></div></article>`).join(''):'<div class="empty-state"><span class="empty-symbol">▱</span>选中正文中的文字<br>即可添加高亮，留下阅读痕迹。</div>');
    }else{
      box.innerHTML='<div class="notebook-kicker">BOOKMARKS · 再读一遍</div>'+(state.bookmarks.length?state.bookmarks.map(b=>`<article class="record-card"><button class="record-context" data-jump="${esc(b.contentId)}">${esc(pageLabel(anchorMap.get(b.contentId)))} ↗</button><div class="record-text">${esc(recordContext(b.contentId))}</div><div class="record-actions"><button data-jump="${esc(b.contentId)}">回到正文</button><button class="delete" data-delete-bookmark="${esc(b.id)}">移除</button></div></article>`).join(''):'<div class="empty-state"><span class="empty-symbol">☆</span>给想再读一遍的页面或段落<br>添加一枚书签。</div>');
    }
  }
  function showNotebook(){if(innerWidth<=1020)$('#notebook').classList.add('mobile-open');else document.body.classList.remove('right-hidden');}
  function openNote(id,editId=null){
    if(noteTarget&&$('#note-text').value.trim()&&($('#note-text').value!==noteInitial)){notebookTab='notes';renderNotebook();showNotebook();toast('请先保存或取消正在编辑的笔记。');return false;}
    noteTarget=id||currentPage?.id;editingNote=editId;$('#note-context').textContent=recordContext(noteTarget);$('#note-text').value=editId?state.notes.find(n=>n.id===editId)?.text||'':'';noteInitial=$('#note-text').value;$('#note-dialog-title').textContent=editId?'编辑笔记':'写下你的想法';notebookTab='notes';renderNotebook();showNotebook();$('#note-text').focus();return true;
  }
  function askSelection(){notebookTab='assistant';renderNotebook();showNotebook();document.dispatchEvent(new CustomEvent('assistant-selection',{detail:selectedRanges}));}
  let noteInitial='';
  $('#cancel-note').onclick=()=>{noteTarget=null;editingNote=null;$('#note-text').value='';renderNotebook();};
  document.addEventListener('assistant-save-note',e=>{if(openNote(e.detail.contentId))$('#note-text').value=e.detail.text;});
  function toggleBookmark(id){const exists=state.bookmarks.find(b=>b.contentId===id);if(exists)state.bookmarks=state.bookmarks.filter(b=>b!==exists);else state.bookmarks.push({id:uuid(),contentId:id,createdAt:date()});save();renderNotebook();$$(`[data-bookmark="${CSS.escape(id)}"]`).forEach(b=>{if(b.closest('.slide-tools')){b.textContent=exists?'☆':'★';b.classList.toggle('saved',!exists);}});toast(exists?'已移除书签':'已添加书签');}
  function sourceDialog(page,unit){
    $('#source-title').textContent=`${page.source.file} · 第 ${page.number} 页`;
    const sourceLink=page.file.sourceUrl+'#page='+page.number;
    $('#source-body').innerHTML=`<p><a href="${esc(sourceLink)}" target="_blank" rel="noopener">打开原始文件 ↗</a></p>${unit?`<p class="small">稳定定位：${esc(unit.id)}<br>提取方式：${esc(unit.origin)} · 坐标：${esc(JSON.stringify(unit.position))}</p><h3>原始识别文本</h3><pre>${esc(unit.rawText)}</pre>${unit.corrections?.length?`<h3>修正记录</h3><pre>${esc(JSON.stringify(unit.corrections,null,2))}</pre>`:''}`:''}<img src="${esc(page.image)}" alt="第 ${page.number} 页原图"><details><summary class="original-toggle">查看该页完整文字层</summary><pre>${esc(page.rawText)}</pre></details>`;
    $('#source-dialog').showModal();
    if(hostToken&&unit&&!unit.reviewOnly)$('#source-body').insertAdjacentHTML('afterbegin',`<button class="button" data-review-unit="${esc(unit.id)}">修正原文 / 译文</button>`);
    if(hostToken&&page.reviewRequired)$('#source-body').insertAdjacentHTML('beforeend',`<p><button class="button" data-review-page="${esc(page.id)}">已对照原图，确认本页表格复核完成</button></p>`);
    if(unit?.uncertaintyReason)$('#source-body').insertAdjacentHTML('afterbegin',`<p class="page-status">${esc(unit.uncertaintyReason)}</p>`);
    if(unit?.artifactReason)$('#source-body').insertAdjacentHTML('afterbegin',`<p class="page-status">${esc(unit.artifactReason)}</p>`);
    if(unit?.translationNotes?.length)$('#source-body').insertAdjacentHTML('beforeend',`<h3>译文核对说明（独立于讲义正文）</h3><p>${unit.translationNotes.map(esc).join('；')}</p>`);
    if(unit?.translationCorrections?.length)$('#source-body').insertAdjacentHTML('beforeend',`<details><summary class="original-toggle">译文术语统一记录</summary><pre>${esc(JSON.stringify(unit.translationCorrections,null,2))}</pre></details>`);
    if(page.ocrRawText)$('#source-body').insertAdjacentHTML('beforeend',`<details><summary class="original-toggle">原始 OCR 识别记录（未清洗）</summary><pre>${esc(page.ocrRawText)}</pre></details>`);
    if(page.ocrDraft)$('#source-body').insertAdjacentHTML('beforeend',`<details><summary class="original-toggle">${esc(page.ocrModel||'OCR')} 识别草稿（未经校验）</summary><p class="small">草稿可能遗漏列或误读符号；正文使用后续视觉核对结果。</p><pre>${esc(page.ocrDraft)}</pre></details>`);
  }
  function search(query){
    query=query.trim().toLocaleLowerCase();
    if(!query){$('#search-results').innerHTML='<div class="empty-state">输入概念、关键词或一句原文，找到它在课程中的位置。</div>';return;}
    const terms=query.split(/\s+/);
    const results=[];
    for(const u of unitMap.values())if(terms.every(t=>(u.sourceText+' '+(u.translatedText||'')).toLocaleLowerCase().includes(t)))results.push({id:u.id,text:u.sourceText,translation:u.translatedText,page:anchorMap.get(u.id),type:'原文 / 译文'});

    $('#search-results').innerHTML=`<p class="small muted" style="padding:8px 14px">找到 ${results.length} 处结果${results.length>100?' · 显示前 100 条，请缩小搜索范围':''}</p>`+results.slice(0,100).map(r=>`<button class="search-result" data-search-result="${esc(r.id)}"><span class="result-meta">${esc(pageLabel(r.page))} · ${esc(r.type)}</span><span class="result-text">${esc(r.text)}</span>${r.translation?`<span class="result-text muted">${esc(r.translation)}</span>`:''}</button>`).join('');
  }
  function openSearch(){$('#search-dialog').showModal();$('#search-input').focus();search($('#search-input').value);}
  function showQuality(){
    const q=C.quality;
    const processed=q.visualValidated===q.pages&&q.transcriptionValidated===q.pages&&(q.readingTranslated??q.translated)===(q.readingUnits??q.units);
    const stats=[[q.pages,'原始页数'],[q.readingUnits??q.units,'正文内容单元'],[`${q.readingTranslated??q.translated}/${q.readingUnits??q.units}`,'正文翻译配对'],[`${q.visualValidated}/${q.pages}`,'视觉校验'],[`${q.transcriptionValidated}/${q.pages}`,'转录核对'],[q.readingUncertain??q.uncertain,'正文待复核单元']];
    $('#quality-body').innerHTML=`<p>${q.complete?'所有页面已通过处理流程。':processed?'全部页面的处理步骤已完成，仍有下列疑点或结构问题需要复核。':'此课程仍有未完成的识别、核对或翻译步骤。'}自动校验不等于人工逐字确认；存疑内容应对照原页复核。</p><div class="quality-grid">${stats.map(([v,k])=>`<div class="quality-stat"><strong>${esc(v)}</strong><span>${esc(k)}</span></div>`).join('')}</div><p class="small">${q.formulaCount} 个已识别公式 · ${q.tableCells} 个表格单元格（含历史记录） · ${q.explanations} 条历史解析记录（保留旧定位）<br>另保留 ${q.ocrCandidates||0} 个历史识别记录，其中 ${q.unresolvedCandidates||0} 个尚未处理；已替换或确认重复的记录不计入正文翻译配对。<br>原文 ID 保留、来源引用、译文配对与解析定位：${q.errors.length?esc(q.errors.join('；')):'结构检查通过'}</p><div class="quality-issues">${allPages.filter(p=>p.warnings.length||p.visualStatus!=='complete'||p.transcriptionStatus!=='complete'||p.units.some(u=>!u.reviewOnly&&(u.uncertain||u.translationStatus!=='complete')||u.reviewOnly&&!u.supersededBy&&!u.rejectedArtifact)).map(p=>`<button data-quality-jump="${esc(p.id)}">Page ${p.number} · ${esc(p.title)}<br>${esc(p.warnings.join('；')||'存在待核对或未译内容')}</button>`).join('')||'暂无页面级警告。'}</div>`;
    $('#quality-dialog').showModal();
  }
  function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
  function backupMarkdown(){const lines=[`# ${C.title} · 我的学习笔记`,'',`导出时间：${date()}`,''];for(const n of state.notes){const p=anchorMap.get(n.contentId);lines.push(`## ${pageLabel(p)}`,'',`来源：${p.source.file} · #${n.contentId}`,'',`> ${recordContext(n.contentId).replace(/\n/g,'\n> ')}`,'',n.text,'');}lines.push('## 高亮','');for(const h of state.highlights)lines.push(`- ${h.text}（${pageLabel(anchorMap.get(h.contentId))} · #${h.contentId}）`);download('coursebook-学习笔记.md',lines.join('\n'),'text/markdown;charset=utf-8');}
  function captureSelection(){
    const s=getSelection();if(!s||s.isCollapsed||!s.rangeCount)return;
    const range=s.getRangeAt(0);selectedRanges=[];
    $$('#lecture-content .source-copy, #lecture-content .translation-copy').forEach(el=>{
      if(!el.getClientRects().length||!range.intersectsNode(el)||el.closest('.type-formula'))return;
      const r=document.createRange();r.selectNodeContents(el);
      if(range.compareBoundaryPoints(Range.START_TO_START,r)>0)r.setStart(range.startContainer,range.startOffset);
      if(range.compareBoundaryPoints(Range.END_TO_END,r)<0)r.setEnd(range.endContainer,range.endOffset);
      const text=r.toString();if(!text.trim())return;
      const pre=document.createRange();pre.selectNodeContents(el);pre.setEnd(r.startContainer,r.startOffset);
      const start=pre.toString().length;
      selectedRanges.push({contentId:el.closest('[data-unit]').dataset.unit,layer:el.dataset.layer,start,end:start+text.length,text});
    });
    if(!selectedRanges.length)return;
    if(notebookTab==='assistant')document.dispatchEvent(new CustomEvent('assistant-selection',{detail:selectedRanges}));
    const rect=range.getBoundingClientRect(),menu=$('#selection-menu');menu.hidden=false;menu.style.left=Math.min(innerWidth-180,Math.max(10,rect.left+rect.width/2-75))+'px';menu.style.top=Math.max(65,rect.top-46)+'px';
  }
  function redrawUnit(id){const old=document.getElementById(id),group=old?.closest('.heading-group');if(group){const data=anchorMap.get(id)?.headingGroups?.find(g=>g.id===group.dataset.heading);if(data)group.outerHTML=headingHTML(data);}else if(old)old.outerHTML=unitHTML(unitMap.get(id));}
  function setMode(mode){state.mode=mode;document.body.classList.remove('mode-original','mode-translation');if(mode!=='bilingual')document.body.classList.add('mode-'+mode);$$('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));save();}
  document.addEventListener('click',async event=>{
    const el=event.target.closest('button,a,img[data-source]');if(!el)return;
    if(el.dataset.close){document.getElementById(el.dataset.close).close();return;}
    if(el.dataset.jump){event.preventDefault();navigate(el.dataset.jump,{closeNotebook:!!el.dataset.closeNotebook});return;}
    if(el.dataset.mode){setMode(el.dataset.mode);return;}
    if(el.dataset.tab){notebookTab=el.dataset.tab;selectedExplanation=null;insightFilter=null;renderNotebook();return;}
    if(el.dataset.ask){const u=unitMap.get(el.dataset.ask),layer=state.mode==='translation'?'translation':'source',text=displayText(u,layer);selectedRanges=text?[{contentId:u.id,layer,start:0,end:text.length,text}]:[];askSelection();return;}
    if(el.dataset.note){openNote(el.dataset.note);return;}
    if(el.dataset.bookmark){toggleBookmark(el.dataset.bookmark);return;}
    if(el.dataset.read){const id=el.dataset.read;state.read=state.read.includes(id)?state.read.filter(p=>p!==id):[...state.read,id];save();const checked=state.read.includes(id);el.innerHTML=`<span class="read-check ${checked?'checked':''}">${checked?'✓':''}</span>`;el.setAttribute('aria-label',checked?'标记为未读':'标记为已学');renderProgress();renderOutline();return;}
    if(el.dataset.source){sourceDialog(pageMap.get(el.dataset.source));return;}
    if(el.dataset.raw){sourceDialog(anchorMap.get(el.dataset.raw),unitMap.get(el.dataset.raw));return;}
    if(el.dataset.copy){const link=location.href.split('#')[0]+'#'+el.dataset.copy;try{await navigator.clipboard.writeText(link);toast('已复制精确定位链接');}catch(e){const area=document.createElement('textarea');area.value=link;document.body.append(area);area.select();const ok=document.execCommand('copy');area.remove();toast(ok?'已复制精确定位链接':'复制失败，请使用浏览器地址栏中的定位链接。');navigate(el.dataset.copy);}return;}
    if(el.dataset.editNote){const n=state.notes.find(n=>n.id===el.dataset.editNote);openNote(n.contentId,n.id);return;}
    if(el.dataset.deleteNote){state.notes=state.notes.filter(n=>n.id!==el.dataset.deleteNote);if(editingNote===el.dataset.deleteNote){noteTarget=null;editingNote=null;$('#note-text').value='';}save();renderNotebook();toast('已删除笔记');return;}
    if(el.dataset.deleteHighlight){const h=state.highlights.find(h=>h.id===el.dataset.deleteHighlight);state.highlights=state.highlights.filter(x=>x!==h);save();redrawUnit(h.contentId);renderNotebook();return;}
    if(el.dataset.deleteBookmark){state.bookmarks=state.bookmarks.filter(b=>b.id!==el.dataset.deleteBookmark);save();renderNotebook();return;}
    if(el.dataset.searchResult){$('#search-dialog').close();navigate(el.dataset.searchResult);return;}
    if(el.dataset.qualityJump){$('#quality-dialog').close();navigate(el.dataset.qualityJump);return;}
    if(el.dataset.selection){$('#selection-menu').hidden=true;if(el.dataset.selection==='assistant'){askSelection();}else if(el.dataset.selection==='note'){if(openNote(selectedRanges[0]?.contentId))$('#note-context').textContent=selectedRanges.map(s=>s.text).join('\n');}else{const ids=[];selectedRanges.forEach(r=>{state.highlights.push({id:uuid(),...r,createdAt:date()});ids.push(r.contentId);});save();getSelection()?.removeAllRanges();unique(ids).forEach(redrawUnit);notebookTab='highlights';renderNotebook();toast('高亮已保存');}return;}
    switch(el.id){
      case 'search-open':openSearch();break;
      case 'new-note':case 'empty-new-note':openNote();break;
      case 'export-btn':case 'backup-open':$('#export-dialog').showModal();break;
      case 'export-json':download('coursebook-学习备份.json',JSON.stringify(state,null,2),'application/json');break;
      case 'export-md':backupMarkdown();break;
      case 'quality-open':showQuality();break;
      case 'outline-tab':case 'topics-tab':outlineMode=el.id==='outline-tab'?'outline':'topics';$('#outline-tab').classList.toggle('active',outlineMode==='outline');$('#topics-tab').classList.toggle('active',outlineMode==='topics');$('#outline-tab').setAttribute('aria-selected',outlineMode==='outline');$('#topics-tab').setAttribute('aria-selected',outlineMode==='topics');renderOutline();break;
      case 'collapse-all':{const list=$$('.chapter-nav'),shouldOpen=list.every(d=>!d.open);list.forEach(d=>d.open=shouldOpen);el.textContent=shouldOpen?'全部折叠':'全部展开';break;}
      case 'sidebar-toggle':if(innerWidth<=700)$('#sidebar').classList.toggle('mobile-open');else document.body.classList.toggle('left-hidden');break;
      case 'notebook-toggle':if(innerWidth<=1020)$('#notebook').classList.toggle('mobile-open');else document.body.classList.toggle('right-hidden');break;
      case 'font-toggle':state.font=state.font===19?15:state.font+2;document.documentElement.style.setProperty('--font',state.font+'px');save();toast('正文字号 '+state.font);break;
    }
  });
  $('#note-form').addEventListener('submit',e=>{e.preventDefault();const text=$('#note-text').value.trim();if(!text)return;if(editingNote){const n=state.notes.find(n=>n.id===editingNote);n.text=text;n.updatedAt=date();}else state.notes.push({id:uuid(),contentId:noteTarget,text,createdAt:date(),updatedAt:date()});save();noteTarget=null;editingNote=null;$('#note-text').value='';notebookTab='notes';renderNotebook();showNotebook();toast('个人笔记已保存');});
  $('#search-input').addEventListener('input',e=>{clearTimeout(search.timer);search.timer=setTimeout(()=>search(e.target.value),100);});
  $('#import-records').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>20e6)throw Error('备份不能超过 20 MB。');const imported=validateState(JSON.parse(await file.text()));for(const key of ['notes','highlights','bookmarks']){const map=new Map(state[key].map(v=>[v.id,v]));imported[key].forEach(v=>{const current=map.get(v.id);if(!current||(v.updatedAt||v.createdAt)>(current.updatedAt||current.createdAt))map.set(v.id,v);});state[key]=[...map.values()];}state.read=unique([...state.read,...imported.read]);save();renderChapter(currentChapter.id);renderProgress();renderNotebook();toast('备份已合并，已有记录保留。');}catch(err){toast(err.message||'备份无法读取。');}e.target.value='';});
  $('#lecture-content').addEventListener('mouseup',()=>setTimeout(captureSelection,15));
  $('#lecture-content').addEventListener('keyup',()=>setTimeout(captureSelection,15));
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('#selection-menu'))$('#selection-menu').hidden=true;});
  $('#selection-menu').addEventListener('mousedown',e=>e.preventDefault());
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openSearch();}if(e.key==='Escape'){$('#selection-menu').hidden=true;$('#sidebar').classList.remove('mobile-open');$('#notebook').classList.remove('mobile-open');}});
  addEventListener('hashchange',()=>{let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(e){return;}if(id)navigate(id,{noHash:true});});
  addEventListener('popstate',()=>{let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(e){return;}if(id)navigate(id,{noHash:true});});
  $('#course-title').textContent=C.title;$('#top-title').textContent=C.title;$('#course-subtitle').textContent=C.subtitle;$('#lecture-count').textContent=`${C.files.length} 份讲义 · ${allPages.length} 页`;
  document.title=C.title+' · coursebook';document.documentElement.style.setProperty('--font',state.font+'px');setMode(state.mode);
  let initial;try{initial=decodeURIComponent(location.hash.slice(1));}catch(e){initial=null;}
  // Resume precisely; new readers start at the first teaching page, with front matter available in original order.
  initial=anchorMap.has(initial)?initial:anchorMap.has(state.lastAnchor)?state.lastAnchor:(allPages.find(p=>p.units.filter(u=>u.type==='bullet').length>=2)||allPages[0]).id;
  navigate(initial,{instant:true,noHash:true});renderProgress();renderNotebook();
  document.addEventListener('course-review-updated',e=>{
    const patch=e.detail;
    if(patch.unit){Object.assign(unitMap.get(patch.unit.id),patch.unit);state=validateState(state);}
    if(patch.pageId)Object.assign(pageMap.get(patch.pageId),patch.pageChanges);
    if(patch.quality)C.quality=patch.quality;
    (patch.explanationReviewIds||[]).forEach(id=>{if(explanationMap.has(id))explanationMap.get(id).needsReview=true;});
    const scroll=$('#reader-scroll')||$('.reader-scroll'),top=scroll.scrollTop;
    renderChapter(currentChapter.id);renderNotebook();scroll.scrollTop=top;save();
  });
  document.addEventListener('course-navigate',e=>navigate(e.detail));
  const preferences=document.createElement('details');preferences.className='reading-preferences';preferences.innerHTML='<summary title="阅读设置">阅读设置</summary><div><label class="reading-select">双语对照<select id="bilingual-layout"><option value="stacked">逐句上下</option><option value="columns">左右对照</option></select></label><label class="reading-select">正文字体<select id="body-font"><option value="sans">现代黑体</option><option value="song">经典宋体</option><option value="kai">人文楷体</option><option value="serif">英文衬线</option></select></label><label><input id="compact-reading" type="checkbox" checked> 紧凑表格与段落</label><label><input id="merge-identical" type="checkbox" checked> 合并相同原文与译文</label><button type="button" id="focus-reading">专注阅读</button></div>';
  $('.reader-toolbar').append(preferences);
  let density={compact:true,merge:true,layout:'stacked',font:'sans'};try{density={...density,...JSON.parse(localStorage.getItem('course-compiler:reading-density')||'{}')};}catch{}
  const fonts={sans:'"Segoe UI","Microsoft YaHei",sans-serif',song:'"SimSun","Songti SC",serif',kai:'"KaiTi","STKaiti",serif',serif:'Georgia,"SimSun",serif'};
  function applyDensity(){density.layout=density.layout==='columns'?'columns':'stacked';density.font=Object.hasOwn(fonts,density.font)?density.font:'sans';document.body.classList.toggle('bilingual-columns',density.layout==='columns');document.documentElement.style.setProperty('--body-font',fonts[density.font]);$('#bilingual-layout').value=density.layout;$('#body-font').value=density.font;document.body.classList.toggle('compact-reading',density.compact);document.body.classList.toggle('merge-identical',density.merge);$('#compact-reading').checked=density.compact;$('#merge-identical').checked=density.merge;}
  applyDensity();preferences.onchange=()=>{density={compact:$('#compact-reading').checked,merge:$('#merge-identical').checked,layout:$('#bilingual-layout').value,font:$('#body-font').value};applyDensity();try{localStorage.setItem('course-compiler:reading-density',JSON.stringify(density));}catch{}};
  $('#focus-reading').onclick=()=>{document.body.classList.toggle('right-hidden');preferences.open=false;};
  if(storageWarning)setTimeout(()=>toast('浏览器存储不可用或备份格式异常，请导出记录备份。'),500);
  // Optional WebMCP capability uses precisely the same navigation and note actions.
  const context=document.modelContext;
  if(context?.registerTool){
    const lifecycle=new AbortController();
    const register=tool=>{try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch(e){}};
    register({name:'navigate_course_content',description:'Navigate to an existing course content, page or explanation anchor.',inputSchema:{type:'object',properties:{contentId:{type:'string'}},required:['contentId'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},execute(input){if(typeof input?.contentId!=='string'||!anchorMap.has(input.contentId))throw Error('Unknown content ID');navigate(input.contentId);return{contentId:input.contentId,page:anchorMap.get(input.contentId).number};}});
    register({name:'start_course_note',description:'Open the personal note editor at the selected course anchor. Does not save a note.',inputSchema:{type:'object',properties:{contentId:{type:'string'}},required:['contentId'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},execute(input){if(typeof input?.contentId!=='string'||!anchorMap.has(input.contentId))throw Error('Unknown content ID');openNote(input.contentId);return{editorOpen:true,contentId:input.contentId};}});
    addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
  }
})();
