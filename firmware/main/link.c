#include "link.h"

#include "led.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "link";

static void handle_line(char *line)
{
    size_t len = strlen(line);
    while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        line[--len] = '\0';
    }
    if (strncmp(line, "WIFI\t", 5) == 0) {
        ESP_LOGI(TAG, "usb only, wifi command ignored");
        return;
    }
    if (strcmp(line, "SKILL") == 0) {
        led_skill();
        ESP_LOGI(TAG, "skill");
        return;
    }
    if (strcmp(line, "SKILL2") == 0) {
        led_skill_other();
        ESP_LOGI(TAG, "skill other");
        return;
    }
    if (strcmp(line, "WAIT") == 0) {
        led_await_reply();
        return;
    }
    if (strcmp(line, "LISTEN") == 0) {
        led_listen();
        return;
    }
    if (strcmp(line, "FAIL") == 0) {
        led_fail();
        return;
    }
    if (strcmp(line, "END") == 0) {
        led_plugged();
    }
}

static void serial_task(void *arg)
{
    (void)arg;
    char line[128];
    while (true) {
        if (!fgets(line, sizeof(line), stdin)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        handle_line(line);
    }
}

void link_start(void)
{
    ESP_LOGI(TAG, "usb only");
    xTaskCreate(serial_task, "serial", 4096, NULL, 5, NULL);
}
