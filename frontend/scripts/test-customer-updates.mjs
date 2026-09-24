import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const code = ts.transpileModule(readFileSync(new URL('../src/useCustomerUpdates.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const settle = () => new Promise(resolve=>setImmediate(resolve));
function harness({active=true,status=200,ws=true}={}) {
  let effect, requests=0, refreshes=0, sequence=0;
  const sockets=[], timers=new Map(), listeners=new Map();
  const window={__WS_URL__:ws?'wss://example.test/live':'', addEventListener:(name,fn)=>listeners.set(name,fn), removeEventListener:name=>listeners.delete(name)};
  const expire=()=>{active=false;listeners.get('expired')?.({detail:'session'});};
  class Socket { constructor(){sockets.push(this);} close(){this.closed=true;this.onclose?.();} }
  const exports={};
  vm.runInNewContext(code,{exports,require:name=>name==='react'?{useEffect:fn=>{effect=fn;},useRef:value=>({current:value}),useState:value=>[value,()=>{}]}:{CUSTOMER_SESSION_EXPIRED:'expired',customerSessionActive:()=>active,expireCustomerSession:expire},
    window,WebSocket:Socket,AbortController,fetch:async()=>{requests++;return {ok:status===200,status,json:async()=>({token:'token'})};},
    setTimeout:(fn,ms)=>{timers.set(++sequence,{fn,ms});return sequence;},clearTimeout:id=>timers.delete(id)});
  exports.useCustomerUpdates('/api/public-moves/move','key','session',async()=>{refreshes++;});
  const cleanup=effect();
  return {sockets,timers,expire,cleanup,get requests(){return requests;},get refreshes(){return refreshes;}};
}
const normal=harness();await settle();assert.equal(normal.requests,1);assert.equal(normal.refreshes,0);
normal.sockets[0].onopen();await settle();assert.equal(normal.refreshes,1);assert.equal(normal.timers.size,0);
normal.sockets[0].onmessage({data:JSON.stringify({type:'staff_event'})});assert.equal(normal.refreshes,1);
normal.sockets[0].onmessage({data:JSON.stringify({type:'customer_move_updated'})});await settle();assert.equal(normal.refreshes,2);
normal.expire();assert.ok(normal.sockets[0].closed);assert.equal(normal.timers.size,0);
normal.sockets[0].onmessage({data:JSON.stringify({type:'customer_move_updated'})});await settle();assert.equal(normal.refreshes,2);assert.equal(normal.requests,1);normal.cleanup();
const expired=harness({active:false});await settle();assert.equal(expired.requests,0);assert.equal(expired.refreshes,0);expired.cleanup();
const rejected=harness({status:401});await settle();assert.equal(rejected.requests,1);assert.equal(rejected.sockets.length,0);assert.equal(rejected.timers.size,0);rejected.cleanup();
const fallback=harness({ws:false});await settle();assert.equal(fallback.refreshes,1);assert.equal(fallback.requests,0);assert.equal(fallback.timers.size,0);fallback.cleanup();
const broken=harness();await settle();broken.sockets[0].onopen();await settle();broken.sockets[0].close();
for(let i=0;i<3;i++){const [id,timer]=[...broken.timers][0];broken.timers.delete(id);timer.fn();await settle();broken.sockets.at(-1).close();}
assert.equal(broken.requests,4);assert.equal(broken.timers.size,0);broken.cleanup();
console.log('Customer live updates: one initial load, pushed updates, expiry shutdown, 401 shutdown, fallback and bounded reconnects passed.');
