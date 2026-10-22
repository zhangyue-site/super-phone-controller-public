#pragma once
#include "driver/i2c_master.h"
i2c_master_bus_handle_t controller_i2c_bus();
bool controller_touch_init();
// -1: missing/error, 0: released, 1: exactly one finger. Coordinates are screen pixels.
int controller_touch_read(int &x,int &y);
