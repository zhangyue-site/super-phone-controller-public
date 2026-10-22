#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"

// Diagnostic firmware: no display refresh, TinyUSB, WiFi, credentials or NVS writes.
void app_main(void) {
    gpio_config_t power={.pin_bit_mask=1ULL<<17,.mode=GPIO_MODE_OUTPUT};
    ESP_ERROR_CHECK(gpio_config(&power));
    gpio_set_level(GPIO_NUM_17,1);
    gpio_config_t button={.pin_bit_mask=1ULL<<18,.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&button));
    ESP_LOGI("recovery","Native USB recovery started. Screen is intentionally unchanged.");
    int64_t pressed_at=0,next_log=0;
    bool latched=false;
    for(;;){
        int64_t now=esp_timer_get_time()/1000;
        if(gpio_get_level(GPIO_NUM_18)==0){
            if(!pressed_at)pressed_at=now;
            if(!latched&&now-pressed_at>=1500){
                latched=true;
                ESP_LOGI("recovery","PWR: battery power latch disabled. USB can still supply power.");
                gpio_set_level(GPIO_NUM_17,0);
            }
        }else pressed_at=0;
        if(now>=next_log){ESP_LOGI("recovery","alive uptime_ms=%lld",now);next_log=now+3000;}
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
