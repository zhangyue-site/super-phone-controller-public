#include "led.h"

#include "board.h"

#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_check.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct {
    rmt_encoder_t base;
    rmt_encoder_t *bytes;
    rmt_encoder_t *copy;
    int state;
    rmt_symbol_word_t reset;
} led_encoder_t;

static led_encoder_t encoder;
static rmt_channel_handle_t channel;

typedef enum {
    LED_MODE_OFF = 0,
    LED_MODE_PLUGGED,
    LED_MODE_WIFI,
    LED_MODE_READY,
    LED_MODE_AWAIT,
    LED_MODE_LISTEN,
    LED_MODE_SKILL,
    LED_MODE_SKILL_OTHER,
    LED_MODE_FAIL,
} led_mode_t;

static volatile led_mode_t mode = LED_MODE_OFF;
static volatile int64_t mode_at;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static size_t encode_pixel(rmt_encoder_t *base, rmt_channel_handle_t tx, const void *data,
                           size_t data_size, rmt_encode_state_t *ret_state)
{
    led_encoder_t *led = __containerof(base, led_encoder_t, base);
    rmt_encode_state_t session = RMT_ENCODING_RESET;
    rmt_encode_state_t state = RMT_ENCODING_RESET;
    size_t encoded = 0;

    if (led->state == 0) {
        encoded += led->bytes->encode(led->bytes, tx, data, data_size, &session);
        if (session & RMT_ENCODING_COMPLETE) {
            led->state = 1;
        }
        if (session & RMT_ENCODING_MEM_FULL) {
            state |= RMT_ENCODING_MEM_FULL;
            *ret_state = state;
            return encoded;
        }
    }
    if (led->state == 1) {
        encoded += led->copy->encode(led->copy, tx, &led->reset, sizeof(led->reset), &session);
        if (session & RMT_ENCODING_COMPLETE) {
            led->state = 0;
            state |= RMT_ENCODING_COMPLETE;
        }
        if (session & RMT_ENCODING_MEM_FULL) {
            state |= RMT_ENCODING_MEM_FULL;
        }
    }
    *ret_state = state;
    return encoded;
}

static esp_err_t reset_encoder(rmt_encoder_t *base)
{
    led_encoder_t *led = __containerof(base, led_encoder_t, base);
    led->state = 0;
    rmt_encoder_reset(led->bytes);
    rmt_encoder_reset(led->copy);
    return ESP_OK;
}

static esp_err_t delete_encoder(rmt_encoder_t *base)
{
    led_encoder_t *led = __containerof(base, led_encoder_t, base);
    rmt_del_encoder(led->bytes);
    rmt_del_encoder(led->copy);
    return ESP_OK;
}

static void paint(uint8_t green, uint8_t red, uint8_t blue)
{
    uint8_t pixel[3] = {green, red, blue};
    rmt_transmit_config_t tx = {0};
    encoder.state = 0;
    rmt_encoder_reset(&encoder.base);
    ESP_ERROR_CHECK(rmt_transmit(channel, &encoder.base, pixel, sizeof(pixel), &tx));
    ESP_ERROR_CHECK(rmt_tx_wait_all_done(channel, 20));
}

static void set_mode(led_mode_t next)
{
    mode = next;
    mode_at = now_ms();
}

static void led_task(void *arg)
{
    (void)arg;
    while (true) {
        int64_t elapsed = now_ms() - mode_at;
        uint8_t green = 0;
        uint8_t red = 0;
        uint8_t blue = 0;

        if (mode == LED_MODE_PLUGGED) {
            red = 48;
            green = 48;
            blue = 48;
        } else if (mode == LED_MODE_WIFI) {
            bool on = elapsed < 400 || ((elapsed / 250) % 2) == 0;
            if (on) {
                red = 24;
                green = 24;
                blue = 24;
            }
        } else if (mode == LED_MODE_READY) {
            if (elapsed < 5000) {
                green = 32;
            } else {
                set_mode(LED_MODE_PLUGGED);
            }
        } else if (mode == LED_MODE_AWAIT) {
            red = 28;
            green = 22;
        } else if (mode == LED_MODE_LISTEN) {
            if (((elapsed / 140) % 2) == 0) {
                green = 24;
                blue = 24;
            }
        } else if (mode == LED_MODE_SKILL) {
            blue = 32;
        } else if (mode == LED_MODE_SKILL_OTHER) {
            red = 22;
            blue = 28;
        } else if (mode == LED_MODE_FAIL) {
            if (elapsed >= 1200) {
                set_mode(LED_MODE_PLUGGED);
            } else if (((elapsed / 200) % 2) == 0) {
                red = 32;
            }
        }

        paint(green, red, blue);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void led_start(void)
{
    rmt_tx_channel_config_t config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = BOARD_LED_GPIO,
        .mem_block_symbols = 64,
        .resolution_hz = 10 * 1000 * 1000,
        .trans_queue_depth = 4,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&config, &channel));

    rmt_bytes_encoder_config_t bytes = {
        .bit0 = {.duration0 = 4, .level0 = 1, .duration1 = 8, .level1 = 0},
        .bit1 = {.duration0 = 8, .level0 = 1, .duration1 = 4, .level1 = 0},
        .flags.msb_first = 1,
    };
    ESP_ERROR_CHECK(rmt_new_bytes_encoder(&bytes, &encoder.bytes));
    rmt_copy_encoder_config_t copy = {};
    ESP_ERROR_CHECK(rmt_new_copy_encoder(&copy, &encoder.copy));
    encoder.reset.duration0 = 2800;
    encoder.reset.level0 = 0;
    encoder.reset.duration1 = 0;
    encoder.reset.level1 = 0;
    encoder.base.encode = encode_pixel;
    encoder.base.reset = reset_encoder;
    encoder.base.del = delete_encoder;
    ESP_ERROR_CHECK(rmt_enable(channel));
    set_mode(LED_MODE_PLUGGED);
    paint(48, 48, 48);
    xTaskCreate(led_task, "led", 3072, NULL, 4, NULL);
}

void led_plugged(void)
{
    set_mode(LED_MODE_PLUGGED);
}

void led_wifi_read(void)
{
    set_mode(LED_MODE_WIFI);
}

void led_session_ready(void)
{
    set_mode(LED_MODE_READY);
}

void led_await_reply(void)
{
    set_mode(LED_MODE_AWAIT);
}

void led_listen(void)
{
    set_mode(LED_MODE_LISTEN);
}

void led_skill(void)
{
    set_mode(LED_MODE_SKILL);
}

void led_skill_other(void)
{
    set_mode(LED_MODE_SKILL_OTHER);
}

void led_fail(void)
{
    set_mode(LED_MODE_FAIL);
}

void led_off(void)
{
    set_mode(LED_MODE_OFF);
}
