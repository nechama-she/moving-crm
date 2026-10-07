import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import vm from 'node:vm';
import ts from 'typescript';
const exports={};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/inventoryActions.ts',import.meta.url),'utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,crypto:{randomUUID}});
const {inventoryActions,catalogInventoryId,hasInventoryEdits}=exports;
const catalog=[{id:'chair',name:'Chair',cuft:30},{id:'box',name:'Small Box',cuft:2}];
const before=[{id:'room',room_type_id:'bedroom',name:'Bedroom',items:{},custom_items:[
 {id:'row-1',catalog_item_id:'chair',name:'Chair',quantity:1,cuft:30},
 {id:'row-2',catalog_item_id:'chair',name:'Chair',quantity:1,cuft:30},
 {id:'box-row',catalog_item_id:'box',name:'Small Box (CP)',mover_pack:true,quantity:3,cuft:2},
]}];
const diff=after=>JSON.parse(JSON.stringify(inventoryActions(before,after,catalog)));
let after=structuredClone(before);after[0].custom_items[0].quantity=4;
assert.deepEqual(diff(after).update,[{id:'row-1',fields:{quantity:4}}]);
assert.deepEqual(diff(after).add,[]);
after=structuredClone(before);after[0].custom_items[2].name='Small Box (PBO)';after[0].custom_items[2].mover_pack=false;
assert.deepEqual(diff(after).update,[{id:'box-row',fields:{mover_pack:false}}]);
assert.deepEqual(diff(after).delete,[]);
after=structuredClone(before);after[0].custom_items.splice(0,1);
assert.deepEqual(diff(after).delete,['row-1']);
after=structuredClone(before);after[0].name='Office';
assert.deepEqual(diff(after).rooms.update,[{id:'room',name:'Office'}]);
assert.deepEqual(diff([]).rooms.delete,['room']);
assert.deepEqual(diff([]).delete,[]);
after=structuredClone(before);after[0].items.chair=2;
const added=diff(after).add[0];assert.equal(added.catalog_item_id,'chair');assert.equal(added.quantity,2);assert.equal('name' in added,false);
assert.equal(added.id,catalogInventoryId(after[0],'chair'));
assert.equal(hasInventoryEdits(inventoryActions(before,before,catalog)),false);
console.log('ID-based sparse updates, duplicate items, packing, deletes, rooms and catalog additions passed.');

after=structuredClone(before);after[0].custom_items[0].going=false;
assert.deepEqual(diff(after).update,[{id:'row-1',fields:{going:false}}]);
after=structuredClone(before);after[0].custom_items[0].cuft=12;
assert.deepEqual(diff(after).update,[{id:'row-1',fields:{cuft:12}}]);
after=structuredClone(before);after[0].custom_items[0].name='My chair';after[0].custom_items[0].name_override=true;
assert.deepEqual(diff(after).update,[{id:'row-1',fields:{name:'My chair'}}]);
