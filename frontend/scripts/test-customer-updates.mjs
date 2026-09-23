import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/useCustomerUpdates.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
let effect, cleanup, refreshes = 0, requests = 0;
const sockets = [], timers = [];
class Socket {
  constructor(url) { this.url=url; sockets.push(this); }
  close() { this.onclose?.(); }
}
const exports = {};
vm.runInNewContext(code, {
  exports, require: () => ({useEffect: fn => {effect=fn;}, useRef:value=>({current:value}), useState:value=>[value,()=>{}]}),
  window:{__WS_URL__:'wss://example.test/live'}, WebSocket:Socket, AbortController,
  fetch: async () => { requests++; return {ok:true,status:200,json:async()=>({token:'scoped-token'})}; },
  setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout:()=>{},
});
const settle = () => new Promise(resolve=>setImmediate(resolve));
exports.useCustomerUpdates('/api/public-moves/move','link','session',async()=>{refreshes++;});
cleanup=effect();
await settle();
assert.equal(requests,1);
assert.equal(sockets.length,1);
sockets[0].onopen();
await settle();
assert.equal(refreshes,1); // Subscription catch-up only.
assert.equal(timers.length,0); // No refresh/heartbeat polling timer while connected.
sockets[0].onmessage({data:JSON.stringify({type:'staff_event'})});
assert.equal(refreshes,1);
sockets[0].onmessage({data:JSON.stringify({type:'customer_move_updated'})});
await settle();
assert.equal(refreshes,2);
assert.equal(requests,1); // Notification does not mint another token.
// A broken connection gets three attempts, then stops instead of looping forever.
sockets[0].close();
for(let i=0;i<3;i++) { timers[i](); await settle(); sockets.at(-1).close(); }
assert.equal(timers.length,3);
assert.equal(requests,4);
cleanup();
assert.equal(timers.length,3);
console.log('Customer updates: event-driven refresh, isolation, no polling, bounded reconnects passed.');
