import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
function load(name) {
  const exports = {};
  const source = readFileSync(new URL(`../src/${name}.tsx`, import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,
    {exports,require: id => id === './CustomerMaterialItems' ? load('CustomerMaterialItems') : require(id)});
  return exports;
}
const Component = load('CustomerPackingOptions').default;
const config = {cubic_feet:100,rates:{},items:[{id:'sofa',label:'Sofa',packing_material:'plastic',labor_price:26,material_price:12}],
  other_inventory:[{id:'bed',inventory_id:'bed',label:'Bed King',room:'Bedroom',protection:'fragile'}]};
const selection = {mode:'none',unpacking:false,item_ids:[]};
const render = (stage, answer) => renderToStaticMarkup(React.createElement(Component,{config,selection:{...selection,has_additional_protection:answer},stage,disabled:false,onChange(){}}));
const service = render('service',null);
assert(service.includes('Choose your packing service'));
assert(!service.includes('Do you have any other'));
const protection = render('protection',null);
assert(protection.includes('Fabric items must be covered with plastic'));
assert(protection.includes('Required material:'));
assert(protection.includes('Plastic'));
assert(protection.includes('Packing only'));
assert(protection.includes('$26.00'));
assert(protection.includes('$38.00'));
assert(protection.includes('No, I have no other fabric or fragile items'));
assert(!protection.includes('Bed King'));
const yes = render('protection',true);
assert(yes.includes('Bed King: fabric'));
assert(yes.includes('Bed King: fragile'));
assert(!yes.includes('Close item list'));
assert(!yes.includes('Add unpacking'));
assert(!render('protection',false).includes('Bed King'));
console.log('Protection follow-up, material labels, purchase prices, and extra-item classification passed.');
