import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const exports = {};
const source = readFileSync(new URL('../src/customerQuestionNavigation.ts', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports });
const { groupTerms, needsTermAnswer, requiredQuestionTarget } = exports;
const question = (id, saved, acknowledge = false) => ({
  id, rule_id: id, question: id, answers: [{ id: 'yes', acknowledge }], saved,
});
const complete = question('answered', { answer_id: 'yes', acknowledged: true });
const missing = question('missing');
const pending = question('pending', { answer_id: 'yes', pending: true });
const acknowledgement = question('ack', { answer_id: 'yes', acknowledged: false }, true);
const invalid = question('invalid', { answer_id: 'removed-answer' });
const groups = groupTerms([complete, missing, pending, acknowledgement, invalid]);
assert.equal(needsTermAnswer(complete), false);
for (const entry of [missing, pending, acknowledgement, invalid]) assert.equal(needsTermAnswer(entry), true);
assert.equal(requiredQuestionTarget(['items'], groups).termsIndex, 1);
assert.equal(requiredQuestionTarget(['storage', 'items'], groups).step, 'storage');
assert.equal(requiredQuestionTarget(['shuttle'], groups).step, 'shuttle');
missing.saved = { answer_id: 'yes', acknowledged: true };
assert.equal(needsTermAnswer(missing), false);
assert.equal(requiredQuestionTarget(['items'], groups).termsIndex, 2);
const sameGroup = groupTerms([complete, { ...missing, rule_id: 'answered', saved: undefined }]);
assert.equal(sameGroup.length, 1);
assert.equal(sameGroup[0].some(needsTermAnswer), true);
assert.equal(requiredQuestionTarget(['items'], sameGroup).termsIndex, 0);
console.log('Missing-question navigation, grouped terms, and saved-answer status checks passed.');
