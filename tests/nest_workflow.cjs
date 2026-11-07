// Level 4: real NestJS/FastAPI HTTP using pinned Backend code and MOCKED data/store.
// No Prisma, database driver, external provider or production AppModule is loaded.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const cp=require('node:child_process'),crypto=require('node:crypto'),net=require('node:net');
const assert=require('node:assert/strict');
const option=(name)=>process.argv[process.argv.indexOf(name)+1];
const root=path.resolve(__dirname,'..'),reference=path.resolve(option('--backend-reference'));
const dependencies=path.resolve(option('--dependencies')),python=path.resolve(option('--python'));
process.env.NODE_PATH=path.join(dependencies,'node_modules');
require('node:module').Module._initPaths();
require('reflect-metadata');
const ts=require('typescript'),{Module,ValidationPipe}=require('@nestjs/common');
const {NestFactory,Reflector}=require('@nestjs/core'),{ConfigService}=require('@nestjs/config');
const {JwtService}=require('@nestjs/jwt');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'docs/verification/workflow-backend-sources.json'),'utf8'));
const compiled=fs.mkdtempSync(path.join(dependencies,'compiled-'));
for(const [file,sha] of Object.entries(manifest.files)){
  const source=fs.readFileSync(path.join(reference,file),'utf8').replace(/\r\n/g,'\n');
  assert.equal(crypto.createHash('sha1').update('blob '+Buffer.byteLength(source)+'\0'+source).digest('hex'),sha);
  const output=path.join(compiled,file.replace(/^src\//,'').replace(/\.ts$/,'.js'));
  fs.mkdirSync(path.dirname(output),{recursive:true});
  fs.writeFileSync(output,ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,
    module:ts.ModuleKind.CommonJS,experimentalDecorators:true,emitDecoratorMetadata:false}}).outputText);
}
const read=(file)=>require(path.join(compiled,file));
const {AiController}=read('ai/ai.controller'),{AiService}=read('ai/ai.service');
const {AiSecurity}=read('ai/ai-security'),{AiInternalGuard}=read('ai/ai-internal.guard');
const {UnavailableAiConversationStore}=read('ai/ai-conversation.store');
const {AiRespondDto,AiToolDto}=read('ai/ai.dto'),{AuthGuard}=read('auth/auth.guard');
const {productResponse}=read('products/product-presenter'),{createPagination}=read('common/pagination/pagination');
const {AppHttpException}=read('common/errors/app-http.exception');
const unavailableStore=new UnavailableAiConversationStore();
const paused=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
const freePort=()=>new Promise(resolve=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{
  const port=server.address().port;server.close(()=>resolve(port));});});
const env={...process.env,PYTHON_DOTENV_DISABLED:'1',PYTHONIOENCODING:'utf-8',GROQ_API_KEY:'',AI_PROVIDER:'rules'};
const fixtureResult=cp.spawnSync(python,['-X','utf8','-c',
  'import json;from tests.workflow_probe import product_fixture;print(json.dumps(product_fixture(),ensure_ascii=False))'],
  {cwd:root,env,encoding:'utf8',windowsHide:true});
assert.equal(fixtureResult.status,0,'Synthetic fixture export');
const fixtures=JSON.parse(fixtureResult.stdout),bid=fixtures[0].businessId;
const cid='00000002-0000-4000-8000-000000000001',conversation='00000003-0000-4000-8000-000000000011';
const ownerId=crypto.randomUUID(),sessionId=crypto.randomUUID();
const keys=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
const inbound=crypto.randomBytes(48).toString('base64url'),outbound=crypto.randomBytes(48).toString('base64url');
const state={unavailable:false,ownerActive:true,historyUnavailable:false,malformed:false};
const messages=[],saved=new Map(),callbacks=[],domainCalls=[];let sequence=0;
function sourceMessage(message,conversationId=conversation,customerId=cid){
  const value={businessId:bid,customerId,conversationId,messageId:crypto.randomUUID(),message,
    senderType:'CUSTOMER',messageType:'TEXT',createdAt:new Date(Date.UTC(2026,10,1)+1000*(++sequence)).toISOString()};
  messages.push(value);return value;
}
function row(m){return {id:m.messageId,conversationId:m.conversationId,senderType:m.senderType,
  messageType:m.messageType,content:m.message,createdAt:m.createdAt,externalMessageId:null};}
const store={
  async current(businessId,conversationId,messageId){
    if(state.unavailable)return unavailableStore.current();
    const m=messages.find(m=>m.businessId===businessId&&m.conversationId===conversationId&&m.messageId===messageId);
    if(!m||!state.ownerActive)throw new AppHttpException('UNAUTHORIZED',401,'Invalid synthetic source scope');
    return {...m};
  },
  async historyBefore(m,limit,offset){
    if(state.unavailable||state.historyUnavailable)return unavailableStore.historyBefore();
    const prior=messages.filter(v=>v.businessId===m.businessId&&v.customerId===m.customerId&&
      v.conversationId===m.conversationId&&v.createdAt<m.createdAt).sort((a,b)=>b.createdAt.localeCompare(a.createdAt)||b.messageId.localeCompare(a.messageId));
    return {businessId:m.businessId,customerId:m.customerId,conversationId:m.conversationId,
      beforeMessageId:m.messageId,beforeMessageCreatedAt:m.createdAt,
      snapshot:crypto.createHash('sha256').update(JSON.stringify(prior)).digest('hex'),
      order:'createdAt_desc_id_desc',complete:true,pagination:createPagination({limit,offset},prior.length),
      items:prior.slice(offset,offset+limit).map(row)};
  },
  async saveReply(m,result){
    if(state.unavailable)return unavailableStore.saveReply();
    if(!saved.has(m.messageId))saved.set(m.messageId,result);
    return saved.get(m.messageId);
  },
};
const money=(value)=>value===null?null:{toFixed:()=>value};
function present(product){return productResponse({...product,basePrice:money(product.basePrice),
  variants:product.variants.slice(0,20).map(v=>({...v,unitPrice:money(v.unitPrice)})),
  _count:{variants:product.variants.length}},product.isSellable);}
function parent(businessId,id){const p=fixtures.find(p=>p.businessId===businessId&&p.id===id);
  if(!p)throw new AppHttpException('PRODUCT_NOT_FOUND',404,'Product not found');return p;}
function logDomain(method,args){domainCalls.push({method,arguments:args});}
const products={
  async list(businessId,page){logDomain('ProductsService.list',{businessId,...page});
    const values=fixtures.filter(p=>p.businessId===businessId);
    return {pagination:createPagination(page,values.length),items:values.slice(page.offset,page.offset+page.limit).map(present)};},
  async get(businessId,productId){logDomain('ProductsService.get',{businessId,productId});return present(parent(businessId,productId));},
};
const variants={
  async list(businessId,productId,page){logDomain('VariantsService.list',{businessId,productId,...page});const p=parent(businessId,productId);
    return {pagination:createPagination(page,p.variants.length),items:p.variants.slice(page.offset,page.offset+page.limit)};},
  async get(businessId,productId,variantId){logDomain('VariantsService.get',{businessId,productId,variantId});
    const v=parent(businessId,productId).variants.find(v=>v.id===variantId);
    if(!v)throw new AppHttpException('VARIANT_NOT_FOUND',404,'Variant not found');
    return state.malformed?{...v,stockQuantity:'invalid'}:{...v};},
};
async function main(){
  const aiPort=await freePort(),config=new ConfigService({AI_INTEGRATION_ENABLED:'true',
    AI_BASE_URL:'http://127.0.0.1:'+aiPort,AI_SERVICE_TOKEN:outbound,BACKEND_SERVICE_TOKEN:inbound,
    AI_CONTEXT_PRIVATE_KEY:keys.privateKey.export({type:'pkcs8',format:'pem'}).toString()});
  const security=new AiSecurity(config),service=new AiService(security,store,products,variants,{});
  const originalTool=service.tool.bind(service);
  service.tool=async(claims,dto)=>{const event={tool:dto.tool,arguments:dto.arguments,messageId:claims.messageId,
    actualInternalGuardPassed:true,layer:4};callbacks.push(event);
    try{const value=await originalTool(claims,dto);event.httpStatus=200;return value;}
    catch(error){event.httpStatus=error.getStatus?.()??500;event.failureCategory=error.constructor.name;throw error;}};
  // Source decorators remain unchanged. Explicit test DI metadata avoids loading
  // real Prisma/domain modules merely for emitted constructor type metadata.
  Reflect.defineMetadata('design:paramtypes',[AiService],AiController);
  Reflect.defineMetadata('design:paramtypes',[AiSecurity],AiInternalGuard);
  Reflect.defineMetadata('design:paramtypes',[String,AiRespondDto],AiController.prototype,'respond');
  Reflect.defineMetadata('design:paramtypes',[Object,AiToolDto],AiController.prototype,'data');
  class WorkflowTestModule{}
  Module({controllers:[AiController],providers:[{provide:AiService,useValue:service},
    {provide:AiSecurity,useValue:security},{provide:AiInternalGuard,useValue:new AiInternalGuard(security)}]})(WorkflowTestModule);
  const app=await NestFactory.create(WorkflowTestModule,{logger:false});
  const ownerJwt=new JwtService({secret:crypto.randomBytes(32).toString('hex')});
  const prisma={user:{findUnique:async()=>({id:ownerId,authVersion:0})},
    authSession:{findUnique:async()=>({userId:ownerId,expiresAt:new Date(Date.now()+3600000),revokedAt:null})},
    businessMember:{findUnique:async({where})=>where.userId_businessId.businessId===bid?
      {role:'OWNER',isActive:state.ownerActive}:null}};
  app.useGlobalGuards(new AuthGuard(new Reflector(),ownerJwt,prisma));
  app.useGlobalPipes(new ValidationPipe({transform:true,whitelist:true,forbidNonWhitelisted:true}));
  await app.listen(0,'127.0.0.1');const backendUrl=await app.getUrl();
  const traceFile=path.join(compiled,'ai-traces.jsonl');let child;
  const ownerToken=ownerJwt.sign({sub:ownerId,sid:sessionId,ver:0},{expiresIn:300});
  const body=(m)=>JSON.stringify(Object.fromEntries(['businessId','customerId','conversationId','messageId','message'].map(k=>[k,m[k]])));
  async function tool(m,name,args={},token=security.issue(m,body(m)),credential=inbound){
    const response=await fetch(backendUrl+'/internal/ai/data',{method:'POST',headers:{'Content-Type':'application/json',
      Authorization:'Bearer '+credential,'X-AI-Context':token},body:JSON.stringify({tool:name,arguments:args})});
    return {status:response.status,body:await response.json()};}
  const checks=[],turns=[];
  try{
    child=cp.spawn(python,['-X','utf8','-m','tests.workflow_probe','--trace-file',traceFile],{cwd:root,windowsHide:true,
      env:{...env,APP_ENV:'local',AI_LOCAL_ENABLED:'true',AI_LOCAL_PROVIDER:'rules',AI_INTEGRATION_ENABLED:'true',
        AI_LOCAL_PORT:String(aiPort),BACKEND_BASE_URL:backendUrl,AI_SERVICE_TOKEN:outbound,BACKEND_SERVICE_TOKEN:inbound,
        BACKEND_CONTEXT_PUBLIC_KEY:keys.publicKey.export({type:'spki',format:'pem'}).toString()},stdio:'ignore'});
    let ready=false;for(let i=0;i<100;i++){if(child.exitCode!==null)break;
      try{ready=(await fetch('http://127.0.0.1:'+aiPort+'/ready')).status===200;}catch{}
      if(ready)break;await paused(100);}
    assert(ready,'Canonical AI loopback startup');
    stage='initial-direct-tool-probe';
    const probe=await tool(sourceMessage('synthetic probe'),'get_products');
    if(probe.status!==200)throw Object.assign(new Error('Direct probe'),{code:JSON.stringify(probe)});
    async function respond(message,label){stage=label;const m=sourceMessage(message),start=callbacks.length;
      const response=await fetch(backendUrl+'/businesses/'+bid+'/ai/respond',{method:'POST',
        headers:{'Content-Type':'application/json',Authorization:'Bearer '+ownerToken},
        body:JSON.stringify({conversationId:m.conversationId,messageId:m.messageId})});
      const result=await response.json();assert.equal(response.status,200,label);assert.equal(result.orderCandidate,null);
      assert(saved.has(m.messageId),'Actual AiService saveReply boundary invoked');
      const observed=fs.readFileSync(traceFile,'utf8').trim().split('\n').map(JSON.parse).find(t=>t.messageId===m.messageId);
      assert(observed?.finalGuardPassed,label+' final guard');
      turns.push({case:label,httpStatus:response.status,callbacks:callbacks.slice(start),execution:observed,
        replyPersistence:'mock adapter boundary only'});return {result,observed};}
    const journey=['عندكم تيشيرت أسود؟','طب مقاس L بكام؟','طب عايزة 10 قطع من مقاس L',
      'طب خلاص خليهم 3 قطع من الأبيض مقاس L بدل الأسود'];
    for(let i=0;i<journey.length;i++)await respond(journey[i],'required-turn-'+(i+1));
    const final=turns[3].execution;assert.equal(final.quantity,3);assert.equal(final.facts.length,1);
    assert.deepEqual(final.facts[0].options,{Color:'White',Size:'L'});
    assert.equal(final.facts[0].effectivePrice,'290.00');assert.equal(final.facts[0].recordedQuantity,3);
    assert.equal(turns[2].execution.response.requiresReview,true);assert.equal(final.response.requiresReview,false);
    await respond('متوفر منه كام قطعة؟','stock-followup');
    const compared=await respond('أنهي أرخص، الأسود L ولا الأبيض L؟','comparison');
    assert.deepEqual(compared.observed.facts.map(v=>v.effectivePrice).sort(),['275.00','290.00']);
    const missing=await respond('عندكم الأبيض مقاس M؟','missing-combination');assert.equal(missing.observed.facts.length,0);
    const linen=await respond('طب وريني القميص الكتان','different-product');assert.equal(linen.observed.facts[0].effectivePrice,'350.00');
    stage='direct-tool-checks';const m=sourceMessage('black tshirt size L price');
    for(const name of ['get_products','get_product_details','get_product_variants','get_variant_details']){
      const args=name==='get_products'?{}:{productId:fixtures[0].id};if(name==='get_variant_details')args.variantId=fixtures[0].variants[0].id;
      assert.equal((await tool(m,name,args)).status,200);}
    checks.push('all_four_read_only_tools_over_actual_NestJS_HTTP');
    assert.equal((await tool(m,'get_products',{},undefined,outbound)).status,401);
    assert.equal((await tool(m,'create_order')).status,400);
    assert.equal((await tool(m,'get_products',{businessId:crypto.randomUUID()})).status,400);
    assert.equal((await tool(m,'get_product_details',{productId:crypto.randomUUID()})).status,404);
    const signed=security.issue(m,body(m));
    assert.equal((await tool(m,'get_products',{},signed.slice(0,-5)+'abcde')).status,401);
    assert.equal((await tool(m,'get_products',{},security.issue({...m,customerId:crypto.randomUUID()},body(m)))).status,401);
    const originalNow=Date.now;let expired;try{Date.now=()=>originalNow()-61000;expired=security.issue(m,body(m));}finally{Date.now=originalNow;}
    assert.equal((await tool(m,'get_products',{},expired)).status,401);
    const tampered=await fetch('http://127.0.0.1:'+aiPort+'/v2/ai/respond',{method:'POST',headers:{
      'Content-Type':'application/json','X-Internal-Token':outbound,'X-AI-Context':signed},body:body(m)+' '});
    assert.equal(tampered.status,403);checks.push('credentials_scope_signature_expiry_body_and_tool_allowlist');
    const before=domainCalls.length;state.unavailable=true;
    assert.equal((await tool(m,'get_products')).status,503);assert.equal(domainCalls.length,before);
    state.unavailable=false;checks.push('actual_UnavailableAiConversationStore_blocks_Product_tools_before_domain_read');
    state.historyUnavailable=true;const absent=await respond('طب مقاس L بكام؟','history-unavailable');
    assert.equal(absent.observed.historyStatus,'unavailable');assert.equal(absent.observed.facts.length,0);state.historyUnavailable=false;
    state.malformed=true;const malformed=await respond('بكام التيشيرت الأسود مقاس L؟','malformed-variant');
    assert(malformed.observed.facts.every(v=>typeof v.recordedQuantity==='number'||v.recordedQuantity===null));state.malformed=false;
    assert(malformed.observed.facts.every(v=>v.source.tool!=='get_variant_details'));
    assert(!malformed.observed.typedEvidence.some(v=>v.model==='ProductVariant'));
    checks.push('unavailable_history_clarifies_and_malformed_variant_does_not_supply_facts');
    console.log(JSON.stringify({level:4,backendCommit:manifest.commit,realNestJsHTTP:true,realFastApiHTTP:true,
      actualBackendClasses:['AiController','AiService','AiSecurity','AiInternalGuard','AuthGuard','productResponse'],
      mockedDomainServices:true,mockedConversationStore:true,mockedOwnerSessionMembership:true,
      realPostgreSQL:false,realPersistence:false,liveGroq:false,checks,turns,
      domainMethods:[...new Set(domainCalls.map(c=>c.method))],productionAppModuleUsed:false},null,2));
  }finally{if(child&&child.exitCode===null){child.kill();await Promise.race([new Promise(r=>child.once('exit',r)),paused(3000)]);}
    await app.close();}
}
let stage='startup';
main().catch(error=>{console.error(JSON.stringify({failure:'Level-4 workflow',stage,
  category:error.name,code:error.code??null,actual:typeof error.actual==='number'?error.actual:undefined,
  expected:typeof error.expected==='number'?error.expected:undefined,
  callbacks,domainMethods:[...new Set(domainCalls.map(c=>c.method))],
  rawErrorsAndCredentialsSuppressed:true}));process.exitCode=1;});
