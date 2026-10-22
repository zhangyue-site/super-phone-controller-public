# 墨水屏原生 USB 恢复诊断固件

用于ESP32-S3微雪1.54 V2的启动与USB诊断。不开启TinyUSB HID，不初始化或刷新屏幕，不启用WiFi，不读取或写入NVS。GPIO18作为PWR输入，GPIO17保持电池供电；长按PWR1.5秒关闭电池供电保持。USB仍可供电，墨水屏保留原图不代表未关机。

必须先通过官方的“按住BOOT重新上电”进入下载模式，并从USB枚举信息/芯片身份确认目标。没有USB枚举时不能从电脑刷写。带电池且当前固件无法关机时需要实际断开电池供电再上电；不要求操作不存在的RST键。

使用ESP-IDF5.5.2 `idf.py build`。沿用原始NVS、OTA和assets布局，刷写app时不覆盖NVS或assets。原板全片备份位于本机被忽略的private-backups目录。

2026-10-20：在电池断开、按住BOOT接USB后，原板（MAC末尾D4:18）成功进入下载模式；整片备份SHA256校验通过，恢复固件及配套启动文件已写入，各区域通过esptool校验。刷写后日志仍停在ROM下载模式；要求松开BOOT并重新接USB启动。此后暂未再次检测到目标串口，因此**仅确认写入成功，尚未确认应用启动和持续心跳**。恢复固件不初始化屏幕，旧画面或不刷新不能用作运行状态证明。

官方说明：https://docs.waveshare.net/ESP32-S3-ePaper-1.54/FAQ/

## 一体机限制（官方触摸版原理图复核）

用户设备为一体机，不能假定电池插头外露，不要求用户自行拆壳。官方原理图显示PWR通过电源保持电路与GPIO18/17配合，BOOT接GPIO0；没有独立外露RESET按钮，也未从官方资料确认不依赖固件的强制关机组合。USB枚举失败且当前程序无法关机时，电脑无法直接写入Flash。无需拆机的恢复路径是断开USB等待电池耗尽，再按住BOOT接USB重新上电；如果等待不可接受，需要由具备该机型维护条件的人操作真实断电/芯片复位。不要把持续按住运行中的BOOT当作必然复位。

原理图：https://github.com/waveshareteam/ESP32-S3-ePaper-1.54/blob/main/04_Hardware/Schematics/ESP32-S3-Touch-ePaper-1.54-Schematic.pdf

## 后续验收

已读取恢复固件完整启动日志，并收到uptime约3/6/9秒的连续心跳。后续普通固件真机CDC-only PID0x4001，默认HID/蓝牙/Wi-Fi关闭，LOGS缓存可读；屏幕曾因5ms延时被100Hz调度截为0 tick而过早超时，修正版改为真实时钟截止时间。软件退出原生ROM下载模式应优先使用已验证的 `esptool --after watchdog_reset`；不要把反复RTS reset回到下载模式误认成仍按着BOOT。
