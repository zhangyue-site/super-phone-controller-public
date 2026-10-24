# 超级手机控制器 · zy的codex

ESP32-S3 作为 HID 鼠标与云端指令桥；Android 升级助手负责经系统授权的整屏共享、蓝牙升级和文字任务入口。云端分析画面，用户确认后执行，并核验结果。ADB 仅用于中文键盘输入，完成、失败或停止后恢复原输入法。搜索联系人只停在结果页，不发消息。

## 当前状态

官方 Android 版本 1.0.8（9）。首次 USB 提示选择默认 App、明确配对对应控制板后，后续插入自动准备系统整屏共享授权。必须本人确认；不能绕过系统授权。共享助手复用升级 App，不另装采集 App。HID 操作许可仍由板端开启。

已知问题：1.0.8 在无任务时把服务端 202 缺少 barrier 显示成上传失败；本快照已修复服务端兼容响应。真机整屏上传、USB 默认打开、微信实际搜索和 App UI OTA 仍需现场验收；单元测试不等于实机通过。

## 构建

- Android：Flutter 3.44.0、JDK 17、Android SDK 36；`cd app && flutter pub get && flutter test && flutter build apk --debug`。
- GitHub Actions 仅构建社区 debug APK，不带正式签名，不能覆盖官方正式 App。正式更新从官方下载页安装。
- ESP32-S3：使用 ESP-IDF 6.0，复制 `firmware-epaper/main/device_config.example.h` 为忽略的 `device_config.h`，填写自己的服务端及设备凭据；ADB 私钥按 `tools/provision_board_adb_key.py` 为自己的板子生成。不要使用其他设备身份，不要公开生产固件。
- 服务端：Python 3，依赖及启动见 `display_service/README.md`。生产地址、API 密钥和设备身份由运行环境配置。
- 回归：`python3 -m unittest discover -s tests` 和 `python3 -m unittest discover -s display_service/tests`；构建交互测试见 `tools/test_host.py`。

## 发布与隐私

这是从私有开发仓库导出的干净源码快照，不包含历史提交、私人交接记录、实机屏幕预览、私钥、签名证书、用户配置或含设备身份的固件。生产构建历史和 GitHub Secrets 不迁入公开仓库。合成测试夹具用于回归，不含真实手机截屏。Android 正式安装包复用原助手图标及签名；公开源码仍保留 Android 包名和公开服务地址以兼容现有安装。

展示及提交作者：zy的codex。第三方组件和兼容代码保留原许可证声明；本项目未另行授予许可证，使用须遵守各自许可及 GitHub 条款。

官方下载：https://d.zhangyue.site/apps/phone-controller-flash/

## 2026-10-24 快照更新

- 服务端同步：语音计划预告（板端确认后才执行）、通用安全导航、模型路由、渲染与回执日志更新（display_service 20 个文件）。
- 模型渠道完全由 `EPAPER_MODEL_CONFIG` 指定的本机配置提供（OpenAI 兼容格式），代码零内置密钥；接入任意自有/免费渠道即可运行，演示渠道不公开。
- 每轮 HID 执行回执带错误码日志："本轮未完成"的原因可在服务日志按 `err=` 直接定位（input_failed / screen_changed / 超时等）。
- 新增 Python 依赖 Pillow。构建仅需本地 Flutter/JDK/ESP-IDF 工具链与 GitHub 免费 ubuntu runner；本仓库不含付费 CI 步骤，也不内置任何付费 API 依赖。
