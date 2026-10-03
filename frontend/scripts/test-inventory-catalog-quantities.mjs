import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const exports = {};
const source = readFileSync(new URL('../src/inventoryCatalogQuantities.ts', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, {exports});
const {catalogQuantity, setCatalogQuantity} = exports;
const room = {items:{bin:1}, custom_items:[
  {id:'saved',catalog_item_id:'bin',quantity:3,cuft:6,going:false,mover_pack:true},
  {id:'other',catalog_item_id:'chair',quantity:2},
]};
assert.equal(catalogQuantity(room,'bin'),4);
const added = setCatalogQuantity(room,'bin',5);
assert.equal(catalogQuantity(added,'bin'),5);
assert.equal(added.custom_items[0],room.custom_items[0]);
const reduced = setCatalogQuantity(added,'bin',2);
assert.equal(catalogQuantity(reduced,'bin'),2);
assert.equal(reduced.custom_items[0].cuft,6);
assert.equal(reduced.custom_items[0].going,false);
assert.equal(reduced.custom_items[0].mover_pack,true);
const removed = setCatalogQuantity(reduced,'bin',0);
assert.equal(catalogQuantity(removed,'bin'),0);
assert.equal(catalogQuantity(removed,'chair'),2);
assert.equal(catalogQuantity(room,'bin'),4);
assert.equal(catalogQuantity({items:{},custom_items:[]},'bin'),0);
assert.equal(catalogQuantity(setCatalogQuantity(room,'bin',1000),'bin'),999);
console.log('Saved inventory quantities, additions, reductions, removal, and metadata preservation passed.');
