#pragma once

#include "driver/gpio.h"

/* M5Stack AtomS3U. ESP32-S3FN8, 8MB flash, no PSRAM.
 * USB-A plug, one front button, PDM mic, RGB LED. No speaker and no screen.
 */

#define BOARD_BUTTON_GPIO      GPIO_NUM_41
#define BOARD_MIC_CLK_GPIO     GPIO_NUM_38
#define BOARD_MIC_DATA_GPIO    GPIO_NUM_39
#define BOARD_LED_GPIO         GPIO_NUM_35
#define BOARD_IR_GPIO          GPIO_NUM_12
#define BOARD_GROVE_SDA_GPIO   GPIO_NUM_2
#define BOARD_GROVE_SCL_GPIO   GPIO_NUM_1

#define BOARD_HOLD_MS          800
#define BOARD_MIC_RATE_HZ      16000
