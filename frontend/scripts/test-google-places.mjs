import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/googlePlaces.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } });
const { selectedAddress } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const component = (type, text) => ({ types: [type], longText: text, shortText: text });
const place = {
  id: 'place-id', formattedAddress: 'Miami, FL, USA',
  addressComponents: [component('locality', 'Miami'), component('administrative_area_level_1', 'FL'), component('country', 'US')],
};
assert.equal(selectedAddress(place).city, 'Miami');
assert.equal(selectedAddress({ ...place, formattedAddress: '123 Main St, Miami, FL, USA' }).state, 'FL');
assert.equal(selectedAddress({ ...place, addressComponents: place.addressComponents.filter(c => !c.types.includes('locality')) }), null);
assert.equal(selectedAddress({ ...place, addressComponents: place.addressComponents.filter(c => !c.types.includes('administrative_area_level_1')) }), null);
assert.equal(selectedAddress({ ...place, id: '' }), null);
assert.equal(selectedAddress({ ...place, addressComponents: [component('administrative_area_level_2', 'County'), ...place.addressComponents.slice(1)] }), null);
assert.equal(selectedAddress({ ...place, addressComponents: [component('sublocality_level_1', 'Brooklyn'), ...place.addressComponents.slice(1)] }).city, 'Brooklyn');
console.log('Google address component validation: 7 checks passed.');
