const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="console-token"]').content;
const activeStatuses = new Set(['starting','planning','ready','running','awaiting_human','stopping','closing']);
const labels = {idle:'Ready',starting:'Opening browser',planning:'Planning',ready:'Working',running:'Working',awaiting_human:'Your turn',stopping:'Stopping',closing:'Closing browser',done:'Completed',blocked:'Needs attention',error:'Run failed',cancelled:'Stopped'};
let current = {status:'idle'}, renderedRun = null, lastTimeline = '', lastPlan = '', displayedLive = '', polling = false, submitting = false;
const examples = {
  books: {url:'https://books.toscrape.com',goal:'Find the product page for A Light in the Attic. Report its title, price, and UPC. Check whether an ISBN is listed; if absent, say that this page does not provide one.'},
  webb: {url:'https://en.wikipedia.org/wiki/Main_Page',goal:'James Webb Space Telescope: Report its launch date, the launch vehicle, and why it operates near the Sun-Earth L2 point. Cite supporting sources.'},
  python: {url:'https://www.google.com',goal:"Find Python's official documentation explaining list.sort() and sorted(). Explain which modifies the original list and which returns a new list, with the documentation URL."}
};
function node(tag, text, className) { const el=document.createElement(tag); if(text!==undefined)el.textContent=text;if(className)el.className=className;return el; }
function safeUrl(value) { try {const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;} }
async function api(path, body) {
  const response=await fetch(path,{method:body?'POST':'GET',headers:{'X-Console-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed');return data;
}
function notice(message) { $('notice').textContent=message||'';$('notice').hidden=!message; }
function tab(output) { $('activity-tab').setAttribute('aria-selected',String(!output));$('output-tab').setAttribute('aria-selected',String(output));$('activity-pane').hidden=output;$('output-pane').hidden=!output; }
function render(state) {
  current=state;
  if(state.run_id!==renderedRun){renderedRun=state.run_id;lastTimeline='';lastPlan='';tab(false);$('answer').textContent='';$('sources').replaceChildren();}
  const active=activeStatuses.has(state.status), waiting=state.status==='awaiting_human';
  $('status').textContent=labels[state.status]||state.status;$('status').className='status'+(active&&!waiting?' busy':'')+(['blocked','error'].includes(state.status)?' error':'');
  $('run').disabled=active||state.session_status==='release_failed';$('goal').disabled=active;$('url').disabled=active;
  $('pause').disabled=!active||waiting||['starting','planning','closing'].includes(state.status);$('stop').disabled=!active||state.status==='closing';
  $('handoff').hidden=!waiting;$('retry-release').hidden=state.session_status!=='release_failed';
  const missing=Object.entries(state.configured||{}).filter(([,ok])=>!ok).map(([key])=>key);
  $('config-status').textContent=missing.length?'Setup needed: '+missing.join(', '):(state.hosted?'Credentials configured · cloud console':'Credentials configured · local console');
  notice(state.cleanup_error?('Browser cleanup could not be confirmed. '+state.cleanup_error):state.blocked_reason||state.live_warning||(missing.length?(state.hosted?'Configure '+missing.join(' and ')+' in the server environment.':'Add '+missing.join(' and ')+' to .env and restart the console.'):''));
  const live=state.live_url;
  if(live!==displayedLive){displayedLive=live||'';if(live){$('live-browser').src=live;}else{$('live-browser').removeAttribute('src');}}
  $('live-browser').hidden=!live;$('browser-placeholder').hidden=!!live;
  if(!live){const end=state.run_id&&!active;$('browser-placeholder').querySelector('h2').textContent=end?'Browser session ended.':'Your browser, working live.';$('browser-placeholder').querySelector('p').textContent=end?'The activity and result stay available below.':'Start a task to open a cloud browser. You can watch every step here.';}
  $('open-browser').hidden=!live;if(live)$('open-browser').href=live;
  $('page-title').textContent=state.page?.title||'Live browser';
  $('session-state').textContent=state.session_status==='released'?'Browser released':state.session_status==='active'?'Cloud session active':state.session_status==='release_failed'?'Session cleanup needs attention':state.session_status==='creating'?'Creating cloud session':'No active session';
  const seconds=Math.floor((state.elapsed_ms||0)/1000);$('elapsed').textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  $('completion-time').hidden=state.status!=='done';
  const durationSeconds=Math.max(0,Math.round((state.elapsed_ms||0)/1000));
  $('completion-duration').textContent=durationSeconds<60?((state.elapsed_ms||0)/1000).toFixed(1)+'s':Math.floor(durationSeconds/60)+'m '+String(durationSeconds%60).padStart(2,'0')+'s';
  $('evidence-count').textContent=state.evidence_count||0;$('call-count').textContent=Object.values(state.model_calls||{}).reduce((sum,n)=>sum+n,0);
  const planKey=JSON.stringify([state.tasks,state.task_index,state.status]);
  if(planKey!==lastPlan){lastPlan=planKey;$('plan').replaceChildren();if(!state.tasks?.length)$('plan').append(node('li',active?'Breaking your goal into tasks…':'The plan will appear when your task starts.','muted'));else state.tasks.forEach((task,i)=>$('plan').append(node('li',task.objective,i<(state.task_index||0)||state.status==='done'?'complete':i===(state.task_index||0)?'active':'')));}
  const history=state.history||[], events=(state.events||[]).filter(e=>['read','content_paged','replanned','uncertain','stale','verified','incomplete'].includes(e.status));
  const timelineKey=JSON.stringify([history,events]);
  if(timelineKey!==lastTimeline){lastTimeline=timelineKey;$('timeline').replaceChildren();for(const h of history){const li=node('li');li.append(node('span','↗','event-icon'));const main=node('div',undefined,'event-main');main.append(node('strong',h.action||h.operation));if(h.text)main.append(node('p','Entered “'+h.text+'”'));li.append(main,node('span',((h.elapsed_ms||0)/1000).toFixed(1)+'s','event-time'));$('timeline').append(li);}for(const e of events.slice(-12)){const li=node('li');li.append(node('span',e.status==='read'?'≡':'·','event-icon'));const main=node('div',undefined,'event-main');main.append(node('strong',({read:'Read source passages',content_paged:'Moved to another content window',replanned:'Updated plan',uncertain:'Reassessing the next action',stale:'Page changed; observing again',verified:'Checked task outcome',incomplete:'More evidence needed'})[e.status]));if(e.passage||e.reason)main.append(node('p',e.passage||e.reason));li.append(main);$('timeline').append(li);}$('activity-empty').hidden=!!(history.length||events.length);$('timeline').scrollTop=$('timeline').scrollHeight;}
  $('output-empty').hidden=!!state.result;$('output-badge').hidden=!state.result;
  if(state.result){$('answer').textContent=state.result.answer;$('sources').replaceChildren(node('p','SUPPORTING SOURCES','eyebrow'));for(const source of state.result.sources||[]){const url=safeUrl(source.url);if(!url)continue;const a=node('a','['+source.id+'] '+source.title+' ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';$('sources').append(a,node('small',source.quote));}tab(true);}
  $('download').disabled=!state.run_id||active;
  $('outcome-note').textContent=state.status==='done'?'Answer passed the agent’s evidence checks.':state.status==='blocked'?'Stopped without verified completion. See the trace for details.':waiting?'Paused for your input.':active?'Observations and actions update as the agent runs.':state.run_id?'Run ended. Trace available for review.':'Ready when you are.';
}
$('task-form').addEventListener('submit',async event=>{event.preventDefault();if(submitting)return;submitting=true;$('run').disabled=true;try{render(await api('/api/start',{goal:$('goal').value,url:$('url').value}));}catch(error){notice(error.message);$('run').disabled=false;}finally{submitting=false;}});
for(const [id,action] of [['pause','pause'],['stop','cancel'],['resume','resume'],['retry-release','release']])$(id).addEventListener('click',async()=>{try{render(await api('/api/control',{action}));}catch(error){notice(error.message);}});
for(const button of document.querySelectorAll('[data-example]'))button.addEventListener('click',()=>{if(activeStatuses.has(current.status))return;const example=examples[button.dataset.example];$('goal').value=example.goal;$('url').value=example.url;$('goal').focus();});
$('activity-tab').onclick=()=>tab(false);$('output-tab').onclick=()=>tab(true);
$('download').onclick=async()=>{try{const response=await fetch('/api/trace',{headers:{'X-Console-Token':token}});if(!response.ok)throw new Error('Trace is not available yet.');const url=URL.createObjectURL(await response.blob()),a=node('a');a.href=url;a.download='minotaur-'+current.run_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message);}};
async function poll(){if(submitting||polling||(current.hosted&&current.run_id&&!activeStatuses.has(current.status)))return;polling=true;try{const state=await api('/api/state');if(!submitting)render(state);}catch(error){notice('Console disconnected. '+error.message);}finally{polling=false;}}
poll();setInterval(poll,2000);
