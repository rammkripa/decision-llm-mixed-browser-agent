import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sign, verify, validTask } from '../lib/session.mjs';
test('session rejects tampering, expired sessions, wrong signing keys, and invalid sandbox names',()=>{
  const data={name:'minotaur-'+'a'.repeat(32),expires:Date.now()+10000};
  const token=sign(data,'secret');
  assert.deepEqual(verify(token,'secret'),data);
  assert.equal(verify(token,'other'),null);
  assert.equal(verify(token+'x','secret'),null);
  assert.equal(verify(sign({...data,expires:0},'secret'),'secret'),null);
  assert.equal(verify(sign({...data,name:'other-project'},'secret'),'secret'),null);
});
test('task input accepts goals and rejects credentials or non-web protocols',()=>{
  assert.deepEqual(validTask({goal:'  Find a book  '}),{goal:'Find a book',url:'https://www.google.com'});
  for(const body of [{goal:''},{goal:'x'.repeat(2001)},{goal:'go',url:'file:///tmp/a'},{goal:'go',url:'https://user:pass@example.com'}])assert.throws(()=>validTask(body));
});

test('each run keeps its own signed capability even when another run starts',async()=>{
  const { runCookieName, sessionForRun } = await import('../lib/session.mjs');
  const first='minotaur-'+'a'.repeat(32), second='minotaur-'+'b'.repeat(32);
  const firstToken=sign({name:first,expires:Date.now()+10000},'secret');
  const secondToken=sign({name:second,expires:Date.now()+10000},'secret');
  const cookies=`${runCookieName(first)}=${firstToken}; ${runCookieName(second)}=${secondToken}`;
  assert.equal(sessionForRun(cookies,first,'secret').name,first);
  assert.equal(sessionForRun(cookies,second,'secret').name,second);
  assert.equal(sessionForRun(`${runCookieName(second)}=${firstToken}`,second,'secret'),null);
  assert.equal(sessionForRun(cookies,'../other','secret'),null);
});

test('two concurrent runs route state, controls, and traces independently without paid APIs',async()=>{
  const { createHandler }=await import('../api/console.mjs');
  const { runCookieName }=await import('../lib/session.mjs');
  const original={...process.env};
  for(const key of ['BROWSERBASE_API_KEY','BROWSERBASE_PROJECT_ID','TYPESAFE_API_KEY','TEXT_MODEL_API_KEY'])process.env[key]='offline-test';
  process.env.CONSOLE_SESSION_SECRET='offline-signing-key';
  const boxes=new Map();
  const makeBox=name=>({
    name,status:'running',files:new Map(),stops:0,
    async writeFiles(files){for(const f of files)this.files.set(f.path,f.content);},
    async runCommand({args}){if(args.includes('jev_ultrafast.vercel_worker')){
      const task=JSON.parse(this.files.get('task.json'));
      this.files.set('state.json',Buffer.from(JSON.stringify({...task,status:'running',run_id:'internal-worker-id'})));
    }return {exitCode:0};},
    async readFileToBuffer({path}){return this.files.get(path)||null;},
    async stop(){this.stops++;this.status='stopped';}
  });
  const handler=createHandler({sandbox:{async create({name}){const box=makeBox(name);boxes.set(name,box);return box;},async get({name}){assert.ok(boxes.has(name));return boxes.get(name);}},loadSource:async()=>'[]'});
  async function request(url,body,cookie=''){
    const req={url,method:body?'POST':'GET',body,headers:{host:'console.test',origin:'https://console.test',cookie}};
    const response={statusCode:200,headers:{},setHeader(k,v){this.headers[k]=v;},status(code){this.statusCode=code;return this;},json(value){this.body=value;return this;},send(value){this.body=value;return this;}};
    await handler(req,response);return response;
  }
  try{
    const a=await request('/api/start',{goal:'First task'});
    const b=await request('/api/start',{goal:'Second task'});
    assert.equal(a.statusCode,201);assert.equal(b.statusCode,201);
    const first=a.body.run_id,second=b.body.run_id;
    assert.notEqual(first,second);
    const firstCookie=a.headers['Set-Cookie'].split(';')[0],secondCookie=b.headers['Set-Cookie'].split(';')[0];
    assert.ok(a.headers['Set-Cookie'].includes(`Path=/api/runs/${first};`));
    const cookies=firstCookie+'; '+secondCookie;
    assert.equal((await request(`/api/runs/${first}/state`,null,cookies)).body.goal,'First task');
    assert.equal((await request(`/api/runs/${second}/state`,null,cookies)).body.goal,'Second task');
    assert.equal((await request(`/api/runs/${first}/state`,null,cookies)).body.run_id,first);
    await request(`/api/runs/${first}/control`,{action:'cancel'},cookies);
    assert.ok(boxes.get(first).files.has('cancel'));assert.equal(boxes.get(second).files.has('cancel'),false);
    assert.equal(boxes.get(first).stops,0);assert.equal(boxes.get(second).stops,0);
    // Reopening the first console after creating the second still returns the first run.
    assert.equal((await request(`/api/runs/${first}/state`,null,firstCookie)).body.goal,'First task');
    const forged=runCookieName(second)+'='+firstCookie.split('=')[1];
    assert.equal((await request(`/api/runs/${second}/state`,null,forged)).statusCode,404);
    assert.equal((await request(`/api/runs/${first}/state`,null)).statusCode,404);
    for(const [id,label] of [[first,'first trace'],[second,'second trace']]){
      const box=boxes.get(id);box.files.set('trace.json',Buffer.from(label));
      assert.equal((await request(`/api/runs/${id}/trace`,null,cookies)).body.toString(),label);
    }
    assert.equal((await request('/api/state',null,cookies)).body.status,'idle');
  }finally{
    for(const key of Object.keys(process.env))if(!(key in original))delete process.env[key];
    Object.assign(process.env,original);
  }
});
