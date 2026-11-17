import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './harness.mjs';

const core = (data) => load(['core.js'], data).run;

test('fmtN formats the same way for every viewer', () => {
  assert.equal(core()('fmtN(1234567)'), '1,234,567');
});

test('fmt abbreviates thousands and millions', () => {
  const run = core();
  assert.equal(run('fmt(999)'), '999');
  assert.equal(run('fmt(24154)'), '24K');
  assert.equal(run('fmt(1250000)'), '1.3M');
});

test('esc escapes every character that can break out of HTML text or an attribute', () => {
  const run = core();
  assert.equal(run(`esc('<img src=x onerror="alert(1)">&\\'')`), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;');
  assert.equal(run('esc(null) + esc(undefined) + esc(0)'), '0');
});

test('slugToDate reads YYYYMMDD as UTC midnight', () => {
  assert.equal(core()("slugToDate('20261021').toISOString()"), '2026-10-21T00:00:00.000Z');
});

test('deltaSub colours a rise red and a fall green, and names the gap', () => {
  const run = core();
  const up = run('deltaSub(110, 100, 42)');
  assert.match(up, /var\(--crit\)/);
  assert.match(up, /↑ 10 \(10\.0%\)/);
  assert.ok(up.endsWith(' vs 42d ago'));
  const down = run('deltaSub(90, 100, 35)');
  assert.match(down, /var\(--low\)/);
  assert.match(down, /↓ 10 \(10\.0%\)/);
  assert.match(run('deltaSub(5, 5, 30)'), /no change/);
  assert.match(run('deltaSub(120, 0, 30)'), />↑ 120<\/span>/);  // no percentage claimed from zero

});
