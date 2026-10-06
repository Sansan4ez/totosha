import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
const require = createRequire(import.meta.url);
const braces = require('braces');

test('braces rejects deeply nested brace/parenthesis ASTs before recursion', () => {
  for (const [open, close] of [['{', '}'], ['(', ')']]) {
    for (const method of ['compile', 'expand', 'stringify', 'parse']) {
      for (const closed of [true, false]) {
        const input = open.repeat(4000) + 'a,b' + (closed ? close.repeat(4000) : '');
        assert.throws(() => braces[method](input), (error: unknown) =>
          error instanceof SyntaxError && error.message.includes('safe depth'));
      }
    }
  }
  assert.throws(() => braces.compile('{('.repeat(1000) + 'a,b'), SyntaxError);
});

test('braces mitigation preserves normal glob and literal behavior', () => {
  assert.deepEqual(braces.expand('src/{app,lib}/**/*.{ts,tsx}'), [
    'src/app/**/*.ts', 'src/app/**/*.tsx', 'src/lib/**/*.ts', 'src/lib/**/*.tsx',
  ]);
  assert.deepEqual(braces.expand('{1..3}'), ['1', '2', '3']);
  assert.deepEqual(braces.expand('{a,{b,c}}'), ['a', 'b', 'c']);
  assert.equal(braces.stringify(String.raw`\{literal\}`), '{literal}');
  assert.doesNotThrow(() => braces.compile('{'.repeat(32) + 'a,b' + '}'.repeat(32)));
  assert.doesNotThrow(() => execFileSync(process.execPath, ['scripts/patch-braces.cjs']));
});
