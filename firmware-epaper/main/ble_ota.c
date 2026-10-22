#include "ble_ota.h"
#include "device_config.h"
#ifndef DISPLAY_DEVICE_ID
#define DISPLAY_DEVICE_ID "epaper-01"
#endif
#include "ota_generation.h"
#include <string.h>
#include <stdbool.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_app_format.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_random.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "psa/crypto.h"

static const char *TAG = "ble_ota";

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
static atomic_int s_state = BLE_OTA_IDLE;
static atomic_int s_err = BLE_OTA_OK;
static atomic_int s_progress = 0;
static atomic_bool s_busy = false;

static esp_ota_handle_t s_ota_handle = 0;
static const esp_partition_t *s_ota_part = NULL;
static uint32_t s_total = 0;
static uint32_t s_written = 0;
static uint8_t s_expect_sha[32];
static psa_hash_operation_t s_sha = PSA_HASH_OPERATION_INIT;
static bool s_sha_live = false;

static uint16_t s_conn = BLE_HS_CONN_HANDLE_NONE;
static uint16_t s_status_handle = 0;
static uint8_t s_auth_proof[32];
static bool s_auth_ready;
static char s_boot_nonce[33];

// 手机写入的片不进回调直接处理：回调里写 flash 会卡住 NimBLE host 任务，
// 导致连接超时。统一塞进队列，由 writer 任务串行处理。
typedef struct {
    uint8_t cmd;
    unsigned generation;
    uint16_t len;
    uint8_t data[512];
} chunk_t;
static QueueHandle_t s_queue = NULL;
static atomic_uint s_generation = 0;


static void notify_status(void);
static void advertise(void);

static void set_state(ble_ota_state_t st, ble_ota_err_t err) {
    atomic_store(&s_err, err);
    atomic_store(&s_state, st);
    ESP_LOGI(TAG, "state=%d err=%d progress=%d", (int)st, (int)err, atomic_load(&s_progress));
    notify_status();
}

// ---------------------------------------------------------------------------
// 传输控制
// ---------------------------------------------------------------------------
// 最小合法固件长度：镜像头 + 至少要有一点内容。真正的大小由 sha 校验兜底。
#define MIN_IMAGE 4096

static ble_ota_err_t begin_transfer(const uint8_t *p, uint16_t len) {
    if (len < 1 + 4 + 32) return BLE_OTA_ERR_PARAM;
    if (atomic_load(&s_busy)) return BLE_OTA_ERR_STATE;

    uint32_t total = (uint32_t)p[1] | ((uint32_t)p[2] << 8) |
                     ((uint32_t)p[3] << 16) | ((uint32_t)p[4] << 24);
    if (total < MIN_IMAGE) return BLE_OTA_ERR_PARAM;

    s_ota_part = esp_ota_get_next_update_partition(NULL);
    if (!s_ota_part) return BLE_OTA_ERR_FLASH;
    if (total > s_ota_part->size) {
        ESP_LOGE(TAG, "image %u > slot %u", total, (unsigned)s_ota_part->size);
        return BLE_OTA_ERR_SIZE;
    }

    // 拿到锁前先清干净上一次的残留
    if (s_ota_handle) { esp_ota_abort(s_ota_handle); s_ota_handle = 0; }

    esp_err_t e = esp_ota_begin(s_ota_part, OTA_WITH_SEQUENTIAL_WRITES, &s_ota_handle);
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "ota_begin: %s", esp_err_to_name(e));
        s_ota_handle = 0;
        return BLE_OTA_ERR_FLASH;
    }

    memcpy(s_expect_sha, p + 5, 32);
    if (s_sha_live) { psa_hash_abort(&s_sha); }
    s_sha = (psa_hash_operation_t)PSA_HASH_OPERATION_INIT;
    if (psa_hash_setup(&s_sha, PSA_ALG_SHA_256) != PSA_SUCCESS) return BLE_OTA_ERR_PARAM;
    s_sha_live = true;

    s_total = total;
    s_written = 0;
    atomic_store(&s_progress, 0);
    atomic_store(&s_busy, true);
    set_state(BLE_OTA_RECEIVING, BLE_OTA_OK);
    return BLE_OTA_OK;
}

static ble_ota_err_t abort_transfer(void) {
    if (s_ota_handle) { esp_ota_abort(s_ota_handle); s_ota_handle = 0; }
    if (s_sha_live) { psa_hash_abort(&s_sha); s_sha_live = false; }
    atomic_store(&s_busy, false);
    atomic_store(&s_progress, 0);
    set_state(BLE_OTA_IDLE, BLE_OTA_OK);
    return BLE_OTA_OK;
}

static ble_ota_err_t end_transfer(unsigned generation) {
    if (!atomic_load(&s_busy) || !s_ota_handle) return BLE_OTA_ERR_STATE;
    // 队列里可能还有没写完的片：等它们落盘再校验，否则最后一片会丢。
    // END is processed by the same writer after all preceding DATA commands.

    if (s_written != s_total) {
        ESP_LOGE(TAG, "size mismatch written=%u total=%u", s_written, s_total);
        abort_transfer();
        return BLE_OTA_ERR_SIZE;
    }

    set_state(BLE_OTA_VERIFYING, BLE_OTA_OK);

    uint8_t digest[32];
    size_t digest_len = 0;
    bool hash_ok = s_sha_live &&
        psa_hash_finish(&s_sha, digest, sizeof(digest), &digest_len) == PSA_SUCCESS &&
        digest_len == 32;
    s_sha_live = false;
    if (!hash_ok) {
        ESP_LOGE(TAG, "hash finalize failed");
        abort_transfer();
        return BLE_OTA_ERR_SHA;
    }
    if (memcmp(digest, s_expect_sha, 32) != 0) {
        ESP_LOGE(TAG, "sha256 mismatch");
        abort_transfer();
        return BLE_OTA_ERR_SHA;
    }

    if (atomic_load(&s_generation) != generation) { abort_transfer(); return BLE_OTA_ERR_STATE; }
    esp_err_t e = esp_ota_end(s_ota_handle);
    s_ota_handle = 0;
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "ota_end: %s", esp_err_to_name(e));
        // esp_ota_end 失败已经释放句柄，不需要再 abort。
        atomic_store(&s_busy, false);
        set_state(BLE_OTA_ERROR, BLE_OTA_ERR_HASH);
        return BLE_OTA_ERR_HASH;
    }

    // Atomic commit boundary: cancellation wins until this CAS. Once switching
    // the boot slot begins, cancellation cannot undo the already verified update.
    if (!controller_ota_try_commit(&s_generation, generation)) {
        abort_transfer(); return BLE_OTA_ERR_STATE;
    }
    e = esp_ota_set_boot_partition(s_ota_part);
    if (e != ESP_OK) {
        atomic_fetch_and(&s_generation, ~CONTROLLER_OTA_COMMIT_FLAG);
        ESP_LOGE(TAG, "set_boot: %s", esp_err_to_name(e));
        atomic_store(&s_busy, false);
        set_state(BLE_OTA_ERROR, BLE_OTA_ERR_FLASH);
        return BLE_OTA_ERR_FLASH;
    }

    atomic_store(&s_progress, 100);
    atomic_store(&s_busy, false);
    set_state(BLE_OTA_READY, BLE_OTA_OK);
    ESP_LOGI(TAG, "image verified, boot partition switched");
    return BLE_OTA_OK;
}

// ---------------------------------------------------------------------------
// writer 任务：从队列取片写 flash
// ---------------------------------------------------------------------------
static void writer_task(void *) {
    chunk_t *c = (chunk_t *)malloc(sizeof(chunk_t));
    if (!c) { ESP_LOGE(TAG, "no mem"); vTaskDelete(NULL); return; }
    unsigned generation = atomic_load(&s_generation);
    for (;;) {
        BaseType_t received = xQueueReceive(s_queue, c, pdMS_TO_TICKS(100));
        if (controller_ota_sync_generation(&s_generation, &generation)) abort_transfer();
        if (received != pdTRUE || c->generation != generation) continue;
        ble_ota_err_t result = BLE_OTA_OK;
        if (c->cmd == 1) {
            result = begin_transfer(c->data, c->len);
        } else if (c->cmd == 3) {
            result = end_transfer(c->generation);
            if (result == BLE_OTA_OK) {
                vTaskDelay(pdMS_TO_TICKS(1200)); esp_restart();
            }
        } else if (c->cmd == 4) {
            abort_transfer();
        }
        if (c->cmd != 2) {
            if (result != BLE_OTA_OK) { abort_transfer(); set_state(BLE_OTA_ERROR, result); }
            continue;
        }
        if (!atomic_load(&s_busy) || !s_ota_handle) continue;

        uint32_t room = s_total - s_written;
        uint16_t n = c->len;
        if (n > room) { abort_transfer(); set_state(BLE_OTA_ERROR, BLE_OTA_ERR_SIZE); continue; }

        esp_err_t e = esp_ota_write(s_ota_handle, c->data, n);
        if (e != ESP_OK) {
            ESP_LOGE(TAG, "ota_write: %s", esp_err_to_name(e));
            abort_transfer();
            set_state(BLE_OTA_ERROR, BLE_OTA_ERR_FLASH);
            continue;
        }
        if (s_sha_live && psa_hash_update(&s_sha, c->data, n) != PSA_SUCCESS) {
            ESP_LOGE(TAG, "hash update failed");
            abort_transfer();
            set_state(BLE_OTA_ERROR, BLE_OTA_ERR_FLASH);
            continue;
        }
        s_written += n;
        int pct = (int)((uint64_t)s_written * 100 / s_total);
        // 只在百分比整数变化时通知，省 BLE 带宽。
        if (pct != atomic_load(&s_progress)) {
            atomic_store(&s_progress, pct);
            notify_status();
        }
    }
}

// ---------------------------------------------------------------------------
// GATT
// ---------------------------------------------------------------------------
static const ble_uuid128_t SVC_UUID = BLE_UUID128_INIT(0x01,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);
static const ble_uuid128_t CTRL_UUID = BLE_UUID128_INIT(0x02,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);
static const ble_uuid128_t STAT_UUID = BLE_UUID128_INIT(0x03,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);

static const ble_uuid128_t INFO_UUID = BLE_UUID128_INIT(0x04,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);
static const ble_uuid128_t AUTH_UUID = BLE_UUID128_INIT(0x05,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);
static void hex_string(const uint8_t *data, size_t len, char *out) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i=0;i<len;i++) { out[i*2]=hex[data[i]>>4]; out[i*2+1]=hex[data[i]&15]; }
    out[len*2]=0;
}
// Read-only local connection flags; no credentials, screen pixels or phone actions.
extern void controller_ble_diagnostic_state(char *out, unsigned size);
static const ble_uuid128_t DIAG_UUID = BLE_UUID128_INIT(0x06,0,0,0,0,0,0,0,0x61,0x74,0x6f,0x2d,0x61,0x74,0x6f,0x6f);
static int diag_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg) {
    if(ctxt->op!=BLE_GATT_ACCESS_OP_READ_CHR)return BLE_ATT_ERR_UNLIKELY;
    char out[384];controller_ble_diagnostic_state(out,sizeof(out));
    return os_mbuf_append(ctxt->om,out,strlen(out))==0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}
static int info_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg) {
    if(ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR)return BLE_ATT_ERR_UNLIKELY;
    const esp_app_desc_t *desc=esp_app_get_description();
    esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
    esp_ota_get_state_partition(esp_ota_get_running_partition(),&state);
    char elf[65],buf[384];hex_string(desc->app_elf_sha256,32,elf);
    int n=snprintf(buf,sizeof(buf),"{\"protocol\":1,\"device\":\"%s\",\"version\":\"%s\",\"elfSha256\":\"%s\",\"boot\":\"%s\",\"imageState\":%d}",DISPLAY_DEVICE_ID,desc->version,elf,s_boot_nonce,(int)state);
    if(n<0 || n>=(int)sizeof(buf))return BLE_ATT_ERR_INSUFFICIENT_RES;
    return os_mbuf_append(ctxt->om,buf,n)==0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}
static int auth_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg) {
    if(ctxt->op==BLE_GATT_ACCESS_OP_READ_CHR) {
        if(!s_auth_ready)return BLE_ATT_ERR_UNLIKELY;
        return os_mbuf_append(ctxt->om,s_auth_proof,32)==0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    if(ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR || OS_MBUF_PKTLEN(ctxt->om)!=32)return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    s_auth_ready=false;memset(s_auth_proof,0,sizeof(s_auth_proof));
    uint8_t message[128];const char *prefix="PCFLASH1\n" DISPLAY_DEVICE_ID "\n";
    size_t n=strlen(prefix);if(n+32>sizeof(message))return BLE_ATT_ERR_UNLIKELY;
    memcpy(message,prefix,n);ble_hs_mbuf_to_flat(ctxt->om,message+n,32,NULL);
    psa_key_attributes_t attributes=PSA_KEY_ATTRIBUTES_INIT;psa_key_id_t key=0;
    psa_set_key_usage_flags(&attributes,PSA_KEY_USAGE_SIGN_MESSAGE);
    psa_set_key_algorithm(&attributes,PSA_ALG_HMAC(PSA_ALG_SHA_256));
    psa_set_key_type(&attributes,PSA_KEY_TYPE_HMAC);
    psa_status_t result=psa_import_key(&attributes,(const uint8_t *)DISPLAY_TOKEN,strlen(DISPLAY_TOKEN),&key);
    psa_reset_key_attributes(&attributes);size_t length=0;
    if(result==PSA_SUCCESS) {
        result=psa_mac_compute(key,PSA_ALG_HMAC(PSA_ALG_SHA_256),message,n+32,s_auth_proof,32,&length);
        psa_destroy_key(key);
    }
    s_auth_ready=result==PSA_SUCCESS && length==32; // gitleaks:allow (boolean result, no credential)
    return s_auth_ready ? 0 : BLE_ATT_ERR_UNLIKELY;
}

static void notify_status(void) {
    if (s_conn == BLE_HS_CONN_HANDLE_NONE || !s_status_handle) return;
    uint8_t buf[4] = {(uint8_t)atomic_load(&s_state), (uint8_t)atomic_load(&s_progress),
                      (uint8_t)atomic_load(&s_err), 0};
    struct os_mbuf *om = ble_hs_mbuf_from_flat(buf, sizeof(buf));
    if (!om) return;
    ble_gatts_notify_custom(s_conn, s_status_handle, om);
}

static int ctrl_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *) {
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len < 1) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;

    uint8_t cmd = 0;
    ble_hs_mbuf_to_flat(ctxt->om, &cmd, 1, NULL);

    if (cmd < 1 || cmd > 4 || len > 512 || (cmd == 1 && len != 37) ||
        (cmd == 2 && len < 2) || (cmd >= 3 && len != 1)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    chunk_t c = {0}; c.cmd = cmd; c.generation = atomic_load(&s_generation);
    uint8_t raw[513];
    ble_hs_mbuf_to_flat(ctxt->om, raw, len, NULL);
    c.len = cmd == 1 ? len : len - 1;
    memcpy(c.data, raw + (cmd == 1 ? 0 : 1), c.len);
    // Never acknowledge data that did not enter the writer's ordered queue.
    if (xQueueSend(s_queue, &c, 0) != pdTRUE) return BLE_ATT_ERR_INSUFFICIENT_RES;
    return 0;
}

static int stat_access(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *) {
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint8_t buf[4] = {(uint8_t)atomic_load(&s_state), (uint8_t)atomic_load(&s_progress),
                      (uint8_t)atomic_load(&s_err), 0};
    int rc = os_mbuf_append(ctxt->om, buf, sizeof(buf));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static const struct ble_gatt_svc_def GATT_SVCS[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &SVC_UUID.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid = &CTRL_UUID.u,
                .access_cb = ctrl_access,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP |
                         BLE_GATT_CHR_F_NOTIFY,
            },
            {
                .uuid = &STAT_UUID.u,
                .access_cb = stat_access,
                .val_handle = &s_status_handle,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
            },
            { .uuid=&INFO_UUID.u, .access_cb=info_access, .flags=BLE_GATT_CHR_F_READ },
            { .uuid=&AUTH_UUID.u, .access_cb=auth_access, .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE },
            { .uuid=&DIAG_UUID.u, .access_cb=diag_access, .flags=BLE_GATT_CHR_F_READ },
            {0},
        },
    },
    {0},
};

// ---------------------------------------------------------------------------
// GAP
// ---------------------------------------------------------------------------
static uint8_t own_addr_type;

static int gap_event(struct ble_gap_event *event, void *) {
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_conn = event->connect.conn_handle;
            ESP_LOGI(TAG, "connected");
            // MTU 由手机端发起交换（Android requestMtu / iOS 自动协商），
            // 外设侧只被动接受。这里调用 ble_gattc_exchange_mtu 需要 central
            // 角色支持，本固件为省内存已关闭 central，故不主动请求。
        } else {
            advertise();
        }
        return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "disconnected reason=%d", event->disconnect.reason);
        s_conn = BLE_HS_CONN_HANDLE_NONE;
        s_auth_ready=false;memset(s_auth_proof,0,sizeof(s_auth_proof));
        // 连接断了但传输没完成：不能继续写，必须回滚，否则槽位被半包固件占着。
        ble_ota_cancel();
        advertise();
        return 0;
    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "mtu=%d", event->mtu.value);
        return 0;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        advertise();
        return 0;
    default:
        return 0;
    }
}

static void advertise(void) {
    struct ble_hs_adv_fields fields = {};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;

    // 名字里带版本能让手机端一眼看出板子跑的是哪版，省去连上再问。
    static char name[32];
    const esp_app_desc_t *desc = esp_app_get_description();
    snprintf(name, sizeof(name), "PhoneCtl-%.12s", desc->version);
    fields.uuids128 = (ble_uuid128_t *)&SVC_UUID;
    fields.num_uuids128 = 1; fields.uuids128_is_complete = 1;
    struct ble_hs_adv_fields response = {0};
    response.name = (uint8_t *)name; response.name_len = strlen(name); response.name_is_complete = 1;
    ble_gap_adv_rsp_set_fields(&response);

    int rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) { ESP_LOGE(TAG, "adv_set_fields rc=%d", rc); return; }

    struct ble_gap_adv_params params = {};
    params.conn_mode = BLE_GAP_CONN_MODE_UND;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    rc = ble_gap_adv_start(own_addr_type, NULL, BLE_HS_FOREVER,
                           &params, gap_event, NULL);
    if (rc != 0) ESP_LOGE(TAG, "adv_start rc=%d", rc);
}

static void on_sync(void) {
    if (ble_hs_util_ensure_addr(0) != 0) { ESP_LOGE(TAG, "ensure_addr failed"); return; }
    ble_hs_id_infer_auto(0, &own_addr_type);
    advertise();
}

static void on_reset(int reason) {
    ESP_LOGW(TAG, "host reset reason=%d", reason);
    s_conn = BLE_HS_CONN_HANDLE_NONE;
    ble_ota_cancel();
}

static void host_task(void *) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}

// ---------------------------------------------------------------------------
// 对外
// ---------------------------------------------------------------------------
int ble_ota_start(void) {
    static bool started = false;
    if (started) return 0;
    started = true;
    uint8_t nonce[16];esp_fill_random(nonce,sizeof(nonce));hex_string(nonce,sizeof(nonce),s_boot_nonce);

    s_queue = xQueueCreate(48, sizeof(chunk_t));
    if (!s_queue) return -1;
    xTaskCreate(writer_task, "ble_ota_w", 6144, NULL, 5, NULL);

    esp_err_t e = nimble_port_init();
    if (e != ESP_OK) { ESP_LOGE(TAG, "nimble_port_init: %s", esp_err_to_name(e)); return -1; }

    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.reset_cb = on_reset;

    ble_svc_gap_init();
    ble_svc_gatt_init();
    int rc = ble_gatts_count_cfg(GATT_SVCS);
    if (rc != 0) return rc;
    rc = ble_gatts_add_svcs(GATT_SVCS);
    if (rc != 0) return rc;
    ble_svc_gap_device_name_set("PhoneCtl");

    nimble_port_freertos_init(host_task);
    ESP_LOGI(TAG, "BLE OTA ready");
    return 0;
}

void ble_ota_status(ble_ota_state_t *state, uint8_t *progress, uint8_t *err) {
    if (state) *state = (ble_ota_state_t)atomic_load(&s_state);
    if (progress) *progress = (uint8_t)atomic_load(&s_progress);
    if (err) *err = (uint8_t)atomic_load(&s_err);
}

bool ble_ota_busy(void) { return atomic_load(&s_busy); }

void ble_ota_cancel(void) { controller_ota_cancel_ticket(&s_generation); }
