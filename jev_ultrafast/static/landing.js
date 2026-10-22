import { examples } from './task-examples.js';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="console-token"]').content;
let submitting = false;
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
function recentRuns() {
  try {const runs=JSON.parse(localStorage.getItem('minotaur-runs')||'[]');return Array.isArray(runs)?runs.filter(run=>/^minotaur-[a-f0-9]{32}$/.test(run.id)&&typeof run.goal==='string'):[];}catch{return [];}
}
function showRecent() {
  const runs=recentRuns();$('recent-section').hidden=!runs.length;$('recent-runs').replaceChildren();
  for(const run of runs){const link=document.createElement('a');link.href='/runs/'+run.id;const title=document.createElement('strong');title.textContent=run.goal;const id=document.createElement('small');id.textContent=run.id;link.append(title,id);$('recent-runs').append(link);}
}
for(const button of document.querySelectorAll('[data-example]'))button.addEventListener('click',()=>{if(submitting)return;const example=examples[button.dataset.example];$('goal').value=example.goal;$('url').value=example.url;$('goal').focus();});
$('task-form').addEventListener('submit',async event=>{
  event.preventDefault();if(submitting)return;submitting=true;notice('Opening a fresh console…');$('run').disabled=true;$('run').textContent='Starting your task…';
  const task={goal:$('goal').value,url:$('url').value};
  try {
    const response=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json','X-Console-Token':token},body:JSON.stringify(task)});
    const state=await response.json();if(!response.ok)throw new Error(state.error||'Could not start the task.');
    if(!/^minotaur-[a-f0-9]{32}$/.test(state.run_id))throw new Error('The server returned an invalid run ID.');
    try {localStorage.setItem('minotaur-runs',JSON.stringify([{id:state.run_id,goal:task.goal},...recentRuns().filter(run=>run.id!==state.run_id)].slice(0,12)));}catch{}
    location.assign('/runs/'+state.run_id);
  }catch(error){notice(error.message);submitting=false;$('run').disabled=false;$('run').textContent='Start a new task ↗';}
});
try{const draft=JSON.parse(sessionStorage.getItem('minotaur-draft')||'null');if(draft&&typeof draft.goal==='string'){$('goal').value=draft.goal;$('url').value=typeof draft.url==='string'?draft.url:'';}sessionStorage.removeItem('minotaur-draft');}catch{}
// A back/forward cache restore must not leave the form in its submitting state.
addEventListener('pageshow',()=>{submitting=false;$('run').disabled=false;$('run').textContent='Start a new task ↗';notice('');showRecent();});
showRecent();
fetch('/api/state',{headers:{'X-Console-Token':token}}).then(response=>response.json()).then(state=>{
  const missing=Object.entries(state.configured||{}).filter(([,ok])=>!ok).map(([key])=>key);
  $('config-status').textContent=missing.length?'Setup needed: '+missing.join(', '):'Ready for a new task';
}).catch(()=>{$('config-status').textContent='Connection unavailable';});
