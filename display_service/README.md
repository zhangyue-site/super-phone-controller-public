# 106 端额度与交互展示

`python3 -m display_service.app` 仅监听 `127.0.0.1:18943`，由 Nginx 的独立 `/phone-controller/` 路径提供 TLS。

`/etc/phone-controller/devices.json` 保存设备 ID 到随机设备令牌的映射；不使用模型密钥或 tools 管理令牌。仅提供额度白名单摘要、1-bit 位图和 PNG，不转发原始 Cookie、账号身份或上游错误正文。

- `GET /status`：本设备交互与额度摘要。
- `GET /screen.bin?page=0|1`：200×200，逐行 MSB-first，白色位为1，共5000字节。
- `GET /screen.png?page=0|1`：同一渲染器的验收预览。
- `POST /stop`：取消本设备匹配回合；本地ADB由板端立即撤销。响应不声称能撤回已送达手机的动作。

所有接口要求 `Authorization: Bearer <设备令牌>`。新固件的本地ADB执行协议见下文；running/done必须以本轮实际执行与新界面验证为依据。

服务器发起状态更新：

```sh
cd /opt/phone-controller
python3 -m display_service.control epaper-01 --state waiting --task '等待手机接入'
```

状态文件仅服务器写入。每设备独立文件；listening/thinking/running 超过60秒无更新自动显示超时。设备只拉取渲染结果；Mac不参与运行。

106现有quota-mimo.timer每5分钟采集官方额度。server_integrations/server_mimo_quota.py复用服务器原有采集器及mimo_session，renewal_policy.py在HTTP401/403或业务session_expired时续期一次并重试。网络故障不轮换登录，第二次鉴权失败不循环；续期结果记录到mimo-renewal.json，采集失败保留旧值并写lastError供屏幕标记。此处是登录续期，不是付费套餐续费。

## 连续对话与板端 ADB 执行（2026-10-21）

新固件语音上传使用 `X-Voice-Dialogue: 1`。`/voice` 与 `/voice/stream`（HTTP chunked）在识别后创建异步对话任务；无该标记的旧客户端保持仅ASR。设备令牌、16位hex的 `X-Voice-Session`、单调递增 `X-Voice-Sequence` 共同限定回合。

- `POST /dialogue/text`：`{"text":"你好"}`，文本调试入口，同样检查停止序号。
- `POST /dialogue/poll`：wait、一次性交付的typed ADB command、或done。重复poll不重发动作。
- `POST /dialogue/result`：`{"id":"命令ID","ok":true,"output":"真实ADB输出"}`；重复/过期ACK拒绝。
- `POST /dialogue/audio`：本回合16kHz、单声道、PCM16LE结果，最多30秒。
- `POST /dialogue/screen`：大字结果与停止区域，200×200、5000字节。
- `POST /stop`：取消匹配会话中截至指定序号的任务。板端同时撤销本地ADB ticket并中断播放；云端不声称撤回已经送达手机的动作。

106只决策，不直接连接旧中继。板端HTTP先关闭，再在同一个ADB worker中执行固定观察或typed动作；不接受任意shell/文本输入。每一步重新观察，输入前再比对UI；锁屏未知、界面改变、截断或超时均停止。当前允许查看/导航，不自动发送消息、支付、删除、授权或登录。

模型读取 `EPAPER_MODEL_CONFIG`（默认原OpenClaw配置），TTS读取 `EPAPER_SPEECH_CONFIG`（默认原小米ASR配置），使用MiMo TTS并经ffmpeg转16kHz PCM。不在固件或响应中输出模型凭证。内存对话最多24条，15分钟清理；音频不写长期文件，后台清理过期任务。

ADB连接依赖手机5555已启用及RSA授权。当前板子是USB网络设备，不能自动代替原生USB Host在普通未root手机重启后恢复已关闭的ADB TCP端口。未连接时显示具体错误，动作不自动重放。

[本次验证与实机缺口](../docs/handoff/2026-10-21-dialogue-adb-validation.md)

后续开发与升级采用云端工作区、GitHub Actions构建和106私有OTA发布，详见 [云端开发与升级](../docs/cloud-development-and-ota.md)。手机可由机主手动恢复ADB5555；屏幕会明确提醒。本轮不要求改USB Host硬件。

## AI 语音导航与模型路由（2026-10-24 同步）

本轮新增模块：

- `model_routing.py`：所有模型请求统一从 `EPAPER_MODEL_CONFIG` 环境变量指定的本机 JSON（默认 `/root/.openclaw/openclaw.json`，仅服务器本机路径）读取 provider 的 `baseUrl` / `apiKey`。**代码不内置任何密钥**，接入自己的 OpenAI 兼容渠道即可运行。配置示例：

```json
{
  "models": { "providers": {
    "my-provider": {
      "baseUrl": "https://your-endpoint/v1",
      "apiKey": "替换成你自己的key",
      "models": [{ "id": "你的视觉模型名" }]
    }
  }}
}
```

- 渠道/模型选择：`EPAPER_VISION_PROVIDER`（不设则按 xiaomi → opencode-go 顺序取配置中存在者）、`EPAPER_VISION_MODEL`（默认 `mimo-v2.6-flash`，请换成你自己渠道里的模型名）。
- `voice_ui.py`：语音计划预告——板端小屏先显示本轮步骤，板端确认后服务器才开始操作手机。
- `general_nav.py` / `general_vision.py`：通用"打开/进入/搜索"安全导航，含结果核验与第二视觉渠道兜底（`EPAPER_VISION_FALLBACK_PROVIDER`）。
- `autoglm_adapter.py`：AutoGLM 兼容适配（可选，`EPAPER_AUTOGLM_PROVIDER` / `EPAPER_AUTOGLM_MODEL`）。
- `dialogue.py`：执行回执日志现在带错误码（`PHONE_RECEIPT ... ok=False err=input_failed` 等）。板端显示"本轮未完成"时，直接看服务日志的 `err=` 字段即可定位原因（常见：`input_failed` 点击未生效、`screen_changed` 画面变动、超时未回执）。
- 新增 Python 依赖：Pillow（`PIL`，截图区域裁剪与结构比对）。

构建与回归均不调用付费服务：

```sh
python3 -m py_compile display_service/*.py
python3 -m unittest discover -s tests
```

模型推理用的是你自己配置的渠道（免费或付费自选）；本仓库的 CI 只构建 App，不发起任何模型请求。
