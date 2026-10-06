import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { randomUUID } from 'node:crypto';

const source = readFileSync(new URL('../src/ManualInventoryModal.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  function roomsFromRows(');
const end = source.indexOf('  useLayoutEffect(', start);
const state = { crypto: { randomUUID }, linkCatalogItem: item => item, packingItemName: name => name, structuredClone };
vm.createContext(state);
vm.runInContext(ts.transpile(source.slice(start, end), { target: ts.ScriptTarget.ES2022 }), state);
const catalog = { rooms: [{ id: 'bedroom', name: 'Bedroom' }], items: [] };
const rooms = state.roomsFromRows([
  { name: 'Small Box (CP)', room: 'Bedroom', amount: 2, unit_cuft: 3 },
  { name: 'Small Box (PBO)', room: 'Bedroom', amount: 5, unit_cuft: 3 },
  { name: 'Small Box (PBO)', room: 'Bedroom', amount: 1, unit_cuft: 4 },
], catalog);
assert.equal(rooms[0].custom_items.length, 3, 'Stored rows must remain individually editable');
assert.deepEqual(Array.from(rooms[0].custom_items, item => item.quantity), [2, 5, 1]);
state.serverRooms = rooms;
state.saved = undefined;
const loadLine = source.split('\n').find(line => line.includes('const loaded: Room[] ='));
vm.runInContext(ts.transpile(loadLine + '\nloaded[0].custom_items[0].quantity = 1;'), state);
assert.equal(rooms[0].custom_items[0].quantity, 2, 'Display transformations must not change the save baseline');
console.log('Inventory loading preserves stored rows and an independent save baseline.');


// Restored edits must enter the save queue before Done calculates pricing.
const actionExports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/inventoryActions.ts', import.meta.url), 'utf8'),
  {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, {exports: actionExports});
const effectStart = source.indexOf('  useEffect(() => {', source.indexOf('  function flush()'));
const effectEnd = source.indexOf('  useEffect(() => {', effectStart + 1);
for (const changed of [false, true]) {
  const before = [{id:'bedroom',name:'Bedroom',room_type_id:'bedroom',items:{chair:1}}];
  const restored = structuredClone(before);
  if (changed) restored[0].items.chair = 3;
  const context = {catalog:{items:[{id:'chair',name:'Chair',cuft:10}]}, rooms:restored,
    latest:{current:null}, loadedRooms:{current:restored}, savedRooms:{current:before},
    dirty:{current:false},pending:{current:null},inventoryActions:actionExports.inventoryActions,
    useEffect:fn=>fn(),setSaveStatus(){},window:{setTimeout:()=>1,clearTimeout(){}}};
  vm.runInNewContext(ts.transpile(source.slice(effectStart,effectEnd), {target:ts.ScriptTarget.ES2022}),context);
  assert.equal(context.dirty.current,changed);
  assert.equal(context.pending.current,changed ? restored : null);
}
console.log('Restored changes are queued; unchanged inventory does not autosave.');
