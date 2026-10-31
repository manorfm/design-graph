// Native producer API only: AST/ScopeManager are NOT an IR or a proof receipt.
export {parse} from '@typescript-eslint/typescript-estree';
export {analyze} from './corrected-scope-manager/dist/index.js';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
const digest=path=>createHash('sha256').update(fs.readFileSync(new URL(path,import.meta.url))).digest('hex');
export const engineIdentity=Object.freeze({
  parser:'@typescript-eslint/typescript-estree', parserVersion:'8.72.1',
  scopeManager:'@typescript-eslint/scope-manager', scopeManagerVersion:'8.72.1',
  patchVersion:'design-graph-fdi-2',
  patchSHA256:digest('engine-final.patch'),
  lockSHA256:digest('package-lock.json'),
  semantics:'native-scope-candidates-not-certified-ir'
});
