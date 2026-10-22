#include "board.h"
#include "led.h"
#include "link.h"

#include "driver/gpio.h"
#include "driver/i2s_pdm.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "phone-hand";
static i2s_chan_handle_t mic;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static void mic_open(void)
{
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&channel, NULL, &mic));

    i2s_pdm_rx_config_t config = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(BOARD_MIC_RATE_HZ),
        .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .clk = BOARD_MIC_CLK_GPIO,
            .din = BOARD_MIC_DATA_GPIO,
            .invert_flags = {
                .clk_inv = false,
            },
        },
    };
    config.slot_cfg.slot_mask = I2S_PDM_SLOT_LEFT;
    ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(mic, &config));
    ESP_ERROR_CHECK(i2s_channel_enable(mic));
}

void app_main(void)
{
    gpio_config_t button = {
        .pin_bit_mask = 1ULL << BOARD_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&button));
    led_start();
    mic_open();
    link_start();
    ESP_LOGI(TAG, "AtomS3U ready. Hold the button to record. USB only.");

    bool stable = gpio_get_level(BOARD_BUTTON_GPIO) == 0;
    bool raw = stable;
    int64_t raw_at = now_ms();

    while (true) {
        bool pressed = gpio_get_level(BOARD_BUTTON_GPIO) == 0;
        int64_t t = now_ms();
        if (pressed != raw) {
            raw = pressed;
            raw_at = t;
        }
        if (raw != stable && t - raw_at >= 40) {
            stable = raw;
            if (stable) {
                led_listen();
                ESP_LOGI(TAG, "recording");
            } else {
                led_await_reply();
                ESP_LOGI(TAG, "recording ended, waiting for reply");
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
