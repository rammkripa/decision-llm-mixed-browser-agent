import { createHmac, timingSafeEqual } from 'node:crypto';
export function sign(value, secret) {
  const payload=Buffer.from(JSON.stringify(value)).toString('base64url');
  return payload+'.'+createHmac('sha256',secret).update(payload).digest('base64url');
}
export function verify(value,secret) {
  try {
    const [payload,signature]=value.split('.');
    const expected=createHmac('sha256',secret).update(payload).digest();
    const actual=Buffer.from(signature,'base64url');
    if(actual.length!==expected.length||!timingSafeEqual(actual,expected)) return null;
    const data=JSON.parse(Buffer.from(payload,'base64url'));
    return typeof data.name==='string' && /^minotaur-[a-f0-9]{32}$/.test(data.name) && data.expires>Date.now()?data:null;
  } catch {return null;}
}
export function validTask(body) {
  const goal=body?.goal, url=body?.url||'https://www.google.com';
  if(typeof goal!=='string'||!goal.trim()||goal.trim().length>2000)throw new Error('Enter a task of 1–2,000 characters.');
  if(typeof url!=='string'||url.length>2000)throw new Error('Enter a valid starting URL.');
  const parsed=new URL(url);
  if(!['http:','https:'].includes(parsed.protocol)||!parsed.hostname||parsed.username||parsed.password)throw new Error('Enter an HTTP or HTTPS URL without credentials.');
  return {goal:goal.trim(),url};
}
