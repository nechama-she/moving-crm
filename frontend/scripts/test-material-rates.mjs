import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const prefix='__ld_packing__:';
const exports={};
const source=readFileSync(new URL('../src/LongDistanceMaterialsCard.tsx',import.meta.url),'utf8');
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,
  {exports,require:name=>name==='./LongDistancePackingCard'?{PACKING_CARD_PREFIX:prefix,isPackingCard:row=>row.comments.startsWith(prefix)}:require(name)});
const defaults=exports.materialRows([]);
assert.equal(defaults.length,30);
assert.equal(defaults[14].packing_price,'1.5');
assert.equal(defaults[17].unpacking_price,'0');
const services=[{name:'Packing',rate_text:'',comments:prefix+JSON.stringify({full:'2',items:[{id:'old'}]})}];
const saved=exports.withMaterials(services);
assert.equal(JSON.parse(saved[0].comments.slice(prefix.length)).full,'2');
assert.equal(exports.materialRows(saved).length,30);
assert.equal(exports.materialRows(exports.withMaterials(saved,[])).length,0);
assert.equal(services[0].comments.includes('materials'),false);
for(const editing of [false,true]) {
  const html=renderToStaticMarkup(React.createElement(exports.default,{services:saved,editing,onChange:()=>{}}));
  assert.match(html,/Materials rates/);
  assert.match(html,/Unpacking/);
  assert.equal(html.includes('Add material'),editing);
  assert.equal(html.includes('type="number"'),editing);
}
console.log('Materials defaults, persistence, empty catalog, and edit/read views passed.');
