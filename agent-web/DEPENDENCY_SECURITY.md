# Build dependency security

## 2026-10-06 remediation (totosha-qvs5)

- `tsx >=4.23.15` resolves to `esbuild 0.28.2`, fixing GHSA-g7r4-m6w7-qqqr.
- Override `postcss-selector-parser` to `7.1.6`, fixing GHSA-rj75-hqrm-r3gf.
  Tailwind 3 and postcss-nested compatibility is validated with the production build.
- There is no published fixed `braces` version (latest is 3.0.3).
  `scripts/patch-braces.cjs` runs on `npm install` / `npm ci` and caps AST
  nesting at 128 before recursive compile/expand/stringify. Both parentheses
  and braces are bounded, including unclosed and mixed nesting. This mitigates
  GHSA-vfj7-8cjw-p6xm while preserving ordinary glob behavior.

The patch is deliberately fail-closed on an unexpected package version/source,
searches nested installations, and is idempotent. Docker's dependency stage
copies the script before `npm ci`. Do not use `--ignore-scripts`: it bypasses
this mitigation. The dependency regression tests verify installed behavior.
The guard covers string parsing; direct caller-supplied ASTs are not a supported
untrusted input boundary and must not be passed to recursive braces APIs.

Full `npm audit` still reports 8 high-severity affected packages, all from the
single braces advisory: npm uses package version metadata and cannot recognize
our local mitigation. The warning is **not** suppressed and the version is not
falsified. `npm audit --omit=dev` reports 0 vulnerabilities. This is a temporary
mitigation, not a claim of a clean full audit or an upstream security fix.

When upstream publishes a fix, replace the patch with a patched version,
remove the postinstall hook and its Docker COPY if no longer needed, retain
regression coverage, and rerun `npm ci`, `npm test`, `npm run build`, full and
production audits. Do not downgrade Next/ESLint or use `audit fix --force` merely
to reduce warning counts.
