// Synthetic-only harness: real plugin handler and HTTP, fake outbound recipient.
import {createBridge} from './index.js';
let input='';for await(const chunk of process.stdin)input+=chunk;
const o=JSON.parse(input);if(!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(o.base))throw Error('loopback test only');
const messages=[];const bridge=createBridge({config:o.config,statePath:o.statePath,request:(url,opts)=>fetch(o.base+'/bridge/phone',opts),send:async(w,text)=>messages.push({channel:w.channel,conversation:w.conversation,text})});
const result=o.poll ? (await bridge.tick(),null) : await bridge.handler(o.ctx);
console.log(JSON.stringify({result,messages}));
