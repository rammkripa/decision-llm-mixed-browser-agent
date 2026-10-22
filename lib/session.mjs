import { createHmac, timingSafeEqual } from 'node:crypto';
export function sign(value, secret) {
  const payload=Buffer.from(JSON.stringify(value)).toString('base64url');
  return payload+'.'+createHmac('sha256',secret).update(payload).digest('base64url');
}
export function verify(value,secret) {
  try {
    const parts=value.split('.');
    if(parts.length!==2)return null;
    const [payload,signature]=parts;
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

export const validRunId = value => typeof value === 'string' && /^minotaur-[a-f0-9]{32}$/.test(value);
export function runCookieName(id) {
  if (!validRunId(id)) throw new Error('Invalid run ID');
  return 'minotaur_run_' + id.slice(9);
}
export function sessionForRun(cookies, id, secret) {
  if (!validRunId(id)) return null;
  const prefix = runCookieName(id) + '=';
  const cookie = (cookies || '').split(';').map(value => value.trim()).find(value => value.startsWith(prefix));
  const session = verify(cookie?.slice(prefix.length) || '', secret);
  return session?.name === id ? session : null;
}
