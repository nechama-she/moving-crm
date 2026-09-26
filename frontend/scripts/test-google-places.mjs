import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/googlePlaces.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}});
const {browserSuggestions,browserDrivingMeters}=await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
let requests=0;
let complete;
globalThis.window={google:{maps:{places:{AutocompleteService:class {
  getPlacePredictions(request,callback){requests++;assert.equal(request.componentRestrictions.country,'us');complete=callback;}
}}}}};
const controller=new AbortController();
const pending=browserSuggestions('existing-browser-key','125',controller.signal);
await Promise.resolve();
complete([{place_id:'place1',description:'125 Main St, Miami, FL'}],'OK');
assert.deepEqual(await pending,[{place_id:'place1',text:'125 Main St, Miami, FL'}]);
assert.equal(requests,1);
const cancelled=browserSuggestions('existing-browser-key','126',controller.signal);
await Promise.resolve();controller.abort();
assert.deepEqual(await cancelled,[]);
complete([{place_id:'stale',description:'Old result'}],'OK');
assert.deepEqual(await browserSuggestions('existing-browser-key','127',controller.signal),[]);
assert.equal(requests,2);
console.log('Browser Places: suggestions, cancellation and no repeated requests passed.');
window.google.maps.DirectionsService=class {
  route(request,callback){
    assert.equal(request.travelMode,'DRIVING');
    assert.equal(request.origin,'Main address');
    callback({routes:[{legs:[{distance:{value:12000}},{distance:{value:12140}}]}]},'OK');
  }
};
assert.equal(await browserDrivingMeters('existing-browser-key','Main address','Extra stop'),24140);
window.google.maps.DirectionsService=class {route(request,callback){callback(null,'REQUEST_DENIED');}};
await assert.rejects(browserDrivingMeters('existing-browser-key','Main address','Extra stop'),/Directions API access/);
console.log('Browser driving distances and provider errors passed.');
