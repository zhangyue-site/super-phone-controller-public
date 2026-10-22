#pragma once
#include <stdint.h>

namespace controller {
// Deliberately no NVS/RTC state: each startup must ask again.
constexpr bool hid_on_boot() { return false; }
constexpr bool wifi_on_boot() { return false; }
constexpr bool can_confirm(int64_t visible_at, int64_t press_at, int64_t now,
                           bool same_screen = true) {
    return same_screen && visible_at > 0 && press_at >= visible_at &&
           now >= press_at && now - press_at >= 2000 &&
           now - visible_at < 15000;
}
}
