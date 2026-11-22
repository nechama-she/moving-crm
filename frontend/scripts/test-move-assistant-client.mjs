// The move page assistant's connection to BoxBot: where it may send the page's session, what it sends, how it reads
// answers, and how it treats each failure.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = readFileSync(new URL('../src/moveAssistant/assistantClient.ts', import.meta.url), 'utf8')
  .replace(/import\.meta\.env\.MODE/g, '"production"');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;

let reply = {status: 200, body: {}};
const calls = [];
const window = {setTimeout, clearTimeout};
const exports = {};
vm.runInNewContext(code, {exports, require: () => ({}), window, AbortController, Response, JSON, Array,
  fetch: async (url, init) => { calls.push({url, init}); return new Response(JSON.stringify(reply.body), {status: reply.status}); }});
const {assistantConfig, callAssistant, displayText, AssistantError, BUSY_TEXT} = exports;
// Values made inside the sandbox, compared as plain data.
const plain = value => value === undefined ? value : JSON.parse(JSON.stringify(value));

// Only a path on this site: the page's session goes with every message.
for (const [url, expected] of [['/api/customer-chat', '/api/customer-chat'], ['/api/customer-chat/', '/api/customer-chat'],
  ['https://example.com/chat', null], ['//example.com/chat', null], ['/api/chat?x=1', null], ['', null], [undefined, null]]) {
  window.__MOVE_ASSISTANT__ = url === undefined ? undefined : {url};
  assert.deepEqual(plain(assistantConfig()), expected && {url: expected}, String(url));
}

const config = {url: '/api/customer-chat'};
const base = {config, accessId: 'move 1', audience: 'customer', headers: {'x-public-link': 'link', 'x-public-session': 'session', other: 'x'}, signal: new AbortController().signal};

// The opening event and a message: the page's two headers only, and the body BoxBot expects.
reply = {status: 200, body: {reply: null, history: [{role: 'user', text: 'Hi', ts: 1}, {role: 'assistant', text: 'Hello'}, {role: 'user', text: ''}]}};
let answer = await callAssistant({...base, open: true});
assert.equal(calls[0].url, '/api/customer-chat/move%201');
assert.deepEqual(JSON.parse(calls[0].init.body), {event: {type: 'open'}, audience: 'customer'});
assert.deepEqual(plain(calls[0].init.headers), {'Content-Type': 'application/json', 'x-public-link': 'link', 'x-public-session': 'session'});
assert.equal(answer.reply, null);
assert.deepEqual(plain(answer.history.map(row => [row.role, row.text])), [['customer', 'Hi'], ['assistant', 'Hello']]);

// Only what the window can show: up to 4 quick replies, valid slots, known actions.
reply = {status: 200, body: {reply: 'Pick a time', quick_replies: ['a', 'b', '', 'c', 'd', 'e', 7], reverify: 'yes',
  cards: [{type: 'slots', days: [{date: '2026-11-24', label: 'Tue', slots: [{start: '2026-11-24T10:00:00-05:00', label: '10 AM'}, {label: 'no start'}]}, {label: 'empty', slots: []}]}, {type: 'other'}],
  action: {type: 'open_signing', signature_id: 'sig-1'}}};
answer = await callAssistant({...base, audience: 'rep', message: 'Book a time'});
assert.deepEqual(JSON.parse(calls[1].init.body), {message: 'Book a time', audience: 'rep'});
assert.deepEqual(plain(answer.quickReplies), ['a', 'b', 'c', 'd']);
assert.equal(answer.cards.length, 1);
assert.deepEqual(plain(answer.cards[0].days.map(day => [day.label, day.slots.length])), [['Tue', 1]]);
assert.deepEqual(plain(answer.action), {type: 'open_signing', signatureId: 'sig-1'});
assert.equal(answer.reverify, false);
for (const action of [{type: 'open_signing'}, {type: 'sign_now', signature_id: 'x'}, 'open_signing'])
  { reply = {status: 200, body: {reply: 'x', action}}; assert.equal((await callAssistant({...base, message: 'x'})).action, undefined); }
reply = {status: 200, body: {reply: 'x', action: {type: 'open_bol_signing'}, reverify: true}};
answer = await callAssistant({...base, message: 'x'});
assert.deepEqual(plain(answer.action), {type: 'open_bol_signing'});
assert.equal(answer.reverify, true);

// Failures: 401 asks the page to verify again; busy shows the server's text or the window's own.
const failure = async (status, body) => { reply = {status, body}; return callAssistant({...base, message: 'x'}).then(() => null, error => error); };
let error = await failure(401, {detail: 'Session expired'});
assert.ok(error instanceof AssistantError); assert.equal(error.kind, 'session');
error = await failure(429, {error: 'Too many requests'});
assert.equal(error.kind, 'busy'); assert.equal(error.message, BUSY_TEXT);
error = await failure(503, {detail: 'BoxBot is updating. Try again soon.'});
assert.equal(error.kind, 'busy'); assert.equal(error.message, 'BoxBot is updating. Try again soon.');
error = await failure(504, {});
assert.equal(error.kind, 'busy');
error = await failure(500, {});
assert.equal(error.kind, 'failed');

// A booked slot reads as its time, as written (the company's time zone); anything else is left as it is.
assert.equal(displayText('Book 2026-11-24T10:00:00-05:00'), 'Book Tue, Nov 24 at 10 AM');
assert.equal(displayText('Book 2026-11-24T13:30:00Z'), 'Book Tue, Nov 24 at 1:30 PM');
assert.equal(displayText('Book a video walkthrough'), 'Book a video walkthrough');
assert.equal(displayText('Book 2026-11-24T25:00:00Z'), 'Book 2026-11-24T25:00:00Z');
console.log('move assistant client: ok');
