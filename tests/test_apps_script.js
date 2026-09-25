'use strict';
// Host-side interface model only; this does not certify Apps Script deployment.
const fs=require('fs'),vm=require('vm'),crypto=require('crypto'),assert=require('assert');
const path=require('path');const source=fs.readFileSync(path.join(__dirname,'../apps_script/Code.gs'),'utf8');
const UID='01ARZ3NDEKTSV4RRFFQ69G5FAV';const LID='01ARZ3NDEKTSV4RRFFQ69G5FAW';
function setup(config){
 const props=new Map(),files=[],triggers=[];let lostCreate=false;
 const c=config||{profile:'optional_ingress',tenant_id:UID,ledger_id:LID,audience:'test-ingress',staging_folder_id:'folder-1',workbook_id:'workbook-1',generation_id:'01ARZ3NDEKTSV4RRFFQ69G5FAX',sheet_ids:{Directory:101,'Active Pipeline':102,'Completed Archives':103,_Control:104,_Changes:105},gateway_key_id:'gateway-v1',gateway_key_hex:'22'.repeat(32),gateway_sender_key_id:'gateway',senders:{client:{key_hex:'11'.repeat(32),capabilities:['entity.create','entity.edit']},gateway:{key_hex:'33'.repeat(32),capabilities:['dirty_hint']}}};
 props.set('CRM_INGRESS_CONFIG',JSON.stringify(c));props.set('CRM_ADMISSION',JSON.stringify({starts:[],total_files:0,total_bytes:0,last_clock:0}));
 const buf=x=>Buffer.isBuffer(x)?x:Array.isArray(x)?Buffer.from(x.map(n=>(n+256)%256)):Buffer.from(String(x),'utf8');
 const signed=x=>Array.from(x,n=>n>127?n-256:n);
 function blob(x,type,name){const b=buf(x);return {getBytes:()=>signed(b),getDataAsString:()=>b.toString('utf8'),name,type};}
 const folder={createFile(b){const file={getId:()=>`file-${files.length+1}`,getBlob:()=>b,getSize:()=>b.getBytes().length};const id=`file-${files.length+1}`;file.getId=()=>id;files.push(file);if(lostCreate)throw Error('lost after creation');return file;},getFiles(){let n=0;return {hasNext:()=>n<files.length,next:()=>files[n++]};}};
 const context={console,Date,JSON,Math,Object,Array,Number,String,Set,Error,RegExp,
 Utilities:{newBlob:blob,getUuid:()=>crypto.randomUUID(),DigestAlgorithm:{SHA_256:'sha256'},computeDigest:(algorithm,x)=>signed(crypto.createHash('sha256').update(buf(x)).digest()),computeHmacSha256Signature:(x,key)=>signed(crypto.createHmac('sha256',buf(key)).update(buf(x)).digest())},
 PropertiesService:{getScriptProperties:()=>({getProperty:k=>props.get(k)||null,setProperty:(k,v)=>props.set(k,v)})},
 LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
 DriveApp:{getFolderById:id=>{assert.strictEqual(id,c.staging_folder_id);return folder;}},
 ContentService:{MimeType:{JSON:'application/json'},createTextOutput:text=>({text,setMimeType(mime){this.mime=mime;return this;}})},
 ScriptApp:{getProjectTriggers:()=>triggers,newTrigger(handler){let sid,kind;const b={forSpreadsheet(id){sid=id;return b;},onEdit(){kind='edit';return b;},onChange(){kind='change';return b;},create(){const id=`trigger-${triggers.length}`;const t={getHandlerFunction:()=>handler,getTriggerSourceId:()=>sid,getUniqueId:()=>id,kind};triggers.push(t);return t;}};return b;}}};
 vm.createContext(context);vm.runInContext(source,context,{timeout:1000});
 return {x:context,c,props,files,triggers,setLost(v){lostCreate=v;},post(env){return JSON.parse(context.doPost({postData:{contents:typeof env==='string'?env:JSON.stringify(env),type:'application/json'}}).text);}};
}
function packet(c){return {schema_version:'crm.command.v4',operation_id:'01ARZ3NDEKTSV4RRFFQ69G5FAY',tenant_id:c.tenant_id,ledger_id:c.ledger_id,authority_epoch:'1',template_version:'1',base:null,command_type:'entity.create',payload:{entity_id:'01ARZ3NDEKTSV4RRFFQ69G5FAZ',entity_kind:'person',display_name:'Synthetic patron',facet:{}}};}
function envelope(s,p){const now=new Date().toISOString();const e={protocol:'crm.ingress.v4',kind:'command',delivery_id:'01ARZ3NDEKTSV4RRFFQ69G5FB0',sender_key_id:'client',audience:s.c.audience,tenant_id:s.c.tenant_id,ledger_id:s.c.ledger_id,issued_at:now,expires_at:new Date(Date.parse(now)+300000).toISOString(),nonce:'ab'.repeat(32),payload:p||packet(s.c)};e.payload_digest=s.x.hash_(e.payload);e.mac=s.x.hmac_(s.c.senders.client.key_hex,e,'CRM3:transport:v1');return e;}
function resign(s,e){delete e.mac;e.payload_digest=s.x.hash_(e.payload);e.mac=s.x.hmac_(s.c.senders[e.sender_key_id].key_hex,e,'CRM3:transport:v1');return e;}
if(process.argv[2]==='--roundtrip'){
 const data=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));const s=setup(data.config);const response=s.post(data.envelope);
 process.stdout.write(JSON.stringify({response,recordedBody:s.files.length?s.files[0].getBlob().getDataAsString():null}));process.exit(0);
}
const tests=[];function test(name,fn){tests.push([name,fn]);}
test('valid signed command stages exact original envelope',()=>{const s=setup(),e=envelope(s),r=s.post(e);assert.strictEqual(r.state,'RECEIVED');assert.strictEqual(s.files.length,1);const body=JSON.parse(s.files[0].getBlob().getDataAsString());assert.deepStrictEqual(body.envelope,e);assert.strictEqual(body.custody.file_id,null);});
test('receipt authenticates final Drive ID',()=>{const s=setup(),r=s.post(envelope(s));const m=r.receipt_mac;delete r.receipt_mac;assert.strictEqual(m,s.x.hmac_(s.c.gateway_key_hex,r,'CRM4:ingress-receipt:v1'));assert.strictEqual(r.file_id,'file-1');});
test('duplicate keys reject before staging',()=>{const s=setup();const raw=JSON.stringify(envelope(s)).replace('"protocol":','"protocol":"crm.ingress.v4","protocol":');assert.strictEqual(s.post(raw).ok,false);assert.strictEqual(s.files.length,0);});
test('tampered payload rejects',()=>{const s=setup(),e=envelope(s);e.payload.payload.display_name='Changed';assert.strictEqual(s.post(e).state,'REJECTED');assert.strictEqual(s.files.length,0);});
test('wrong tenant rejects',()=>{const s=setup(),e=envelope(s);e.tenant_id='01ARZ3NDEKTSV4RRFFQ69G5FB1';assert.strictEqual(s.post(resign(s,e)).state,'REJECTED');});
test('expired envelope rejects',()=>{const s=setup(),e=envelope(s);e.issued_at=new Date(Date.now()-600000).toISOString();e.expires_at=new Date(Date.now()-300001).toISOString();assert.strictEqual(s.post(resign(s,e)).state,'REJECTED');});
test('unknown command properties reject',()=>{const s=setup(),e=envelope(s);e.payload.payload.role='admin';assert.strictEqual(s.post(resign(s,e)).state,'REJECTED');});
test('wrong schema version rejects',()=>{const s=setup(),e=envelope(s);e.payload.schema_version='crm.command.v5';assert.strictEqual(s.post(resign(s,e)).state,'REJECTED');});
test('formula-like signed literal does not reach Drive',()=>{const s=setup(),e=envelope(s);e.payload.payload.display_name='=IMAGE("https://invalid.example")';assert.strictEqual(s.post(resign(s,e)).state,'REJECTED');assert.strictEqual(s.files.length,0);});
test('lost creation response is UNKNOWN',()=>{const s=setup();s.setLost(true);const r=s.post(envelope(s));assert.strictEqual(r.state,'UNKNOWN');assert.strictEqual(r.ok,false);assert.strictEqual(s.files.length,1);});
test('shared staging admission limits bursts',()=>{const s=setup();s.post(envelope(s));s.post(envelope(s));assert.strictEqual(s.post(envelope(s)).state,'RETRYABLE_NOT_RECEIVED');assert.strictEqual(s.files.length,2);});
test('edit event never reads raw values',()=>{const s=setup();const event={source:{getId:()=>s.c.workbook_id},triggerUid:'trigger-1',range:{getSheet:()=>({getSheetId:()=>101}),getRow:()=>2,getColumn:()=>29,getNumRows:()=>1,getNumColumns:()=>1,getValue(){throw Error('RAW VALUE READ');},getValues(){throw Error('RAW VALUES READ');}},value:'SECRET_FORMULA',oldValue:'SECRET_OLD'};
 s.x.captureEdit(event);assert.strictEqual(s.files.length,1);const text=s.files[0].getBlob().getDataAsString();assert(!text.includes('SECRET'));const record=JSON.parse(text);assert.strictEqual(record.envelope.kind,'dirty_hint');assert(!('value' in record.envelope.payload));});
test('structural event emits only invalidation',()=>{const s=setup();s.x.captureChange({source:{getId:()=>s.c.workbook_id},triggerUid:'t'});const r=JSON.parse(s.files[0].getBlob().getDataAsString());assert.strictEqual(r.envelope.payload.change_class,'STRUCTURE');});
test('trigger provisioning is idempotent',()=>{const s=setup();s.x.provisionIngress();s.x.provisionIngress();assert.strictEqual(s.triggers.length,2);});
test('health exposes no keys or tenant identity',()=>{const s=setup();const text=s.x.doGet().text;assert(!text.includes(s.c.tenant_id));assert(!text.includes(s.c.gateway_key_hex));});
test('JCS uses UTF16 ordering',()=>{const s=setup();assert.strictEqual(s.x.jcs_({'\ue000':2,'😀':1}),'{"😀":1,"\ue000":2}');});
test('invalid surrogate rejects',()=>{const s=setup();assert.throws(()=>s.x.strictJSON_('{"x":"\\ud800"}',100));});
test('float and unsafe integers reject',()=>{const s=setup();for(const raw of ['{"x":1.2}','{"x":9007199254740992}','{"x":-0}'])assert.throws(()=>s.x.strictJSON_(raw,100));});
test('prototype-shaped key remains ordinary data',()=>{const s=setup();const o=s.x.strictJSON_('{"__proto__":{"polluted":true}}',100);assert.strictEqual(Object.getPrototypeOf(o),null);assert.strictEqual({}.polluted,undefined);});
test('oversized body rejected',()=>{const s=setup();assert.strictEqual(s.post(' '.repeat(98305)).state,'REJECTED');});
const results=[];for(const [name,fn] of tests){try{fn();results.push({name,status:'PASS'});}catch(e){results.push({name,status:'FAIL',error:String(e)});}}
const output={runtime:process.version,profile:'Node interface mocks; no deployed Google runtime',tests:results,passed:results.filter(r=>r.status==='PASS').length,failed:results.filter(r=>r.status==='FAIL').length};
process.stdout.write(JSON.stringify(output,null,2)+'\n');process.exit(output.failed?1:0);
