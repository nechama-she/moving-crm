import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function setup(refresh) {
  const timers = new Map();
  let id = 0;
  const context = {
    exports: {},
    queueMicrotask(fn) { timers.set(++id, fn); },
  };
  const source = readFileSync(new URL('../src/queueRefreshScheduler.ts', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return {
    scheduler: context.exports.createQueueRefreshScheduler(refresh),
    timers,
    tick() {
      const [key, callback] = timers.entries().next().value;
      timers.delete(key);
      return callback();
    },
  };
}

test('event bursts share one refresh and retain both queue flags', async () => {
  const calls = [];
  const { scheduler, timers, tick } = setup(async (...flags) => calls.push(flags));
  scheduler.request(true, false);
  for (let i = 0; i < 100; i++) scheduler.request(false, true);
  assert.equal(timers.size, 1);
  await tick();
  assert.deepEqual(calls, [[true, true]]);
  assert.equal(timers.size, 0);
});

test('events during a slow request produce one later refresh without overlap', async () => {
  let finish;
  const calls = [];
  const { scheduler, timers, tick } = setup((...flags) => {
    calls.push(flags);
    return new Promise(resolve => { finish = resolve; });
  });
  scheduler.request(true, false);
  const first = tick();
  scheduler.request(false, true);
  scheduler.request(true, false);
  assert.equal(timers.size, 0);
  assert.equal(calls.length, 1);
  finish();
  await first;
  assert.equal(timers.size, 1);
  const second = tick();
  assert.deepEqual(calls, [[true, false], [true, true]]);
  finish();
  await second;
  assert.equal(timers.size, 0);
});

test('unmount cancels queued work and prevents an in-flight request rescheduling', async () => {
  let finish;
  const queued = setup(async () => assert.fail('Disposed work ran'));
  queued.scheduler.request(true, true);
  queued.scheduler.dispose();
  await queued.tick();
  assert.equal(queued.timers.size, 0);
  const active = setup(() => new Promise(resolve => { finish = resolve; }));
  active.scheduler.request(true, true);
  const running = active.tick();
  active.scheduler.request(true, true);
  active.scheduler.dispose();
  finish();
  await running;
  assert.equal(active.timers.size, 0);
});
