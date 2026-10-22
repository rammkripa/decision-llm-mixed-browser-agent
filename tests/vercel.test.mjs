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
