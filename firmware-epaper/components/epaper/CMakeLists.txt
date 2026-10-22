idf_component_register(SRCS "epaper_driver_bsp.cpp" INCLUDE_DIRS "."
    REQUIRES esp_timer driver esp_psram
    PRIV_REQUIRES esp_driver_spi esp_driver_gpio)
