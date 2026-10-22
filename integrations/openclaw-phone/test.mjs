import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {identity,parse,createBridge} from './index.js';
const task_id='a'.repeat(32);
for (const channel of ['telegram','openclaw-weixin']) test(`${channel} trusted identity, prepare/confirm, scoped final and restart`,async()=>{
 const senderId=channel==='telegram'?'123456':'test@im.wechat';
 const ctx={channel,senderId,accountId:'bot-one',isAuthorizedSender:true,from:senderId,to:senderId};
 const p=identity(ctx); const sent=[],calls=[];
 const statePath=mkdtempSync(tmpdir()+'/phone-test-')+'/watch.json';
 let terminal=false;
 const opts={config:{token:'fake',bindings:[p]},statePath,send:async(w,text)=>sent.push([w,text]),request:async(url,r)=>{calls.push(JSON.parse(r.body));return{ok:true,json:async()=>({reply:terminal?'完成':'预览',task_id,terminal})};}};
 let b=createBridge(opts);
 assert.equal((await b.handler({...ctx,args:'搜索联系人'})).text,'预览');
 assert.equal(calls[0].operation,'prepare');
 await b.handler({...ctx,args:`确认 ${task_id}`}); assert.equal(calls[1].operation,'confirm');
 b=createBridge(opts); terminal=true; await b.tick(); await b.tick(); assert.equal(sent.length,1); assert.equal(sent[0][0].to,senderId);
 assert.throws(()=>identity({...ctx,isAuthorizedSender:false}));
 assert.throws(()=>identity({...ctx,to:'-987654'}));
 assert.throws(()=>identity({...ctx,messageThreadId:1}));
 const before=calls.length; await b.handler({...ctx,senderId:'99999',args:`确认 ${task_id}`});assert.equal(calls.length,before);
});
test('malformed confirmation and command grammar',()=>{assert.throws(()=>parse('confirm nope'));assert.throws(()=>parse('确认 不正确'));assert.throws(()=>parse('确认'));assert.equal(parse('停止').operation,'stop');assert.equal(parse('存为技能').operation,'save');});
test('ambiguous outbound never retries after network failure or restart',async()=>{
 const ctx={channel:'telegram',senderId:'123',accountId:'bot',isAuthorizedSender:true,from:'123',to:'123'};const p=identity(ctx);let n=0;
 const opts={config:{token:'fake',bindings:[p]},statePath:mkdtempSync(tmpdir()+'/phone-test-')+'/w',send:async()=>{n++;throw Error('network');},request:async()=>({ok:true,json:async()=>({reply:'ok',task_id,terminal:false})})};
 const b=createBridge(opts);await b.handler({...ctx,args:'测试'});opts.request=async()=>({ok:true,json:async()=>({reply:'done',task_id,terminal:true})});
 const c=createBridge(opts);await c.tick();await c.tick();await createBridge(opts).tick();assert.equal(n,1);
});
test('installed entry registers deterministic command and lifecycle',async()=>{
 const {writeFileSync}=await import('node:fs'); const {default:register}=await import('./index.js');
 const dir=mkdtempSync(tmpdir()+'/phone-register-');const path=dir+'/private.json';writeFileSync(path,JSON.stringify({token:'x'.repeat(48),bindings:[]}),{mode:0o600});
 let command,service; register({pluginConfig:{bridgeConfigPath:path,statePath:dir+'/state'},logger:{warn(){}},config:{},runtime:{channel:{outbound:{loadAdapter(){throw Error('must not send');}}}},registerCommand:c=>command=c,registerService:s=>service=s});
 assert.equal(command.name,'phone');assert.equal(command.requireAuth,true);assert.deepEqual(command.channels,['openclaw-weixin','telegram']);assert.equal(typeof service.start,'function');assert.equal(typeof service.stop,'function');
});

test('manifest activates runtime command and durable result service on gateway startup',async()=>{
 const {readFileSync}=await import('node:fs');const m=JSON.parse(readFileSync(new URL('./openclaw.plugin.json',import.meta.url),'utf8'));
 assert.equal(m.activation?.onStartup,true);assert.ok(m.activation.onCommands.includes('phone'));
 assert.ok(m.commandAliases.some(x=>x.name==='phone'&&x.kind==='runtime-slash'));
});
