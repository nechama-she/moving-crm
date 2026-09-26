import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/PricingPage.tsx', import.meta.url), 'utf8');
const tree = ts.createSourceFile('PricingPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'destinationFromAddress');
assert.ok(declaration);
const code = ts.transpileModule(declaration.getText(tree), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
const context = vm.createContext({});
vm.runInContext(code, context);
const resolve = context.destinationFromAddress;

assert.equal(resolve('Monroe, Georgia', ['FL', 'GA'], 'GA', ''), 'GA');
assert.equal(resolve('Monroe, Georgia', ['GA (300-305)', 'GA(306-309)'], 'GA', '30655'), 'GA(306-309)');
assert.equal(resolve('Monroe, Georgia', ['GA (300-305)'], 'GA', '30655'), '');
assert.equal(resolve('Monroe, Georgia', ['GA (300-305)', 'GA (306-309)'], 'GA', ''), '');
assert.equal(resolve('Monroe, Georgia', ['FL', 'NY'], 'GA', ''), '');
assert.equal(resolve('Monroe, Georgia', ['GA (300-305)', 'GA'], 'GA', ''), 'GA');
console.log('6 pricing address checks passed.');
