import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const code = ts.transpileModule(readFileSync(new URL('../src/customerSession.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
let now=1000, requests=0, status=200, pending=false, aborted=false;
const storage=new Map(), events=[];
const window={location:{origin:'https://crm.test'},dispatchEvent:event=>events.push(event.detail),fetch:async(input,init)=>{
  requests++;
  if(pending)return new Promise((resolve,reject)=>init.signal.addEventListener('abort',()=>{aborted=true;reject(new DOMException('Aborted','AbortError'));}));
  return new Response('{}',{status});
}};
const exports={};
vm.runInNewContext(code,{exports,require:()=>({API_BASE:''}),window,URL,Request,Headers,AbortController,DOMException,
  CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
  Date:{now:()=>now},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)}});
exports.installCustomerSessionFetch();
const path='/api/public-moves/move/details';
const headers=token=>({'x-public-session':token});
storage.set('old','legacy-token');assert.equal(exports.loadCustomerSession('old'),'');assert.equal(storage.has('old'),false);
exports.registerCustomerSession('valid',2000);
await window.fetch(path,{headers:headers('valid')});assert.equal(requests,1);
now=2000;
await assert.rejects(window.fetch(path,{headers:headers('valid')}),{name:'AbortError'});assert.equal(requests,1);
exports.registerCustomerSession('new',4000);pending=true;
const inflight=window.fetch(path,{headers:headers('new')});
exports.expireCustomerSession('new');await assert.rejects(inflight,{name:'AbortError'});assert.ok(aborted);
pending=false;status=401;exports.registerCustomerSession('rejected',4000);
await assert.rejects(window.fetch(path,{headers:headers('rejected')}),{name:'AbortError'});
const before=requests;await assert.rejects(window.fetch(path,{headers:headers('rejected')}),{name:'AbortError'});assert.equal(requests,before);
status=200;
await window.fetch('/api/public-moves/move/send-code');
await window.fetch('https://storage.test/photo',{headers:headers('valid')});
assert.equal(requests,before+2);
assert.ok(events.includes('valid')&&events.includes('new')&&events.includes('rejected'));
console.log('Customer session: expired and unknown tokens blocked before network, active requests aborted, server rejection stops further requests; public verification and external uploads unaffected.');
