// BLE OTA：手机通过蓝牙把固件推给板子，板子写进备用 OTA 槽并切换启动。
//
// 为什么走 BLE 而不是复用 HTTP：板子经常没有 Wi-Fi 凭据或 Wi-Fi 挂了，
// 只要手机在旁边就能升级。BLE 吞吐低（实测 10-20 KB/s），1.3MB 固件
// 约 1-2 分钟，对墨水屏这种低频升级场景可以接受。
//
// GATT 设计（尽量简单，手机端只用一个特征值写、一个读状态）：
//   SERVICE  6f6f7461-2d6f-7461-0000-000000000001
//   CTRL     6f6f7461-2d6f-7461-0000-000000000002  write/notify
//            手机写入的指令（首字节是命令码）：
//              0x01 BEGIN  后跟 4 字节小端总长度、32 字节 sha256 → 回 STATUS
//              0x02 DATA   后跟固件分片（应在 MTU 内）→ 回 STATUS
//              0x03 END    收尾校验并切槽 → 回 STATUS
//              0x04 ABORT  放弃当前传输
//   STATUS   6f6f7461-2d6f-7461-0000-000000000003  read/notify
//            4 字节状态：[state, progress(0-100), err, reserved]
//
// 状态机：IDLE → RECEIVING → VERIFYING → READY → (重启) 或 ERROR
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    BLE_OTA_IDLE = 0,
    BLE_OTA_RECEIVING = 1,
    BLE_OTA_VERIFYING = 2,
    BLE_OTA_READY = 3,
    BLE_OTA_ERROR = 4,
} ble_ota_state_t;

typedef enum {
    BLE_OTA_OK = 0,
    BLE_OTA_ERR_STATE = 1,     // 当前状态不允许该操作
    BLE_OTA_ERR_PARAM = 2,     // 长度/sha 不合法
    BLE_OTA_ERR_FLASH = 3,     // 写 flash 失败
    BLE_OTA_ERR_SIZE = 4,      // 超过 OTA 槽位
    BLE_OTA_ERR_SHA = 5,       // 校验不符
    BLE_OTA_ERR_HASH = 6,      // 镜像头部不认
} ble_ota_err_t;

// 启动 BLE OTA 服务（幂等）。返回 esp_err_t。
int ble_ota_start(void);

// 当前状态快照，供屏幕显示。
void ble_ota_status(ble_ota_state_t *state, uint8_t *progress, uint8_t *err);

// 是否正在传输（屏幕任务据此避免频繁重绘、暂停耗电任务）。
bool ble_ota_busy(void);
void ble_ota_cancel(void);

#ifdef __cplusplus
}
#endif
