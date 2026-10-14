import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/DeliveryDateCalendar.tsx', import.meta.url),'utf8');
const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const exports = {};
vm.runInNewContext(compiled,{exports,require:name=>name.endsWith('.css') ? {} : require(name),Date});
for (const [date,periods] of [['2026-10-01',0],['2026-10-06',1],['2026-10-29',1],['2026-11-08',2]]) {
  assert.equal(exports.storagePeriods('2026-09-01',date,30,30).periods,periods);
}
assert.equal(exports.storagePeriods('2026-03-01','2026-03-31',30,30).elapsed,30);
const html = renderToStaticMarkup(React.createElement(exports.default,{value:'2099-09-20',minDate:'2099-09-15',freeDays:30,onChange:()=>{}}));
assert(!html.includes('type="date"'));
assert.match(html,/September 2099/);
assert.match(html,/data-date="2099-09-14" disabled=""/);
assert.match(html,/data-date="2099-09-20"[^>]*aria-pressed="true"/);
assert.match(html,/aria-label="Previous month" disabled=""/);
assert.match(html,/Free storage through Oct 15, 2099/);
assert.match(html,/aria-label="Next month"/);
console.log('Custom storage calendar: date boundaries, partial periods, selection, disabled days, month controls, and non-native markup passed.');
