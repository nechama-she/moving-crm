import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const exports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/inventoryBoxes.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports });
const { boxQuantity } = exports;
for (const name of ['Small Box (CP)', 'Dish Box (PBO)', '27 Gallon Plastic Bin', 'Plastic BinsSmall',
  'Amazon Tote Bags', 'Tote', 'Suitcase Carry-On', 'Duffel Bag', 'Duffle Bag', 'Moving Bags', 'Dishpack Box']) {
  assert.equal(boxQuantity(name, 7), 7, name);
}
for (const name of ['Box Spring Queen', 'Box Springs', 'Cat Litter Box', 'Toy Bookshelf with Bins',
  'Cabinet', 'Bean Bags', 'Punching Bag', 'Sleeping Bag', 'Chair']) {
  assert.equal(boxQuantity(name, 7), 0, name);
}
assert.equal(boxQuantity('Box', 0), 0);
console.log('Inventory box counts passed.');
