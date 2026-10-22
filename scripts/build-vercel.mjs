import { mkdir, copyFile, readFile, writeFile, readdir } from 'node:fs/promises';
await mkdir('public', {recursive:true});
for (const file of ['landing.html','landing.js','task-examples.js','console.html','console.css','console.js','minotaur.png','minotaur-maze.png']) {
  await copyFile(`jev_ultrafast/static/${file}`, `public/${file==='landing.html'?'index.html':file}`);
}
// Ship only the agent source, never .env, traces, git history, or local artifacts.
const files=[];
for(const name of await readdir('jev_ultrafast')) {
  if(/\.(py|js)$/.test(name)) files.push({path:`jev_ultrafast/${name}`,content:(await readFile(`jev_ultrafast/${name}`)).toString('base64')});
}
await mkdir('deployment', {recursive:true});
await writeFile('deployment/source.json',JSON.stringify(files));
