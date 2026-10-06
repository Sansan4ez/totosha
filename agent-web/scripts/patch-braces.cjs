// Temporary mitigation for GHSA-vfj7-8cjw-p6xm until braces publishes a fix.
// Bound AST depth before compile/expand/stringify can recurse. Fail closed if
// the reviewed source changes; do not relabel the package to silence npm audit.
const fs = require('node:fs');
const path = require('node:path');
const marker = '// LocalTopSH: bound recursive AST depth (GHSA-vfj7-8cjw-p6xm)';
const guard = `      ${marker}\n      if (stack.length >= 128) {\n        throw new SyntaxError('braces nesting exceeds safe depth (128)');\n      }\n`;
let patched = 0;
function visit(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const root = path.join(dir, entry.name);
    if (entry.name.startsWith('@')) { visit(root); continue; }
    if (entry.name === 'braces') {
      const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
      if (pkg.version !== '3.0.3') throw new Error(`Review braces patch for ${pkg.version}`);
      const file = path.join(root, 'lib/parse.js');
      let source = fs.readFileSync(file, 'utf8');
      if (!source.includes(marker)) {
        for (const token of ['CHAR_LEFT_PARENTHESES', 'CHAR_LEFT_CURLY_BRACE']) {
          const needle = `    if (value === ${token}) {\n`;
          if (source.split(needle).length !== 2) throw new Error(`Unexpected braces source: ${token}`);
          source = source.replace(needle, needle + guard);
        }
        fs.writeFileSync(file, source);
      }
      if (source.split(marker).length !== 3) throw new Error('Incomplete braces depth patch');
      patched++;
    }
    visit(path.join(root, 'node_modules'));
  }
}
visit(path.join(__dirname, '..', 'node_modules'));
if (!patched) throw new Error('No braces installation found; review/remove temporary patch');
console.log(`Applied/verified braces depth mitigation in ${patched} installation(s)`);
