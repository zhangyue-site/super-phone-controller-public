# 私聊手机控制桥

确定性 `/phone` 插件；不注册模型工具，不接受模型传入的身份。预览、确认、停止、状态、存为技能全部走后端授权接口。ADB 范围由服务器执行层限制为中文键盘输入；插件不直接执行 ADB。

命令：`/phone 打开微信找到张三` → `/phone 确认 <32位任务编号>`。另有 `/phone 状态 [编号]`、`/phone 停止 [编号]`、`/phone 存为技能 [编号]`，英文 confirm/status/stop/save 同样支持。后端当前仅支持限定的微信搜索任务。

## 身份与部署

安装时不自动授权任何用户。私有配置 `/etc/phone-controller/openclaw-bridge.json` 必须0600，结构为 `{ "token": "独立插件令牌至少43字符", "bindings": [{"channel":"telegram或openclaw-weixin","sender":"受信任发送者ID","conversation":"账户与私聊对象组成的JSON数组字符串","device":"epaper-01"}] }`。令牌不能是设备 bearer。绑定必须从已验证的渠道配对状态获取；不得从聊天任务正文获取。

身份来自真实 SDK command context：`channelId || channel`、`senderId`、`accountId`、`isAuthorizedSender`、`from`、`to`。conversation 严格为 `JSON.stringify([accountId, peer])`，Weixin peer 为 `@im.wechat` 用户ID，Telegram peer 为正数用户ID。拒绝无 accountId、群聊目标、话题线程、缺失身份和非授权发送者。绑定更改不重放旧确认。

审查后部署步骤：

1. 创建私有桥配置和绑定，启用后端 `EPAPER_REMOTE_CONTROL=1`；确认后端只监听127.0.0.1:18943。
2. 创建0700的 `/var/lib/phone-controller`，由网关运行用户拥有。
3. 使用 `/usr/local/bin/openclaw plugins install /opt/phone-controller-workspace-wechat/integrations/openclaw-phone` 安装，检查插件配置/allow列表使 openclaw-phone 启用；若CLI需要以链接方式安装，按当前CLI帮助选择。
4. 在维护窗口重启 OpenClaw 网关。此仓库更改未执行安装、重启或真实消息发送。
5. 两个渠道分别人工发送无害搜索任务，核验预览、同会话确认和停止；用另一渠道确认同一编号应被后端拒绝。真实手机验收独立于模拟测试。

## 结果与故障语义

服务每2秒查询后端，最终结果经实际 `api.runtime.channel.outbound.loadAdapter(channel)` 的 `sendText({cfg,to,text,accountId})` 发回已绑定来源。目的地只来自受信任私聊身份。观察记录0600原子保存，重启恢复查询，不重复提交确认或执行任务。

网络发送前持久化 dispatching；发送成功后删除记录。无法判断发送是否到达时不重试，以免重复推送，用户可 `/phone 状态 <编号>` 取回结果。这是 at-most-once 推送，不保证网络故障时一定到达。准备请求与本地观察记录写入之间异常退出也可导致无主动推送；后端仍负责确认幂等和任务持久化。没有跨后端/渠道原子事务，不能声称 exactly-once。

当前 SDK 无命令上下文 ChatType，因此私聊靠 from/to 与已绑定发送者严格一致验证。Weixin 当前安装源码明确将 From/To 设置为 direct 用户；Telegram数字私聊只允许正数用户目标。不能在缺失accountId或身份格式变化时退化为默认账户。

测试：`/www/server/nodejs/v22.15.1/bin/node --test test.mjs`。测试完全使用假渠道和假后端，不会发消息或操作手机。

## 板端停止与单连接传输

板端空闲领取使用每次启动的云端租约握手与递增序号。远程动作前及每次取命令前同步检查停止；既有ADB网络代理只有单连接，不并行发起停止轮询。云端停止不能中断已经开始的中文输入或HTTP传输，中文命令遵循原12秒截止和输入法清理；随后不再执行下一动作。本地屏幕停止仍撤销板端输入许可。后台画面/事件刷新与远程执行互斥，待上报的本地停止会阻止新领取，OTA期间不领取手机任务。物理时延与IME恢复需实机验收。

## 激活验收
当前龙虾版本需要manifest显式声明activation.onStartup=true，持久化结果服务才能随网关启动；phone声明runtime-slash命令归属和onCommands提示。仅plugins info显示enabled不构成运行验收。检查实际启动规划器包含openclaw-phone、网关phone runtime initialized及真实私聊phone handled/status日志，然后核对状态回复。入口日志只记录渠道、布尔身份字段、操作类别和结果状态，不记录用户ID或任务正文。
