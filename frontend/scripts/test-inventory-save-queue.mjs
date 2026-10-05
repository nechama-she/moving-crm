import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/ManualInventoryModal.tsx', import.meta.url), 'utf8');
const actionExports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/inventoryActions.ts', import.meta.url), 'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, {exports:actionExports});
const flush = source.slice(source.indexOf('  function flush()'), source.indexOf('  useEffect(() => {', source.indexOf('  function flush()')));
const save = source.slice(source.indexOf('  async function save('), source.indexOf('  return <div className="cm-modal-overlay"', source.indexOf('  async function save(')));
function setup() {
  const snapshot = [{name:'Bedroom',room_type_id:'bedroom',items:{chair:1}}];
  const calls = [], releases = [];
  const state = {
    Error, rooms:snapshot, latest:{current:snapshot}, pending:{current:snapshot}, inFlight:{current:null},
    saving:{current:null}, dirty:{current:true}, catalog:{rooms:[]}, busy:false,
    savedRooms:{current:null},requestIds:{current:new WeakMap()},retrySnapshot:{current:null},inventoryActions:actionExports.inventoryActions,
    crypto:{randomUUID:()=>String(calls.length)}, draftKey:'test', localStorage:{removeItem(){}},
    setSaveStatus(){},setError(error){state.error=error;},setBusy(){},setFinishing(){},closed:false,calculations:0,
    onDone:async()=>{state.calculations++;},
    submitActionsRef:{current:(request_id,actions)=>{calls.push({request_id,actions});return new Promise((resolve,reject)=>releases.push({resolve,reject}));}},
  };
  state.onClose = () => {state.closed = true;};
  vm.createContext(state);
  vm.runInContext(ts.transpile(flush + save), state);
  return {state,calls,releases};
}

// Done waits for the existing save, without resubmitting that same snapshot.
{
  const {state,calls,releases} = setup();
  const saving = state.flush();
  const done = state.save();
  assert.equal(calls.length,1);
  assert.equal(state.closed,false);
  assert.equal(state.calculations,0);
  releases[0].resolve();
  await Promise.all([saving,done]);
  assert.equal(calls.length,1);
  assert.equal(state.closed,true);
  assert.equal(state.calculations,1);
}
// New edits during a request must still be saved before Done closes the editor.
{
  const {state,calls,releases} = setup();
  state.flush();
  state.rooms = [{name:'Bedroom',room_type_id:'bedroom',items:{chair:2}}];
  state.latest.current = state.rooms;
  state.pending.current = state.rooms;
  const done = state.save();
  releases[0].resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length,2);
  assert.equal(calls[1].actions[0].value.quantity,2);
  assert.equal(state.closed,false);
  releases[1].resolve();
  await done;
  assert.equal(state.closed,true);
}
// Failed requests keep the pending snapshot and leave the editor open for retry.
{
  const {state,calls,releases} = setup();
  const done = state.save();
  releases[0].reject(new Error('offline'));
  await done;
  assert.equal(state.closed,false);
  assert.equal(state.pending.current,state.rooms);
  const retry = state.save();
  assert.equal(calls.length,2);
  assert.equal(calls[0].request_id,calls[1].request_id);
  releases[1].resolve();
  await retry;
  assert.equal(state.closed,true);
}
console.log('Inventory saves avoid duplicates, retain new edits, and retry failures.');

// Done calculates even when autosave has already finished; failures stay open.
{
  const {state,calls} = setup();
  state.dirty.current = false;
  state.pending.current = null;
  state.onDone = async () => { throw new Error('Pricing unavailable'); };
  await state.save();
  assert.equal(calls.length,0);
  assert.equal(state.closed,false);
  assert.equal(state.error,'Pricing unavailable');
  state.onDone = async () => { state.calculations++; };
  await state.save();
  assert.equal(state.calculations,1);
  assert.equal(state.closed,true);
}
// Closing with X/Escape does not calculate.
{
  const {state} = setup();
  state.dirty.current = false;
  state.pending.current = null;
  await state.save(false);
  assert.equal(state.calculations,0);
  assert.equal(state.closed,true);
}
