/* On-demand local study assistant. No keys or generated conversations in site exports. */
(()=>{
  'use strict';
  const panel=document.getElementById('assistant-panel'),C=window.COURSE_DATA;
  if(!panel||!C)return;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let token=null,selection=[],messages=[],running=false,timer=null,loading=null,followReply=true;
  const hosted=location.protocol==='http:'&&/^\/courses\/course-[a-f0-9]{16}\//.test(location.pathname);
  panel.innerHTML=`<div class="assistant-thread" id="assistant-thread" aria-label="与学习助手的对话"><div class="empty-state">选中讲义中的文字，<br>一起弄懂它。</div></div><form id="assistant-form" class="assistant-composer"><div id="assistant-context" hidden></div><label for="assistant-question" class="sr-only">向 AI 学习助手提问</label><textarea id="assistant-question" rows="3" maxlength="4000" placeholder="解释这段话，或提一个课程问题…" required></textarea><div class="assistant-controls"><label title="开启后，助手可按问题发送检索词到已选择的搜索服务"><input type="checkbox" id="assistant-web" disabled><span id="assistant-web-label">联网</span></label><button type="button" id="assistant-cancel" hidden>停止</button><button type="submit" id="assistant-send" class="button primary" disabled>发送 ↑</button></div><p id="assistant-status" class="assistant-status" role="status">${hosted?'正在连接本地助手…':'请在本地 coursebook 应用中打开课程以使用 AI 助手。离线阅读和笔记不受影响。'}</p><div class="assistant-footnote">AI 回答仅辅助理解，以讲义原文为准。${hosted?'<a href="/app" target="_blank" rel="noopener">模型设置 ↗</a>':''}</div></form>`;
  const $=s=>panel.querySelector(s);
  $('#assistant-question').rows=1;
  $('.assistant-footnote').innerHTML=`<details><summary>使用说明${hosted?' · 模型设置':''}</summary><div>AI 回答仅辅助理解，以讲义原文为准。选段作为上下文，发送后才调用模型。Ctrl / ⌘ + Enter 发送。${hosted?'<a href="/app" target="_blank" rel="noopener">模型设置 ↗</a>':''}</div></details>`;
  $('#assistant-thread').insertAdjacentHTML('afterend','<div id="assistant-progress" class="assistant-progress" role="status" aria-live="polite" hidden><span class="assistant-spinner" aria-hidden="true"></span><span id="assistant-stage">正在思考…</span></div><button type="button" id="assistant-new-answer" hidden>查看新回答 ↓</button>');
  function status(text=''){const el=$('#assistant-status');el.textContent=text;el.hidden=!text;}
  function resizeQuestion(){const el=$('#assistant-question');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,104)+'px';}
  $('#assistant-question').addEventListener('input',resizeQuestion);
  $('#assistant-thread').addEventListener('wheel',e=>{if(running&&e.deltaY<0)followReply=false;},{passive:true});
  $('#assistant-thread').addEventListener('touchmove',()=>{if(running)followReply=false;},{passive:true});
  $('#assistant-thread').addEventListener('keydown',e=>{if(running&&['ArrowUp','PageUp','Home'].includes(e.key))followReply=false;});
  $('#assistant-thread').tabIndex=0;
  $('#assistant-thread').addEventListener('scroll',()=>{const t=$('#assistant-thread');if(running)followReply=t.scrollTop+t.clientHeight>=t.scrollHeight-80;});
  function showAnswer(){const t=$('#assistant-thread'),last=t.querySelector('.from-assistant:last-of-type');if(last)t.scrollTop+=last.getBoundingClientRect().top-t.getBoundingClientRect().top-12;$('#assistant-new-answer').hidden=true;}
  $('#assistant-new-answer').onclick=showAnswer;
  async function api(path,data){
    const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Course-Token':token},body:JSON.stringify(data)}:undefined);
    const value=await r.json();if(!r.ok)throw Error(value.error||'连接未成功');return value;
  }
  function busy(value,stage='正在思考…'){
    running=value;panel.classList.toggle('is-running',value);$('#assistant-thread').setAttribute('aria-busy',String(value));
    $('#assistant-progress').hidden=!value;$('#assistant-stage').textContent=stage||'正在思考…';
    $('#assistant-send').disabled=!token||value;$('#assistant-send').textContent=value?'处理中…':'发送 ↑';
    $('#assistant-cancel').hidden=!value;$('#assistant-question').readOnly=value;
    const clear=$('#assistant-clear-context');if(clear)clear.disabled=value;
  }
  function context(){
    const box=$('#assistant-context');box.hidden=!selection.length;
    box.innerHTML=selection.length?`<div class="assistant-context-heading"><button type="button" id="assistant-expand-context" aria-expanded="false">已选正文 · ${selection.length} 处 <span>展开</span></button><button type="button" id="assistant-clear-context" aria-label="移除选段">×</button></div><blockquote>${esc(selection.map(s=>s.text).join('\n'))}</blockquote>`:'';
    box.classList.remove('expanded');
  }
  function cite(s){
    if(s.contentId)return `<button type="button" data-agent-source="${esc(s.contentId)}">[${esc(s.id)}] ${esc(s.file)} · P${Number(s.page)} ↗</button>`;
    if(/^https?:\/\//.test(s.url||''))return `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">[${esc(s.id)}] ${esc(s.title)} ↗</a>`;
    return '';
  }
  function render(newReply=false){
    const thread=$('#assistant-thread'),oldTop=thread.scrollTop,nearEnd=thread.scrollTop+thread.clientHeight>=thread.scrollHeight-80;
    thread.innerHTML=messages.length?messages.map(m=>{
      const sources=m.sources||[],byId=new Map(sources.map(s=>[s.id,s]));
      const body=esc(m.text).replace(/\[([LW]\d+)\]/g,(match,id)=>{const s=byId.get(id);if(!s)return match;return s.contentId?`<button type="button" class="inline-citation" data-agent-source="${esc(s.contentId)}">${match}</button>`:/^https?:\/\//.test(s.url||'')?`<a class="inline-citation" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${match}</a>`:match;});
      const anchor=sources.find(s=>s.contentId)?.contentId;
      return `<article class="assistant-message ${m.role==='user'?'from-user':'from-assistant'}"><div class="assistant-message-label">${m.role==='user'?'你':'AI 助手 · 补充说明'}</div>${m.selection?.length?`<details class="assistant-sent-context"><summary>所选正文 · ${m.selection.length} 处</summary>${m.selection.map(s=>`<button type="button" data-agent-source="${esc(s.contentId)}">${esc(s.text)}</button>`).join('')}</details>`:''}<div class="assistant-answer">${body}</div>${sources.length?`<details class="assistant-sources"><summary>参考来源 · ${sources.length}</summary>${sources.map(cite).join('')}</details>`:''}${m.role==='assistant'?`<button type="button" class="assistant-to-note" data-agent-note="${esc(m.id)}" data-anchor="${esc(anchor||'')}">＋ 保存为笔记</button>`:''}</article>`;
    }).join(''):'<div class="empty-state">选中讲义中的文字，<br>一起弄懂它。<small>支持课程检索、连续追问与联网资料。</small></div>';
    if(newReply){if(followReply)showAnswer();else{thread.scrollTop=oldTop;$('#assistant-new-answer').hidden=false;}}
    else if(nearEnd)thread.scrollTop=thread.scrollHeight;
    else thread.scrollTop=oldTop;
  }
  async function refresh(){
    if(!hosted)return;
    try{
      const data=await api('/api/assistant/'+C.id);
      const newReply=running&&data.messages.some(m=>m.role==='assistant'&&!messages.some(old=>old.id===m.id));
      busy(data.run?.status==='running',data.run?.message);$('#assistant-web').disabled=!data.webAvailable||running;
      if(JSON.stringify(messages)!==JSON.stringify(data.messages)){messages=data.messages;render(newReply);}
      if(!data.webAvailable)$('#assistant-web').checked=false;
      $('#assistant-web').parentElement.title=data.webAvailable?'开启后允许助手向 '+(data.webProviderLabel||'所选搜索服务')+' 发送检索词':'在模型设置中选择搜索服务并填写密钥后可联网';
      $('#assistant-web-label').textContent=data.webAvailable?'联网 · '+(data.webProviderLabel||'已配置'):'联网';
      const run=data.run;
      status(run?.status==='error'||run?.status==='cancelled'?run.message:'');
      clearTimeout(timer);if(running)timer=setTimeout(refresh,1200);
    }catch(e){status(running?'连接暂时中断，正在重新获取回答状态…':e.message);if(running){$('#assistant-stage').textContent='正在确认处理状态…';clearTimeout(timer);timer=setTimeout(refresh,3000);}}
  }
  async function connect(){
    if(!hosted)return;
    if(loading)return loading;
    loading=(async()=>{try{if(!token)token=(await api('/api/status')).token;await refresh();}catch(e){status('本地助手连接未成功，请重新打开课程。');}finally{loading=null;}})();return loading;
  }
  document.addEventListener('assistant-activate',connect);
  document.addEventListener('assistant-selection',e=>{
    if(running)return;
    const ranges=e.detail||[];
    if(ranges.length>8||ranges.reduce((n,r)=>n+r.text.length,0)>8000){status('请选择最多 8 个单元、8000 字以内的内容。');return;}
    selection=ranges.map(r=>({...r}));context();
  });
  panel.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.id==='assistant-clear-context'&&!running){selection=[];context();}
    if(b.id==='assistant-expand-context'){const expanded=$('#assistant-context').classList.toggle('expanded');b.setAttribute('aria-expanded',String(expanded));b.querySelector('span').textContent=expanded?'收起':'展开';}
    if(b.dataset.agentSource)document.dispatchEvent(new CustomEvent('course-navigate',{detail:b.dataset.agentSource}));
    if(b.dataset.agentNote){const message=messages.find(m=>m.id===b.dataset.agentNote);if(message){const refs=(message.sources||[]).map(s=>s.contentId?`[${s.id}] ${s.file} · Page ${s.page} · #${s.contentId}`:`[${s.id}] ${s.title} ${s.url}`).join('\n');document.dispatchEvent(new CustomEvent('assistant-save-note',{detail:{contentId:b.dataset.anchor||selection[0]?.contentId,text:'AI 助手回答（补充说明）\n\n'+message.text+(refs?'\n\n参考来源\n'+refs:'')}}));}}
  });
  $('#assistant-form').onsubmit=async e=>{
    e.preventDefault();if(running||!token)return;
    const question=$('#assistant-question').value.trim();if(!question)return;
    followReply=true;$('#assistant-new-answer').hidden=true;busy(true,'正在发送问题…');status();
    try{await api('/api/assistant/'+C.id,{question,selection,allowWeb:$('#assistant-web').checked});$('#assistant-question').value='';resizeQuestion();await refresh();}
    catch(e){busy(false);status(e.message);}
  };
  $('#assistant-cancel').onclick=async()=>{const b=$('#assistant-cancel');b.disabled=true;$('#assistant-stage').textContent='正在停止…';try{await api('/api/assistant-cancel/'+C.id,{});await refresh();}catch(e){status(e.message);}finally{b.disabled=false;}};
  $('#assistant-question').onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('#assistant-form').requestSubmit();}};
  connect();
})();
