import { Sandbox } from '@vercel/sandbox';
import { readFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { sign, verify, validTask } from '../lib/session.mjs';
const required=['BROWSERBASE_API_KEY','BROWSERBASE_PROJECT_ID','TYPESAFE_API_KEY','TEXT_MODEL_API_KEY'];
const envNames=[...required,'TYPESAFE_MODEL','TEXT_MODEL_BASE_URL','TEXT_MODEL','TEXT_MODEL_REASONING'];
const configured=()=>Object.fromEntries(required.map(key=>[key,Boolean(process.env[key])]));
const idle=()=>({status:'idle',session_status:'none',history:[],events:[],configured:configured(),hosted:true});
export default async function handler(req,res) {
  res.setHeader('Cache-Control','no-store');
  const path=new URL(req.url,'https://console.local').pathname;
  if(!['/api/state','/api/start','/api/control','/api/trace'].includes(path))return res.status(404).json({error:'Not found'});
  if(req.method!==(path==='/api/start'||path==='/api/control'?'POST':'GET'))return res.status(405).json({error:'Method not allowed'});
  if(req.method==='POST') {
    const origin=req.headers.origin;
    if(!origin||new URL(origin).host!==req.headers.host)return res.status(403).json({error:'Invalid request origin'});
  }
  const secret=process.env.CONSOLE_SESSION_SECRET;
  if(!secret)return res.status(503).json({error:'Console session signing is not configured.'});
  const cookie=(req.headers.cookie||'').split(';').map(v=>v.trim()).find(v=>v.startsWith('minotaur_session='))?.slice(17);
  const session=verify(cookie||'',secret);
  try {
    if(path==='/api/state'&&!session)return res.json(idle());
    if(path==='/api/start') {
      let task;
      try {task=validTask(req.body);}catch(error){return res.status(400).json({error:error.message});}
      if(required.some(k=>!process.env[k]))return res.status(503).json({error:'Cloud browser and model credentials are required.'});
      if(session) {
        const previous=await Sandbox.get({name:session.name});
        const data=await previous.readFileToBuffer({path:'state.json'});
        const state=data&&JSON.parse(data.toString());
        if(!state||!['done','blocked','error','cancelled'].includes(state.status)||state.session_status==='release_failed')return res.status(409).json({error:'Finish or stop the current task first.'});
        await previous.stop();
      }
      const name='minotaur-'+randomBytes(16).toString('hex');
      const box=await Sandbox.create({name,runtime:'python3.13',timeout:30*60*1000,persistent:true,snapshotExpiration:24*60*60*1000});
      const expires=Date.now()+24*60*60*1000;
      res.setHeader('Set-Cookie',`minotaur_session=${sign({name,expires},secret)}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400`);
      try {
        const source=JSON.parse(await readFile(new URL('../deployment/source.json',import.meta.url),'utf8'));
        await box.writeFiles([...source.map(f=>({path:f.path,content:Buffer.from(f.content,'base64')})),{path:'task.json',content:Buffer.from(JSON.stringify(task))}]);
        const install=await box.runCommand({cmd:'python3',args:['-m','pip','install','browser-harness==0.1.13','httpx[http2]>=0.28,<1']});
        if(install.exitCode!==0)throw new Error('Sandbox dependency installation failed.');
        const env=Object.fromEntries(envNames.filter(k=>process.env[k]).map(k=>[k,process.env[k]]));
        await box.runCommand({cmd:'python3',args:['-m','jev_ultrafast.vercel_worker'],env,detached:true});
        return res.json({...idle(),...task,status:'starting',run_id:name,session_status:'creating'});
      } catch(error) {
        await box.writeFiles([{path:'state.json',content:Buffer.from(JSON.stringify({...idle(),status:'error',run_id:name,blocked_reason:'Cloud worker setup failed. Start a new task.'}))}]).catch(()=>{});
        await box.stop();throw error;
      }
    }
    if(!session)return res.status(404).json({error:'No task session.'});
    const box=await Sandbox.get({name:session.name});
    const wasStopped=box.status!=='running';
    if(path==='/api/control') {
      const action=req.body?.action;
      if(!['pause','resume','cancel','release'].includes(action))return res.status(400).json({error:'Unknown control.'});
      if(action==='release') {
        const data=await box.readFileToBuffer({path:'state.json'});
        const state=data&&JSON.parse(data.toString());
        if(!state||!['done','blocked','error','cancelled'].includes(state.status))return res.status(409).json({error:'Stop the task before cleanup.'});
        const env=Object.fromEntries(envNames.filter(k=>process.env[k]).map(k=>[k,process.env[k]]));
        await box.runCommand({cmd:'python3',args:['-m','jev_ultrafast.vercel_worker','--release'],env});
      }else await box.writeFiles([{path:action,content:Buffer.from('')}]);
    }
    if(path==='/api/trace') {
      const trace=await box.readFileToBuffer({path:'trace.json'});
      if(!trace)return res.status(404).json({error:'Trace will be available after the run ends.'});
      await box.stop();
      res.setHeader('Content-Type','application/json');return res.send(trace);
    }
    const buffer=await box.readFileToBuffer({path:'state.json'});
    const state=buffer?JSON.parse(buffer.toString()):{...idle(),status:'starting',run_id:session.name};
    // Snapshot reads can resume a stopped VM; a stopped task is never restarted.
    if(wasStopped&&!['done','blocked','error','cancelled'].includes(state.status)) {
      state.status='error';state.session_status=state.session_id?'release_failed':'none';
      state.blocked_reason='Worker stopped before completion. Release the browser before starting a new task.';
      await box.writeFiles([{path:'state.json',content:Buffer.from(JSON.stringify(state))}]);
    }
    if(['done','blocked','error','cancelled'].includes(state.status))await box.stop();
    return res.json({...state,hosted:true,configured:configured()});
  }catch(error){
    console.error('Console infrastructure error:',error.name);
    return res.status(502).json({error:'Cloud worker unavailable. Check the Vercel runtime logs.'});
  }
}
