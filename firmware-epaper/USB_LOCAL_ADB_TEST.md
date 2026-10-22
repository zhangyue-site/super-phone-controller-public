# USB 本地 ADB：独立实验版

这是验证版，不是完整语音控制固件。只用于验证原板NCM、本地IP、ADB5555鉴权与只读shell；不自动切换以太网共享，不执行手机控制命令。测试版语音页长按触发ADB验证，暂不录音；原有联网/CDC版本保留录音功能。

## 构建

先运行 `python tools/provision_board_adb_key.py` 生成板子专用身份。新私钥只保存在忽略的private-backups/与device_adb_keys.h内，勿上传密钥或固件。然后在ESP-IDF5.5.2环境运行：

```
idf.py -C firmware-epaper -B build-usb-local -D SDKCONFIG=sdkconfig.usb-local -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.usb-local.defaults' build
```

本地网络固定192.168.77.1/24，板子DHCPserver分配手机IP，不宣告网关/DNS。无互联网不是测试失败；该模式不得将DHCP租约标为106连通。Android是否接受这种local-only租约需实测，若网卡出现但IP被系统撤销，记录IpClient行为再调整；不能先用Mac租约证明手机已支持。

## 验证顺序

1. 板子接Mac刷入，默认HID/Wi-Fi/蓝牙/ADB关闭，本地版本拒绝WIFI ON。
2. 先测Mac拿到USB局域网地址，记录lease日志；不算手机通过。
3. 若需记录手机直连时的网络状态，可通过已授权USB ADB启动 tools/phone_usb_capture.sh（40轮、每轮等待2秒+ping超时，约两分钟以内），把日志写在/data/local/tmp。无需安装App；完成后删除脚本和日志。
4. 手机接板子后，网络页显示板子地址与是否发出租约。STATUS net=5等待租约，net=6已分配本地IP；peer为网络字节序十六进制IP，LOGS输出点分地址。
5. 语音页长按小太阳后尝试TCP5555。若手机第一次收到板子公钥，请在手机确认。成功只执行echo固定标记并保留连接；手机重启/连接丢失、停止/拔线后不自动重连。
6. ADB状态0关闭、1检测、2等待手机授权、3只读probe成功、4无本地IP、5传输/鉴权失败。只有当前票据有效才能显示成功，旧worker不允许覆盖新票据。

## 必须区分的条件

手机普通USB调试不等于网络ADB已监听。用Mac执行adb tcpip5555只能用于协议诊断，不算免Mac启动方案；测试后用adb usb恢复。可用tools/verify_phone_adb_usb_forward.py配合USB端口转发单独验证板子身份与目标手机ADB，仍不能替代实板USB网络。

手机冷启动默认端口未开启时，当前代码无法自行启用手机adbd。没有安装App、Wi-Fi或直接USB ADB主机通道时，尚未找到可信的自动恢复入口。需要真机验证手机是否提供独立系统设置；不修改持久调试属性、系统镜像或申请root。
