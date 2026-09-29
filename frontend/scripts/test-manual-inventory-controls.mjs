import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const catalog = { rooms: [{ id: 'bedroom', name: 'Bedroom' }], items: [
  ...Array.from({ length: 70 }, (_, i) => ({ id: `a${i}`, name: `A item ${i}`, cuft: 1, weight: 7, description: '' })),
  { id: 'sofa', name: 'Sectional sofa', cuft: 150, weight: 1050, description: '' },
] };
const room = id => ({ id, name: id, room_type_id: 'bedroom', items: { sofa: 3 }, custom_items: [{ id: 'custom', name: 'Bed King', cuft: 80, quantity: 1 }] });
const state = [catalog, [room('Bedroom'), room('Other room')], ''];
let cursor = 0;
const hooks = { ...React,
  useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
  useEffect() {}, useLayoutEffect() {}, useRef: value => ({ current: value }),
};
const exports = {};
const source = readFileSync(new URL('../src/ManualInventoryModal.tsx', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
  exports, require: name => name === 'react' ? hooks : name.endsWith('.css') ? {} : name === './dimensions' ? { dimensionFeet: () => null } : require(name),
});
function render() { cursor = 0; return exports.default({ draftKey: 'test', loadCatalog: async () => catalog, submit: async () => {}, onClose() {} }); }
function find(node, label) {
  if (!node || typeof node !== 'object') return undefined;
  if (node.props?.['aria-label'] === label) return node;
  for (const child of React.Children.toArray(node.props?.children)) { const match = find(child, label); if (match) return match; }
}
let tree = render();
find(tree, 'Remove all Sectional sofa from Bedroom').props.onClick();
assert.equal(state[1][0].items.sofa, 0);
assert.equal(state[1][1].items.sofa, 3);
tree = render();
find(tree, 'Remove all Bed King from Bedroom').props.onClick();
assert.equal(state[1][0].custom_items.length, 0);
assert.equal(state[1][1].custom_items.length, 1);
state[2] = 'Other room';
const html = renderToStaticMarkup(render());
assert(html.includes('Sectional sofa'));
assert(html.indexOf('Sectional sofa') < html.indexOf('A item 0'));
assert(html.includes('Bed King'));
console.log('Summary removal is room-scoped; selected catalog and custom items are visible without searching.');
