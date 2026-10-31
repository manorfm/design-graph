// Same AST and native identity maps as lexical capture; no second resolver.
export function captureSourceSyntax(ast, children, byte, refs, declarations) {
 const uses=[],aliases=[],publications=[],unsupported=[];
 const span=n=>({start:byte(n.range[0]),end:byte(n.range[1])});
 const token=n=>({name:n.name,span:span(n)});
 const ref=n=>refs.get(n)??null;
 const path=n=>{
  const keys=[];let cursor=n;
  while(cursor?.type==='MemberExpression'&&!cursor.computed&&!cursor.optional&&cursor.property.type==='Identifier'){
   keys.unshift(token(cursor.property));cursor=cursor.object;
  }
  return cursor?.type==='Identifier'&&ref(cursor)!==null?{span:span(n),root_reference:ref(cursor),root:token(cursor),keys}:null;
 };
 const unsupportedFact=(n,kind)=>unsupported.push({id:'x'+unsupported.length,kind,span:span(n)});
 function visit(n){
  if(n.type==='VariableDeclarator'&&n.id.type==='Identifier'&&n.init){
   const p=path(n.init),d=declarations.get(n.id);
   if(p&&p.keys.length&&d)aliases.push({id:'a'+aliases.length,declaration:d.id,native_binding:d.target,declarator_span:span(n),initializer:p});
  }
  if(n.type==='MemberExpression'){
   if(n.computed||n.optional)unsupportedFact(n,'computed-or-optional-member');
   else if(n.object.type==='Identifier'&&n.property.type==='Identifier'&&ref(n.object)!==null)
    uses.push({id:'u'+uses.length,member_span:span(n),object_reference:ref(n.object),key:token(n.property)});
  }
  if(n.type==='AssignmentExpression'&&n.right.type==='ObjectExpression'){
   const p=path(n.left);
   if(n.operator==='='&&p&&p.keys.length){
    const members=n.right.properties.map((m,i)=>{
     const property=m.type==='Property';
     const supported=property&&!m.computed&&!m.method&&m.kind==='init'&&m.key.type==='Identifier'&&m.key.name!=='__proto__'&&m.value.type==='Identifier'&&ref(m.value)!==null;
     if(!supported)unsupportedFact(m,'unsupported-publication-member');
     return {id:'p'+publications.length+'m'+i,property_span:span(m),kind:property?m.kind:'spread',computed:property?m.computed:false,method:property?m.method:false,key:property&&!m.computed&&m.key.type==='Identifier'?token(m.key):null,value_reference:property&&m.value.type==='Identifier'?ref(m.value):null};
    });
    publications.push({id:'p'+publications.length,assignment_span:span(n),operator:n.operator,path:p,object_span:span(n.right),members});
   }else unsupportedFact(n,'unsupported-publication-path');
  }
  for(const c of children(n))visit(c);
 }
 visit(ast);
 return {version:'source-syntax/1',uses,aliases,publications,unsupported};
}
