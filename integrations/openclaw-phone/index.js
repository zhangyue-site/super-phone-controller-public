import { readFileSync, writeFileSync, renameSync, mkdirSync, statSync } from 'node:fs';
import { dirname } from 'node:path';
const ID = /^[a-f0-9]{32}$/;
export function identity(ctx) {
  const channel = ctx.channelId || ctx.channel;
  const sender = ctx.senderId;
  if (!ctx.isAuthorizedSender || !sender || !ctx.accountId || ctx.messageThreadId != null || ctx.threadParentId) throw Error('仅允许已授权的私人会话。');
  let peer;
  if (channel === 'openclaw-weixin' && ctx.from === sender && ctx.to === sender && sender.endsWith('@im.wechat')) peer = sender;
  if (channel === 'telegram' && /^[1-9][0-9]*$/.test(sender) && [sender, `telegram:${sender}`].includes(ctx.from) && [sender, `telegram:${sender}`].includes(ctx.to)) peer = sender;
  if (!peer) throw Error('无法验证私人会话身份。');
  return { channel, sender, conversation: JSON.stringify([ctx.accountId, peer]), accountId: ctx.accountId, to: peer, device: 'epaper-01' };
}
export function parse(args = '') {
  const s = args.trim();
  const m = /^(confirm|确认)\s+([a-f0-9]{32})$/i.exec(s);
  if (m) return { operation: 'confirm', task_id: m[2].toLowerCase() };
  const a = /^(status|状态|stop|停止|save|存为技能)(?:\s+([a-f0-9]{32}))?$/i.exec(s);
  if (a) return { operation: ({status:'status',状态:'status',stop:'stop',停止:'stop',save:'save',存为技能:'save'})[a[1].toLowerCase()], ...(a[2] ? {task_id:a[2].toLowerCase()} : {}) };
  if (!s || /^(confirm|确认)(?:\s|$)/i.test(s) || s.length > 2000) throw Error('用法：/phone 任务；/phone 确认 任务编号；/phone 状态；/phone 停止；/phone 存为技能。');
  return { operation:'prepare', text:s };
}
export function createBridge({ config, statePath, request = fetch, send, warn = () => {}, audit = () => {} }) {
  let watches = [];
  try { watches = JSON.parse(readFileSync(statePath,'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (!Array.isArray(watches)) throw Error('Invalid watcher state');
  const persist = () => { mkdirSync(dirname(statePath),{recursive:true,mode:0o700}); writeFileSync(statePath+'.tmp', JSON.stringify(watches),{mode:0o600}); renameSync(statePath+'.tmp',statePath); };
  const allowed = p => config.bindings.some(b => ['channel','sender','conversation','device'].every(k => b[k] === p[k]));
  async function call(p, cmd) {
    if (!allowed(p)) throw Error('此私人会话尚未授权控制设备。');
    const {channel,sender,conversation,device} = p;
    const r = await request('http://127.0.0.1:18943/bridge/phone',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},body:JSON.stringify({channel,sender,conversation,device,...cmd}),signal:AbortSignal.timeout(10000)});
    if (!r.ok) throw Error('手机控制服务拒绝请求，请检查授权或稍后重试。');
    const data = await r.json();
    if (typeof data.reply !== 'string') throw Error('手机控制服务返回无效结果。');
    return data;
  }
  let ticking = false;
  async function tick() {
    if (ticking) return;
    ticking = true;
    try {
      for (const w of [...watches]) {
        if (w.delivery === "dispatching") continue;
        if (!allowed(w) || !ID.test(w.task_id) || w.conversation !== JSON.stringify([w.accountId,w.to])) { watches = watches.filter(x=>x!==w); persist(); continue; }
        try {
          const r = await call(w,{operation:'status',task_id:w.task_id});
          if (r.terminal) {
            // Persist dispatch intent first: ambiguous network outcomes are never automatically resent.
            w.delivery = 'dispatching'; persist();
            await send(w,r.reply);
            watches = watches.filter(x=>x!==w); persist();
          }
        } catch { warn('phone watcher request/delivery failed'); }
      }
    } finally { ticking = false; }
  }
  // Restart after an ambiguous send never duplicates a recipient-visible message.
  watches = watches.filter(w=>w.delivery !== 'dispatching');
  async function handler(ctx) {
    let phase="identity";
    const channel=["telegram","openclaw-weixin"].includes(ctx.channelId||ctx.channel)?(ctx.channelId||ctx.channel):"unknown";
    audit(`phone ingress channel=${channel} authorized=${ctx.isAuthorizedSender===true} sender=${Boolean(ctx.senderId)} account=${Boolean(ctx.accountId)}`);
    try {
      const p = identity(ctx), cmd = parse(ctx.args);phase="bridge";
      if (['status','save'].includes(cmd.operation) && !cmd.task_id) cmd.task_id = watches.findLast(w=>w.conversation===p.conversation && w.channel===p.channel)?.task_id;
      const r = await call(p,cmd);
      if (r.task_id && ID.test(r.task_id) && !r.terminal && ['prepare','confirm'].includes(cmd.operation)) {
        if (!watches.some(w=>w.task_id===r.task_id)) watches.push({...p,task_id:r.task_id});
        persist();
      }
      audit(`phone handled channel=${p.channel} operation=${cmd.operation} state=${r.state||"unknown"}`);
      return {text:r.reply};
    } catch(e) { audit(`phone rejected channel=${channel} phase=${phase}`);return {text: e.message.startsWith('仅') || e.message.startsWith('无法') || e.message.startsWith('此') || e.message.startsWith('用法') || e.message.startsWith('手机') ? e.message : '手机控制暂不可用，请稍后重试。'}; }
  }
  return {handler,tick};
}
export default function register(api) {
  const configPath = api.pluginConfig?.bridgeConfigPath || '/etc/phone-controller/openclaw-bridge.json';
  if ((statSync(configPath).mode & 0o077) !== 0) throw Error('Bridge config must be private (0600)');
  const config = JSON.parse(readFileSync(configPath,'utf8'));
  if (typeof config.token !== 'string' || config.token.length < 43 || !Array.isArray(config.bindings)) throw Error('Invalid private bridge config');
  const bridge = createBridge({config,statePath:api.pluginConfig?.statePath || '/var/lib/phone-controller/openclaw-watchers.json',warn: m=>api.logger.warn(m),audit:m=>api.logger.info?.(m),send:async (w,text)=>{
    const adapter = await api.runtime.channel.outbound.loadAdapter(w.channel);
    if (!adapter?.sendText) throw Error('Channel outbound unavailable');
    await adapter.sendText({cfg:api.config,to:w.to,accountId:w.accountId,text});
  }});
  api.registerCommand({name:'phone',description:'手机任务预览、确认、状态和停止',acceptsArgs:true,requireAuth:true,channels:['openclaw-weixin','telegram'],handler:bridge.handler});
  api.logger.info?.('phone runtime initialized; private command and result service registered');
  let timer;
  api.registerService({id:'phone-result-watchers',start:()=>{timer=setInterval(()=>void bridge.tick(),2000);timer.unref?.();void bridge.tick();},stop:()=>clearInterval(timer)});
}
