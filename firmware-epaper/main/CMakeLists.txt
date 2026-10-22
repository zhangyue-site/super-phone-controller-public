set(CONTROLLER_JSON json)
if(IDF_VERSION_MAJOR GREATER_EQUAL 6)
 set(CONTROLLER_JSON espressif__cjson)
endif()
idf_component_register(SRCS "main.cpp" "dialogue.cpp" "ota.cpp" "ble_ota.c" "gesture.cpp" "usb.cpp" "diagnostics.cpp" "usb_network.cpp" "voice.cpp" "adb_local.cpp" "touch.cpp" "sd_store.cpp" INCLUDE_DIRS "."
 EMBED_FILES "audio/ready.pcm" "audio/recognized.pcm" "audio/failed.pcm" "audio/stopped.pcm" "audio/test.pcm"
 REQUIRES ${CONTROLLER_JSON} app_update esp_driver_gpio fatfs sdmmc esp_driver_sdmmc esp_codec_dev esp_driver_i2s esp_driver_i2c lwip epaper driver usb esp_hw_support esp_wifi esp_event esp_netif nvs_flash esp_http_client esp-tls mbedtls bt esp_timer esp_psram)