import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/liveSwitchVideo.ts', import.meta.url), 'utf8');
const exports = {};
vm.runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText, {exports, Uint8Array});
const normalize = exports.normalizeLiveSwitchVideo;
const bytes = Buffer.from([0, 0, 0, 24, ...Buffer.from('ftypisom'), 0, 0, 0, 0, ...Buffer.from('isommp42')]);
for (const type of ['binary/octet-stream', 'application/octet-stream', '']) {
  const result = await normalize(new Blob([bytes], {type}));
  assert.equal(result.type, 'video/mp4');
  assert.deepEqual(Buffer.from(await result.arrayBuffer()), bytes);
}
const video = new Blob([bytes], {type: 'video/mp4'});
assert.equal(await normalize(video), video);
for (const blob of [new Blob([], {type: 'video/mp4'}), new Blob(['<html>Error</html>'], {type: 'binary/octet-stream'}), new Blob(['{"error":"denied"}'], {type: 'application/json'})]) {
  await assert.rejects(normalize(blob), /not a downloadable video/);
}
console.log('LiveSwitch video: generic binary MP4 accepted, bytes preserved, empty/error bodies rejected.');
