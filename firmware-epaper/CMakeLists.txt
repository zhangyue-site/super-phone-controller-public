cmake_minimum_required(VERSION 3.16)

# PROJECT_VER 必须在 project() 之前定好：ESP-IDF 会把它写进
# esp_app_desc_t.version，OTA 服务端就是靠这个字段判断有没有新版本。
#
# 坑：project() 的 VERSION 参数只接受数字点分形式，"2026.10.21-ci12" 会让它
# 解析失败并静默回落成 "1"，设备于是永远认为已是最新。所以这里干脆不给
# project() 传 VERSION，只设 PROJECT_VER 变量，让 IDF 原样写进描述符。
if(NOT DEFINED PROJECT_VER OR PROJECT_VER STREQUAL "")
    set(PROJECT_VER "0.0.1")
endif()
set(PROJECT_VER "${PROJECT_VER}" CACHE STRING "Firmware version" FORCE)
message(STATUS "PhoneCtl firmware version: ${PROJECT_VER}")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(phone_controller_epaper)
