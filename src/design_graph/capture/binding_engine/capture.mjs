// AST evaluation traversal adapts origins; only native Variable/Reference resolves names.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const request=JSON.parse(fs.readFileSync(0,'utf8'));
const {parse,analyze}=await import(pathToFileURL(request.engine+'/engine-api.mjs').href);
const source=request.source;
const ast=parse(source,{sourceType:request.source_type,range:true,loc:true,filePath:request.syntax==='jsx'?'unit.jsx':'unit.js',jsx:request.syntax==='jsx'});
function checkDialect(node){
 if(node.type.startsWith('TS')||node.declare)throw Error('TypeScript syntax is outside JS/JSX capture');
 for(const child of children(node))checkDialect(child);
}
checkDialect(ast);
const manager=analyze(ast,{sourceType:request.source_type,lib:[],jsxPragma:null});
// One linear UTF16 -> UTF8 boundary map; interior surrogate offsets are invalid.
const offsets=new Map([[0,0]]);let u=0,b=0;
for(const ch of source){u+=ch.length;b+=Buffer.byteLength(ch,'utf8');offsets.set(u,b);}
const byte=x=>{if(!offsets.has(x))throw Error('noncanonical UTF16 offset');return offsets.get(x);};
const regions=[],environments=[],nodeRegions=new Map(),scopeEnvs=new Map(),functionInfo=new Map(),blockEnvs=new Map(),nameEnvs=new Map(),gaps=[],directEvalNodes=new Set(),functions=[];
const env=(kind,owner,outer,complete=true)=>{const e={id:'e'+environments.length,kind,owner:owner.id,outer,complete};environments.push(e);owner.environment=e.id;return e.id;};
const region=(slot,node,parent,environment=null,split_parameters=null,complete=true)=>{const r={id:'r'+regions.length,slot,parent:parent?.id??null,environment,start:byte(node.range[0]),end:byte(node.range[1]),split_parameters,complete};regions.push(r);return r;};
const root=region('root',ast,null); const rootEnv=env('root',root,null);
const contains=p=>!!p&&(p.type==='AssignmentPattern'||(p.type==='Property'&&p.computed)||children(p).some(contains));
function children(node){return Object.entries(node).flatMap(([k,v])=>['range','loc','parent','tokens','comments'].includes(k)?[]:Array.isArray(v)?v.filter(x=>x&&typeof x.type==='string'):v&&typeof v.type==='string'?[v]:[]);}
function walk(node,parent,current){
 if(!node)return;
 if(['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(node.type)){
  if(node.type==='FunctionExpression'&&node.id){
   const name=region('function-name',node,parent);current=env('block',name,current);nameEnvs.set(node,current);parent=name;
  }
  const split=node.params.some(contains),creation=region('function-creation',node,parent,null,split);
  functions.push({region:creation.id,kind:node.type==='ArrowFunctionExpression'?'arrow':'ordinary'});
  const params=region('function-parameters',node,creation);const pe=env(split?'parameters':'function-shared',params,current);
  const body=region('function-body',node.body,creation);const ve=split?env('function-var',body,pe):pe;
  const lexical=region('block',node.body,body);const le=env('block',lexical,ve);
  functionInfo.set(node,{pe,ve,le,split});
  nodeRegions.set(node,creation);
  for(const p of node.params)pattern(p,params,pe);
  if(node.body.type==='BlockStatement')for(const item of node.body.body)walk(item,lexical,le);
  else walk(node.body,lexical,le);
  return;
 }
 if(['ForStatement','ForInStatement','ForOfStatement'].includes(node.type)){
  const declaration=node.type==='ForStatement'?node.init:node.left;
  // One static lexical name inventory, NOT a concrete per-iteration cell.
  // The RHS of lexical for-in/of sees the loop name (possibly TDZ), too.
  // Sites come from AST evaluation phases, independently of native targets.
  const lexical=declaration?.type==='VariableDeclaration'&&declaration.kind!=='var';
  const loop=region(lexical?'block':'evaluation',node,parent);
  const e=lexical?env('block',loop,current):current;
  if(lexical)blockEnvs.set(node,e);
  const phases=node.type==='ForStatement'?[node.init,node.test,node.update,node.body]:[node.right,node.left,node.body];
  for(const phase of phases)if(phase){
   const site=region('evaluation',phase,loop);walk(phase,site,e);
  }
  return;
 }
 if(node.type==='SwitchStatement'){
  const sw=region('switch',node,parent),disc=region('switch-discriminant',node.discriminant,sw);
  walk(node.discriminant,disc,current);
  const cases=region('switch-case',node,sw),ce=env('case',cases,current);blockEnvs.set(node,ce);
  for(const c of node.cases)walk(c,cases,ce);return;
 }
 if(node.type==='BlockStatement'){
  const r=region('block',node,parent),e=env('block',r,current);blockEnvs.set(node,e);
  for(const child of node.body)walk(child,r,e);return;
 }
 if(node.type==='ClassDeclaration'||node.type==='ClassExpression'){
  const r=region('class',node,parent),e=env('block',r,current);blockEnvs.set(node,e);
  if(node.superClass)walk(node.superClass,r,e);
  for(const member of node.body.body)walk(member,r,e);return;
 }
 if(node.type==='WithStatement'){
  walk(node.object,parent,current);const r=region('evaluation',node.body,parent,null,null,false);
  gaps.push({region:r.id,kind:'dynamic-with'});blockEnvs.set(node,current);walk(node.body,r,current);return;
 }
 if(node.type==='CallExpression'&&!node.optional&&node.callee.type==='Identifier'&&node.callee.name==='eval')directEvalNodes.add(node.callee);
 nodeRegions.set(node,parent);
 for(const child of children(node))walk(child,parent,current);
}
function pattern(node,parent,current){
 nodeRegions.set(node,parent);
 if(node.type==='AssignmentPattern'){
  pattern(node.left,parent,current);const r=region('parameter-default',node.right,parent);walk(node.right,r,current);return;
 }
 if(node.type==='Property'){
  if(node.computed){const r=region('parameter-computed',node.key,parent);walk(node.key,r,current);}
  pattern(node.value,parent,current);return;
 }
 for(const child of children(node))pattern(child,parent,current);
}
// Inventory declaration positions, not scope kinds: Annex B also accepts case,
// if/else and labelled declarations. Ordinary Program/FunctionBody declarations
// are excluded. This is a conservative risk inventory, never a synthesized var.
const annexDeclarations=new Set();
function inventoryAnnex(node,parent=null,owner=null){
 if(node.type==='FunctionDeclaration'&&!node.async&&!node.generator){
  const ordinary=parent?.type==='Program'||(parent?.type==='BlockStatement'&&owner?.body===parent&&['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(owner.type));
  if(!ordinary)annexDeclarations.add(node);
 }
 for(const child of children(node))inventoryAnnex(child,node,parent);
}
inventoryAnnex(ast);
for(const n of ast.body)walk(n,root,rootEnv);
for(const s of manager.scopes){
 let e;
 if(s.type==='global'||s.type==='module')e=rootEnv;
 else if(s.type==='function'){const i=functionInfo.get(s.block);if(!i)throw Error('function mapping absent');e=s.designGraphRole==='body-variables'?i.ve:i.pe;}
 else if(s.type==='function-expression-name')e=nameEnvs.get(s.block);
 else e=blockEnvs.get(s.block);
 if(!e)throw Error('unsupported native scope '+s.type);
 scopeEnvs.set(s,e);
}
// Dynamic regions are localized to the affected lexical function/unit, not siblings.
const markGap=(r,kind)=>{r.complete=false;if(!gaps.some(g=>g.region===r.id&&g.kind===kind))gaps.push({region:r.id,kind});};
for(const s of manager.scopes){
 // A resolved lexical binding says nothing about whether its value is %eval%.
 // No value proof is available here, even for a locally declared function.
 if(!s.isStrict)for(const ref of s.references)if(directEvalNodes.has(ref.identifier)){
  let r=nodeRegions.get(ref.identifier);
  while(r.parent&&r.slot!=='function-creation')r=regions.find(x=>x.id===r.parent);
  markGap(r,'sloppy-direct-eval');
 }
 if(!s.isStrict&&request.source_type==='script')for(const v of s.variables)for(const d of v.defs){
  if(d.type!=='FunctionName'||!annexDeclarations.has(d.node))continue;
  // Start outside the declaration's own function; its enclosing unit/function
  // and closures may observe legacy bindings even after the block is exited.
  let r=regions.find(r=>r.id===nodeRegions.get(d.node).parent);
  while(r.parent&&r.slot!=='function-creation')r=regions.find(x=>x.id===r.parent);
  markGap(r,'annex-b');
 }
}
const occurrences=[],variables=[],nativeKeys=new Map(),intrinsics=[];
for(const s of manager.scopes)for(const v of s.variables){
 if(!v.isValueVariable)continue;
 let e=scopeEnvs.get(s);
 const defs=v.defs;
 if(s.type==='function'&&defs.length&&defs.every(d=>d.type==='ClassName'||(d.type==='Variable'&&['let','const'].includes(d.parent?.kind)))){e=functionInfo.get(s.block).le;}
 const key=[e,v.name];nativeKeys.set(v,key);
 const ids=[];
 for(const d of defs){
  let kind;
  if(d.type==='Variable')kind=d.parent.kind;
  else if(d.type==='Parameter')kind='parameter';
  else if(d.type==='FunctionName')kind=s.type==='function-expression-name'?'function-name':'function';
  else if(d.type==='ClassName')kind='class';
  else throw Error('unsupported definition '+d.type);
  const id='d'+occurrences.length;ids.push(id);
  occurrences.push({id,environment:e,name:v.name,namespace:'value',kind,start:byte(d.name.range[0]),end:byte(d.name.range[1])});
 }
 if(!defs.length){if(v.name!=='arguments'||s.type!=='function')throw Error('unsupported intrinsic');intrinsics.push({environment:e,kind:'arguments'});}
 variables.push({environment:e,name:v.name,occurrences:ids});
}
const references=[];
for(const s of manager.scopes)for(const ref of s.references){
 if(!ref.isValueReference)continue;
 const node=ref.identifier,r=nodeRegions.get(node);if(!r)throw Error('reference AST evaluation region absent');
 references.push({id:'ref'+references.length,region:r.id,name:node.name,namespace:'value',access:ref.isReadWrite()?'read-write':ref.isWrite()?'write':'read',start:byte(node.range[0]),end:byte(node.range[1]),target:ref.resolved?nativeKeys.get(ref.resolved):null});
}
process.stdout.write(JSON.stringify({regions,environments,occurrences,variables,references,intrinsics,gaps,functions}));
