/** Sovereign CRM optional ingress, 0.5.0rc1.
 * NO canonical Sheet writes. NO values/formulas in edit hints. No browser loop.
 * Configuration and secrets live in Script Properties, never this source.
 * Production profile requires the deployment acceptance tests in README.
 */
'use strict';

function fail_(code) { const e = new Error(code); e.code = code; throw e; }
function utf8_(s) { return Utilities.newBlob(s, 'application/octet-stream').getBytes(); }
function hex_(bytes) { return bytes.map(x => ((x + 256) % 256).toString(16).padStart(2, '0')).join(''); }
function unhex_(s) {
  if (!/^[a-f0-9]{64,128}$/.test(s) || s.length % 2) fail_('KEY_FORMAT');
  const out=[]; for(let i=0;i<s.length;i+=2){const n=parseInt(s.slice(i,i+2),16);out.push(n>127?n-256:n);}return out;
}
function unicode_(s) {
  for(let i=0;i<s.length;i++) {
    const x=s.charCodeAt(i);
    if(x>=0xD800 && x<=0xDBFF) {const y=s.charCodeAt(++i);if(!(y>=0xDC00&&y<=0xDFFF))fail_('UNICODE');}
    else if(x>=0xDC00&&x<=0xDFFF)fail_('UNICODE');
  }
}
function strictJSON_(input, maxBytes) {
  if(typeof input!=='string' || utf8_(input).length>maxBytes || input.charCodeAt(0)===0xFEFF)fail_('BODY_LIMIT');
  let at=0;
  function ws(){while(/[ \n\r\t]/.test(input[at]||'x'))at++;}
  function str(){
    const start=at++;let escaped=false;
    while(at<input.length){const ch=input[at++];if(ch==='"'&&!escaped){let s;try{s=JSON.parse(input.slice(start,at));}catch(_){fail_('JSON');}unicode_(s);return s;}
      if(ch==='\\'&&!escaped)escaped=true;else escaped=false;}
    fail_('JSON');
  }
  function value(depth){
    if(depth>32)fail_('DEPTH');ws();const ch=input[at];
    if(ch==='"')return str();
    if(ch==='{'){
      at++;ws();const o=Object.create(null);let count=0;if(input[at]==='}'){at++;return o;}
      while(true){ws();if(input[at]!=='"')fail_('JSON');const key=str();if(Object.prototype.hasOwnProperty.call(o,key))fail_('DUPLICATE_KEY');
        ws();if(input[at++]!==':')fail_('JSON');o[key]=value(depth+1);if(++count>10000)fail_('OBJECT_LIMIT');ws();const sep=input[at++];if(sep==='}')return o;if(sep!==',')fail_('JSON');}
    }
    if(ch==='['){at++;ws();const a=[];if(input[at]===']'){at++;return a;}while(true){a.push(value(depth+1));if(a.length>10000)fail_('ARRAY_LIMIT');ws();const sep=input[at++];if(sep===']')return a;if(sep!==',')fail_('JSON');}}
    for(const pair of [['true',true],['false',false],['null',null]]){if(input.slice(at,at+pair[0].length)===pair[0]){at+=pair[0].length;return pair[1];}}
    const m=/^-?(?:0|[1-9][0-9]*)/.exec(input.slice(at));
    if(!m)fail_('JSON');at+=m[0].length;const n=Number(m[0]);if(!Number.isSafeInteger(n)||Object.is(n,-0))fail_('NUMBER_PROFILE');return n;
  }
  const result=value(0);ws();if(at!==input.length)fail_('JSON_TRAILING');return result;
}
function jcs_(x) {
  if(x===null)return 'null';
  if(typeof x==='boolean')return x?'true':'false';
  if(typeof x==='number'){if(!Number.isSafeInteger(x)||Object.is(x,-0))fail_('NUMBER_PROFILE');return JSON.stringify(x);}
  if(typeof x==='string'){unicode_(x);return JSON.stringify(x);}
  if(Array.isArray(x))return '['+x.map(jcs_).join(',')+']';
  if(typeof x==='object')return '{'+Object.keys(x).sort().map(k=>jcs_(k)+':'+jcs_(x[k])).join(',')+'}';
  fail_('JSON_TYPE');
}
function hash_(value) {return hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,utf8_(jcs_(value))));}
function rawHash_(bytes) {return hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,bytes));}
function hmac_(key,obj,domain){return hex_(Utilities.computeHmacSha256Signature(utf8_(domain+'\n'+jcs_(obj)),unhex_(key)));}
function equal_(a,b){if(typeof a!=='string'||typeof b!=='string'||a.length!==64||b.length!==64)return false;let d=0;for(let i=0;i<64;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0;}
function without_(obj,key){const out=Object.create(null);for(const k of Object.keys(obj))if(k!==key)out[k]=obj[k];return out;}
function config_(){
  const raw=PropertiesService.getScriptProperties().getProperty('CRM_INGRESS_CONFIG');
  if(!raw)fail_('NOT_PROVISIONED');const c=strictJSON_(raw,8192);
  if(c.profile!=='optional_ingress'||!c.senders||!c.gateway_key_hex||!c.staging_folder_id||!c.sheet_ids)fail_('CONFIG');
  if(Object.keys(c.senders).length>32)fail_('SENDER_LIMIT');
  unhex_(c.gateway_key_hex);return c;
}
function utc_(s){if(typeof s!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(s)||!Number.isFinite(Date.parse(s))||new Date(s).toISOString()!==s)fail_('TIMESTAMP');return Date.parse(s);}
function matches_(schema,x){
  if(schema.$ref){if(schema.$ref!=='ingest_command_v4.schema.json')return false;return matches_(CRM_COMMAND_SCHEMA_,x);}
  if(schema.const!==undefined && jcs_(x)!==jcs_(schema.const))return false;
  if(schema.enum&&!schema.enum.some(v=>jcs_(v)===jcs_(x)))return false;
  if(schema.type){const ts=Array.isArray(schema.type)?schema.type:[schema.type];const t=x===null?'null':Array.isArray(x)?'array':typeof x;
    if(!ts.some(v=>v===t||(v==='integer'&&typeof x==='number'&&Number.isSafeInteger(x))))return false;}
  if(schema.anyOf&&!schema.anyOf.some(s=>matches_(s,x)))return false;
  if(schema.oneOf&&schema.oneOf.filter(s=>matches_(s,x)).length!==1)return false;
  if(schema.allOf&&!schema.allOf.every(s=>matches_(s,x)))return false;
  if(schema.if&&matches_(schema.if,x)&&schema.then&&!matches_(schema.then,x))return false;
  if(schema.if&&!matches_(schema.if,x)&&schema.else&&!matches_(schema.else,x))return false;
  if(typeof x==='string'){
    if(schema.pattern){const m=(new RegExp(schema.pattern)).exec(x);if(!m)return false;if(schema.pattern.startsWith('^')&&schema.pattern.endsWith('$')&&m[0].length!==x.length)return false;}
    if(schema.maxLength!==undefined&&Array.from(x).length>schema.maxLength)return false;
    if(schema.minLength!==undefined&&Array.from(x).length<schema.minLength)return false;
  }
  if(typeof x==='number'){
    if(schema.minimum!==undefined&&x<schema.minimum)return false;
    if(schema.maximum!==undefined&&x>schema.maximum)return false;
  }
  if(x&&typeof x==='object'&&!Array.isArray(x)){
    const props=schema.properties||{};if(schema.required&&!schema.required.every(k=>Object.prototype.hasOwnProperty.call(x,k)))return false;
    if(schema.additionalProperties===false&&Object.keys(x).some(k=>!Object.prototype.hasOwnProperty.call(props,k)))return false;
    if(schema.minProperties!==undefined&&Object.keys(x).length<schema.minProperties)return false;
    for(const k of Object.keys(props))if(Object.prototype.hasOwnProperty.call(x,k)&&!matches_(props[k],x[k]))return false;
  }
  if(Array.isArray(x)){
    if(schema.maxItems!==undefined&&x.length>schema.maxItems)return false;
    if(schema.items&&!x.every(v=>matches_(schema.items,v)))return false;
  }
  return true;
}
function validateLiteralFields_(obj){
  const textFields=new Set(['display_name','note','next_action','summary','approved_excerpt','subject','objective']);
  function visit(x,depth){if(depth>32)fail_('DEPTH');if(!x||typeof x!=='object')return;
    for(const key of Object.keys(x)){const v=x[key];if(typeof v==='string'){
      if(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u202A-\u202E\u2066-\u2069]/.test(v))fail_('CONTROL_TEXT');
      if(textFields.has(key)&&/^\s*[=@+\-]/.test(v))fail_('FORMULA_LIKE_COMMAND');
      if(utf8_(v).length>4096)fail_('TEXT_LIMIT');
    }else if(v&&typeof v==='object')visit(v,depth+1);}
  }visit(obj,0);
}
function validateEnvelope_(env,c,admissionTime){
  if(!matches_(CRM_ENVELOPE_SCHEMA_,env))fail_('ENVELOPE_SCHEMA');
  if(env.tenant_id!==c.tenant_id||env.ledger_id!==c.ledger_id||env.audience!==c.audience)fail_('AUDIENCE');
  const sender=c.senders[env.sender_key_id];if(!sender)fail_('AUTH');
  if(!equal_(env.mac,hmac_(sender.key_hex,without_(env,'mac'),'CRM3:transport:v1')))fail_('AUTH');
  const issued=utc_(env.issued_at),expiry=utc_(env.expires_at);
  if(expiry<issued||expiry-issued>300000||issued>admissionTime+60000||expiry<admissionTime-60000)fail_('EXPIRED');
  if(!equal_(env.payload_digest,hash_(env.payload)))fail_('PAYLOAD_DIGEST');
  if(env.kind==='command'){
    if(!matches_(CRM_COMMAND_SCHEMA_,env.payload))fail_('COMMAND_SCHEMA');
    if(env.payload.tenant_id!==c.tenant_id||env.payload.ledger_id!==c.ledger_id)fail_('TENANT');
    const capability=CRM_CAPABILITIES_[env.payload.command_type];
    if(!capability||!sender.capabilities.includes(capability))fail_('CAPABILITY');
    validateLiteralFields_(env.payload);
  }else{
    if(!sender.capabilities.includes('dirty_hint'))fail_('CAPABILITY');
    const p=env.payload;
    const allowed=['workbook_id','sheet_id','generation_id','start_row','end_row_exclusive','start_column','end_column_exclusive','change_class','captured_at','trigger_id'];
    if(Object.keys(p).some(k=>!allowed.includes(k))||allowed.some(k=>!Object.prototype.hasOwnProperty.call(p,k)))fail_('HINT_SCHEMA');
    if(p.workbook_id!==c.workbook_id||p.generation_id!==c.generation_id||!Object.values(c.sheet_ids).includes(p.sheet_id))fail_('HINT_PIN');
    for(const k of ['start_row','end_row_exclusive','start_column','end_column_exclusive'])if(!Number.isSafeInteger(p[k])||p[k]<0)fail_('HINT_RANGE');
    if(p.end_row_exclusive<p.start_row||p.end_column_exclusive<p.start_column)fail_('HINT_RANGE');
    if(!['EDIT','STRUCTURE','WHOLE_SHEET'].includes(p.change_class))fail_('HINT_CLASS');utc_(p.captured_at);
    if(p.trigger_id!==null&&(typeof p.trigger_id!=='string'||p.trigger_id.length>256))fail_('TRIGGER_ID');
  }
  return sender;
}
function reserve_(bytes,now,c){
  const lock=LockService.getScriptLock();if(!lock.tryLock(500))fail_('RETRYABLE_NOT_RECEIVED');
  try{
    const props=PropertiesService.getScriptProperties();const raw=props.getProperty('CRM_ADMISSION');if(!raw)fail_('NOT_PROVISIONED');
    const s=strictJSON_(raw,16384);
    if(now<s.last_clock)fail_('CLOCK_HOLD');
    s.starts=s.starts.filter(t=>t>now-60000);
    if(s.starts.length>=10||s.starts.filter(t=>t>now-1000).length>=2)fail_('RETRYABLE_NOT_RECEIVED');
    if(s.total_files>=10000||s.total_bytes+bytes>268435456)fail_('STAGING_CAPACITY_HOLD');
    s.starts.push(now);s.total_files++;s.total_bytes+=bytes;s.last_clock=now;
    props.setProperty('CRM_ADMISSION',jcs_(s));
  }finally{lock.releaseLock();}
}
function receipt_(c,env,state,fileId,receivedAt,error){
  const r={protocol:'crm.ingress.v4',ok:state==='RECEIVED',state:state,delivery_id:env.delivery_id,
    operation_id:env.kind==='command'?env.payload.operation_id:null,file_id:fileId,
    payload_digest:env.payload_digest,received_at:receivedAt,error_code:error};
  r.receipt_mac=hmac_(c.gateway_key_hex,r,'CRM4:ingress-receipt:v1');return r;
}
function stage_(env,c){
  const now=Date.now();validateEnvelope_(env,c,now);
  const received=new Date(now).toISOString();
  const custody={protocol:'crm.custody.v1',gateway_key_id:c.gateway_key_id,tenant_id:c.tenant_id,ledger_id:c.ledger_id,
    delivery_id:env.delivery_id,sender_key_id:env.sender_key_id,envelope_digest:hash_(env),payload_digest:env.payload_digest,
    received_at:received,file_id:null};
  custody.mac=hmac_(c.gateway_key_hex,custody,'CRM5:custody:v1');
  const bytes=jcs_({envelope:env,custody:custody});reserve_(utf8_(bytes).length,now,c);
  // Once creation starts, any inconclusive error means UNKNOWN, not failed intake.
  try{
    const file=DriveApp.getFolderById(c.staging_folder_id).createFile(Utilities.newBlob(bytes,'application/json',env.delivery_id+'.crm-ingress.json'));
    const content=file.getBlob().getBytes();
    if(rawHash_(content)!==rawHash_(utf8_(bytes)))return receipt_(c,env,'UNKNOWN',null,received,'READBACK_MISMATCH');
    return receipt_(c,env,'RECEIVED',file.getId(),received,null);
  }catch(_){return receipt_(c,env,'UNKNOWN',null,received,'DRIVE_CREATE_OR_READBACK');}
}
function output_(obj){return ContentService.createTextOutput(jcs_(obj)).setMimeType(ContentService.MimeType.JSON);}
function doPost(e){
  let c=null,env=null,authenticated=false;
  try{
    if(!e||!e.postData||typeof e.postData.contents!=='string')fail_('BODY');
    c=config_();env=strictJSON_(e.postData.contents,98304);validateEnvelope_(env,c,Date.now());authenticated=true;
    return output_(stage_(env,c));
  }catch(err){
    if(authenticated){const code=err.code||'INGRESS_FAILURE';const state=code==='RETRYABLE_NOT_RECEIVED'?'RETRYABLE_NOT_RECEIVED':'REJECTED';return output_(receipt_(c,env,state,null,new Date().toISOString(),code));}
    // No prior operation IDs, payload echo, configuration or key hints.
    return output_({protocol:'crm.ingress.v4',ok:false,state:'REJECTED',error_code:'REJECTED'});
  }
}
function doGet(){return output_({protocol:'crm.ingress.v4',role:'optional_ingress_only',runtime:'0.5.0rc1'});}
function randomHex_(){return rawHash_(utf8_(Utilities.getUuid()+Utilities.getUuid()+Utilities.getUuid()));}
function deliveryId_(){
  const alphabet='0123456789ABCDEFGHJKMNPQRSTVWXYZ';let millis=Date.now(),time='';
  for(let i=0;i<10;i++){time=alphabet[millis%32]+time;millis=Math.floor(millis/32);}
  const bytes=unhex_(randomHex_());let suffix='';for(let i=0;i<16;i++)suffix+=alphabet[(bytes[i]+256)%32];return time+suffix;
}
function hint_(e,structural){
  const c=config_();if(!e||!e.source||e.source.getId()!==c.workbook_id)fail_('HINT_SOURCE');
  const now=new Date().toISOString();let sheet,startRow=0,endRow=0,startCol=0,endCol=0;
  if(!structural){if(!e.range)fail_('HINT_RANGE');sheet=e.range.getSheet().getSheetId();startRow=e.range.getRow()-1;startCol=e.range.getColumn()-1;endRow=startRow+e.range.getNumRows();endCol=startCol+e.range.getNumColumns();}
  else{sheet=c.sheet_ids.Directory;}
  const huge=(endRow-startRow)*(endCol-startCol)>10000;
  const payload={workbook_id:c.workbook_id,sheet_id:sheet,generation_id:c.generation_id,
    start_row:huge?0:startRow,end_row_exclusive:huge?0:endRow,start_column:huge?0:startCol,end_column_exclusive:huge?0:endCol,
    change_class:structural?'STRUCTURE':huge?'WHOLE_SHEET':'EDIT',captured_at:now,trigger_id:e.triggerUid?String(e.triggerUid):null};
  const env={protocol:'crm.ingress.v4',kind:'dirty_hint',delivery_id:deliveryId_(),sender_key_id:c.gateway_sender_key_id,
    audience:c.audience,tenant_id:c.tenant_id,ledger_id:c.ledger_id,issued_at:now,expires_at:new Date(Date.parse(now)+300000).toISOString(),nonce:randomHex_(),payload:payload,payload_digest:hash_(payload)};
  const sender=c.senders[c.gateway_sender_key_id];if(!sender)fail_('GATEWAY_SENDER_CONFIG');
  env.mac=hmac_(sender.key_hex,env,'CRM3:transport:v1');return stage_(env,c);
}
function captureEdit(e){return hint_(e,false);} // installed .onEdit(), NOT a simple trigger
function captureChange(e){return hint_(e,true);}
function provisionIngress(){
  const c=config_();const props=PropertiesService.getScriptProperties();
  if(!props.getProperty('CRM_ADMISSION')){
    const files=DriveApp.getFolderById(c.staging_folder_id).getFiles();let count=0,bytes=0;
    while(files.hasNext()){const f=files.next();count++;bytes+=f.getSize();if(count>10000||bytes>268435456)fail_('STAGING_CAPACITY_HOLD');}
    props.setProperty('CRM_ADMISSION',jcs_({starts:[],total_files:count,total_bytes:bytes,last_clock:Date.now()}));
  }
  const existing=ScriptApp.getProjectTriggers();const result=[];
  for(const handler of ['captureEdit','captureChange']){
    const same=existing.filter(t=>t.getHandlerFunction()===handler&&t.getTriggerSourceId()===c.workbook_id);
    if(same.length>1)fail_('DUPLICATE_INSTALLED_TRIGGER');
    let trigger=same[0];if(!trigger){const builder=ScriptApp.newTrigger(handler).forSpreadsheet(c.workbook_id);trigger=(handler==='captureEdit'?builder.onEdit():builder.onChange()).create();}
    result.push({handler:handler,trigger_id:trigger.getUniqueId()});
  }
  return {profile:'optional_ingress',triggers:result};
}

// Frozen machine schemas, generated from retained release files.
const CRM_COMMAND_SCHEMA_ = {"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"urn:sovereign:crm:command:5","type":"object","properties":{"schema_version":{"enum":["crm.command.v4","crm.command.v5"]},"operation_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"tenant_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"ledger_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"authority_epoch":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"template_version":{"const":"1"},"base":{"anyOf":[{"type":"object","properties":{"commit_seq":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"transaction_digest":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"required":["commit_seq","transaction_digest"],"additionalProperties":false},{"type":"null"}]},"command_type":{"enum":["entity.create","entity.patch","entity.transition","entity.tombstone","campaign.membership.set","patron.channel.set","patron.primary_channel.set","entity.alias.set","artifact.register","interaction.append","interaction.supersede","dispatch.chunk.append","claim.acquire","claim.release","claim.recover","observation.resolve","project.plan.select","commercial.terms.set","entity.merge","entity.tag.set"]},"payload":{"type":"object"}},"required":["schema_version","operation_id","tenant_id","ledger_id","authority_epoch","template_version","base","command_type","payload"],"additionalProperties":false,"allOf":[{"if":{"properties":{"command_type":{"const":"entity.create"}},"required":["command_type"]},"then":{"properties":{"payload":{"oneOf":[{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"person"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"organization_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"patron_type":{"anyOf":[{"enum":["angel","institutional","individual","business","other"]},{"type":"null"}]},"funding_band":{"type":["string","null"],"maxLength":2048},"funding_currency":{"anyOf":[{"type":"string","pattern":"^[A-Z]{3}$"},{"type":"null"}]}},"required":[],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"organization"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"patron_type":{"anyOf":[{"enum":["angel","institutional","individual","business","other"]},{"type":"null"}]},"funding_band":{"type":["string","null"],"maxLength":2048},"funding_currency":{"anyOf":[{"type":"string","pattern":"^[A-Z]{3}$"},{"type":"null"}]}},"required":[],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"campaign"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"slug":{"type":"string","maxLength":1024},"objective":{"type":["string","null"],"maxLength":2048},"lead_actor_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]}},"required":["slug"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"project"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"slug":{"type":"string","maxLength":1024},"lead_actor_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"lead_model":{"type":["string","null"],"maxLength":2048},"dropzone_drive_id":{"type":["string","null"],"maxLength":2048}},"required":["slug"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"stage"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"project_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"plan_version":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"stage_ordinal":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"required":{"type":"boolean"},"assigned_actor_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"acceptance_ref":{"type":["string","null"],"maxLength":2048},"due_at":{"anyOf":[{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},{"type":"null"}]}},"required":["project_id","plan_version","stage_ordinal","required"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"ticket"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"project_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"plan_version":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"parent_work_item_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"assigned_actor_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"acceptance_ref":{"type":["string","null"],"maxLength":2048},"due_at":{"anyOf":[{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},{"type":"null"}]}},"required":["project_id","plan_version"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"opportunity"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"project_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"primary_patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"amount_minor":{"anyOf":[{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},{"type":"null"}]},"currency":{"anyOf":[{"type":"string","pattern":"^[A-Z]{3}$"},{"type":"null"}]},"due_at":{"anyOf":[{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},{"type":"null"}]}},"required":["project_id","primary_patron_id"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"contract"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"project_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"primary_patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"origin_opportunity_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"amount_minor":{"anyOf":[{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},{"type":"null"}]},"currency":{"anyOf":[{"type":"string","pattern":"^[A-Z]{3}$"},{"type":"null"}]},"due_at":{"anyOf":[{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},{"type":"null"}]}},"required":["project_id","primary_patron_id"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"thread"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"target_app":{"type":"string","maxLength":1024},"connector_account_id":{"type":"string","maxLength":1024},"external_thread_id":{"type":"string","maxLength":1024}},"required":["target_app","connector_account_id","external_thread_id"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false},{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_kind":{"const":"dispatch"},"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048},"facet":{"type":"object","properties":{"work_item_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"thread_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"actor_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"attempt_no":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"prompt_hash":{"type":"string","pattern":"^[0-9a-f]{64}$"},"target_app":{"type":"string","maxLength":1024},"connector_account_id":{"type":"string","maxLength":1024}},"required":["work_item_id","actor_id","attempt_no","prompt_hash","target_app","connector_account_id"],"additionalProperties":false}},"required":["entity_id","entity_kind","display_name","facet"],"additionalProperties":false}]},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.patch"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"changes":{"type":"object","properties":{"display_name":{"type":"string","maxLength":1024},"note":{"type":["string","null"],"maxLength":2048},"next_action":{"type":["string","null"],"maxLength":2048}},"required":[],"additionalProperties":false,"minProperties":1}},"required":["entity_id","changes"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.transition"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"to_status":{"type":"string","maxLength":32},"evidence_artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"claim_token":{"anyOf":[{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_generation":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"holder_actor_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_operation_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"authority_epoch":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"}},"required":["resource_id","claim_generation","holder_actor_id","claim_operation_id","authority_epoch"],"additionalProperties":false},{"type":"null"}]}},"required":["entity_id","to_status"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.tombstone"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"reason":{"type":"string","maxLength":1024}},"required":["entity_id","reason"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"campaign.membership.set"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"campaign_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"present":{"type":"boolean"},"is_primary":{"type":"boolean"}},"required":["campaign_id","entity_id","present","is_primary"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"patron.channel.set"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"channel_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"channel_kind":{"enum":["email","phone","domain","other"]},"original_value":{"type":"string","maxLength":1024},"source_region":{"type":["string","null"],"maxLength":2048},"extension":{"type":["string","null"],"maxLength":2048},"source_artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"retire":{"type":"boolean"}},"required":["channel_id","patron_id","channel_kind","original_value","retire"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"patron.primary_channel.set"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"channel_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]}},"required":["patron_id","channel_id"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.alias.set"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"alias_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"original_value":{"type":"string","maxLength":1024},"source_artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"retire":{"type":"boolean"}},"required":["alias_id","entity_id","original_value","retire"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"artifact.register"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"artifact_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"media_type":{"type":"string","maxLength":1024},"size_bytes":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"object_ref":{"type":"string","maxLength":1024},"object_version":{"type":["string","null"],"maxLength":2048},"visibility":{"enum":["local_only","workbook_audience"]}},"required":["artifact_id","media_type","size_bytes","sha256","object_ref","object_version","visibility"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"interaction.append"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"interaction_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"thread_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"subject":{"type":"string","maxLength":1024},"summary":{"type":["string","null"],"maxLength":2048},"approved_excerpt":{"type":["string","null"],"maxLength":2048},"occurred_at":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},"source_artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]}},"required":["interaction_id","patron_id","subject","occurred_at"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"interaction.supersede"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"interaction_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"supersedes_interaction_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"patron_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"record_kind":{"enum":["correction","retraction"]},"thread_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]},"subject":{"type":"string","maxLength":1024},"summary":{"type":["string","null"],"maxLength":2048},"approved_excerpt":{"type":["string","null"],"maxLength":2048},"occurred_at":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},"source_artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]}},"required":["interaction_id","supersedes_interaction_id","patron_id","record_kind","subject","occurred_at"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"dispatch.chunk.append"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"dispatch_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"chunk_index":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"artifact_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_token":{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_generation":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"holder_actor_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_operation_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"authority_epoch":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"}},"required":["resource_id","claim_generation","holder_actor_id","claim_operation_id","authority_epoch"],"additionalProperties":false}},"required":["dispatch_id","chunk_index","sha256","artifact_id","claim_token"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"claim.acquire"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"}},"required":["resource_id"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"claim.release"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_token":{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_generation":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"holder_actor_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"claim_operation_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"authority_epoch":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"}},"required":["resource_id","claim_generation","holder_actor_id","claim_operation_id","authority_epoch"],"additionalProperties":false},"reason":{"type":"string","maxLength":1024}},"required":["resource_id","claim_token","reason"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"claim.recover"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"resource_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"expected_generation":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"fencing_evidence_artifact_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"reason":{"type":"string","maxLength":1024}},"required":["resource_id","expected_generation","fencing_evidence_artifact_id","reason"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"observation.resolve"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"proposal_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"selection_revision":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},"decision":{"enum":["ADOPT","KEEP_LOCAL","REJECT"]},"reason":{"type":"string","maxLength":1024}},"required":["proposal_id","selection_revision","decision","reason"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"project.plan.select"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"project_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"plan_version":{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"}},"required":["project_id","plan_version"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"commercial.terms.set"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"commercial_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"amount_minor":{"anyOf":[{"type":"string","pattern":"^(0|[1-9][0-9]{0,18})$"},{"type":"null"}]},"currency":{"anyOf":[{"type":"string","pattern":"^[A-Z]{3}$"},{"type":"null"}]},"due_at":{"anyOf":[{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},{"type":"null"}]},"artifact_id":{"anyOf":[{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},{"type":"null"}]}},"required":["commercial_id","amount_minor","currency"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.merge"}},"required":["command_type"]},"then":{"properties":{"payload":{"type":"object","properties":{"survivor_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"retired_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"reason":{"type":"string","maxLength":1024},"evidence_artifact_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"}},"required":["survivor_id","retired_id","reason","evidence_artifact_id"],"additionalProperties":false},"schema_version":{"const":"crm.command.v4"}}}},{"if":{"properties":{"command_type":{"const":"entity.tag.set"}},"required":["command_type"]},"then":{"properties":{"schema_version":{"const":"crm.command.v5"},"payload":{"type":"object","properties":{"entity_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"tag":{"type":"string","minLength":1,"maxLength":128},"present":{"type":"boolean"}},"required":["entity_id","tag","present"],"additionalProperties":false}}}}]};
const CRM_ENVELOPE_SCHEMA_ = {"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"urn:sovereign:crm:ingress:4","type":"object","properties":{"protocol":{"const":"crm.ingress.v4"},"kind":{"enum":["command","dirty_hint"]},"delivery_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"sender_key_id":{"type":"string","minLength":1,"maxLength":256},"audience":{"type":"string","minLength":1,"maxLength":256},"tenant_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"ledger_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"issued_at":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},"expires_at":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},"nonce":{"type":"string","pattern":"^[0-9a-f]{64}$"},"payload":{"type":"object"},"payload_digest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"mac":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"required":["protocol","kind","delivery_id","sender_key_id","audience","tenant_id","ledger_id","issued_at","expires_at","nonce","payload","payload_digest","mac"],"additionalProperties":false,"allOf":[{"if":{"properties":{"kind":{"const":"command"}},"required":["kind"]},"then":{"properties":{"payload":{"$ref":"ingest_command_v4.schema.json"}}}},{"if":{"properties":{"kind":{"const":"dirty_hint"}},"required":["kind"]},"then":{"properties":{"payload":{"type":"object","properties":{"workbook_id":{"type":"string","minLength":1,"maxLength":256},"sheet_id":{"type":"integer","minimum":0,"maximum":2147483647},"generation_id":{"type":"string","pattern":"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"},"start_row":{"type":"integer","minimum":0,"maximum":10000000},"end_row_exclusive":{"type":"integer","minimum":0,"maximum":10000000},"start_column":{"type":"integer","minimum":0,"maximum":10000000},"end_column_exclusive":{"type":"integer","minimum":0,"maximum":10000000},"change_class":{"enum":["EDIT","STRUCTURE","WHOLE_SHEET"]},"captured_at":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},"trigger_id":{"anyOf":[{"type":"string","minLength":1,"maxLength":256},{"type":"null"}]}},"required":["workbook_id","sheet_id","generation_id","start_row","end_row_exclusive","start_column","end_column_exclusive","change_class","captured_at","trigger_id"],"additionalProperties":false}}}}]};
const CRM_CAPABILITIES_ = {"entity.create":"entity.create","entity.patch":"entity.edit","entity.transition":"entity.transition","entity.tombstone":"entity.delete","campaign.membership.set":"campaign.edit","patron.channel.set":"patron.edit","patron.primary_channel.set":"patron.edit","entity.alias.set":"entity.edit","artifact.register":"artifact.register","interaction.append":"interaction.append","interaction.supersede":"interaction.correct","dispatch.chunk.append":"dispatch.result","claim.acquire":"claim.acquire","claim.release":"claim.release","claim.recover":"claim.recover","observation.resolve":"resolve_observation","project.plan.select":"project.accept","commercial.terms.set":"commercial.edit","entity.merge":"entity.merge","entity.tag.set":"entity.edit"};
