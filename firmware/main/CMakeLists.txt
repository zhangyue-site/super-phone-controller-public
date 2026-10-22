idf_component_register(SRCS "main.c" "led.c" "link.c" INCLUDE_DIRS "."
                       REQUIRES driver esp_timer)
