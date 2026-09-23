import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/QuestionReferenceImages.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
let index=0, now=1000, requests=0, nextTimer=0;
const slots=[], effects=[], timers=new Map(), listeners=new Map();
const document={visibilityState:'visible',addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:n=>listeners.delete(n)};
const hooks={
 useState(initial){const i=index++;if(!(i in slots))slots[i]=initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},
 useRef(initial){const i=index++;return slots[i]??=( {current:initial} );},
 useEffect(fn,deps){const i=index++;const old=slots[i];if(!old||deps.some((v,k)=>v!==old.deps[k])){old?.cleanup?.();slots[i]={deps};effects.push(()=>{slots[i].cleanup=fn();});}}
};
const exports={};
vm.runInNewContext(code,{exports,require:()=>hooks,React:{createElement:()=>null},document,AbortController,
 Date:{now:()=>now},setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id),
 fetch:async()=>{requests++;return {ok:true,json:async()=>({images:{Plant:[{name:'Plant',room:'Room',url:'photo',expires_at:10}]}})};}});
function render(active){index=0;exports.default({name:'Plant',endpoint:'/images',linkKey:'key',session:'session',active});while(effects.length)effects.shift()();}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
render(false);await settle();assert.equal(requests,0);
render(true);await settle();assert.equal(requests,1);assert.equal(timers.size,1);
render(false);assert.equal(timers.size,0);
render(true);await settle();assert.equal(requests,1); // Reuse unexpired URLs.
document.visibilityState='hidden';listeners.get('visibilitychange')();render(true);assert.equal(timers.size,0);
now=11000;document.visibilityState='visible';listeners.get('visibilitychange')();render(true);await settle();assert.equal(requests,2);
assert.equal(timers.size,0); // Already-expired provider response must not cause a loop.
for(const slot of slots)slot?.cleanup?.();
assert.equal(timers.size,0);
console.log('Photo renewal: inactive steps/tabs stop, valid links reused, expired links renewed on return, no stale-URL retry loop.');
