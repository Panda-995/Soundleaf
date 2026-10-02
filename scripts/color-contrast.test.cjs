const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parseLinearRgb, contrast } = require('./color-contrast.cjs');

test('OKLCH primary colors match sRGB reference vectors', () => {
  for (const [color, expected] of [
    ['oklch(0.6279553606 0.2576833077 29.2338851923)', [1, 0, 0]],
    ['oklch(0.8664396115 0.2948272403 142.4953388878)', [0, 1, 0]],
    ['oklch(0.4520137184 0.3132143717 264.0520206381)', [0, 0, 1]],
  ]) {
    const actual = parseLinearRgb(color);
    actual.forEach((value, i) => assert.ok(Math.abs(value - expected[i]) < 1e-6, color));
  }
});

test('black/white ratio and the body-text contrast boundary', () => {
  assert.equal(contrast('oklch(0 0 0)', 'oklch(1 0 0)'), 21);
  assert.ok(contrast('rgb(118, 118, 118)', 'rgb(255, 255, 255)') > 4.5);
  assert.ok(contrast('rgb(119, 119, 119)', 'rgb(255, 255, 255)') < 4.5);
  assert.equal(contrast('unparseable', 'rgb(255, 255, 255)'), null);
});
