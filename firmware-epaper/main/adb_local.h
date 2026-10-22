#pragma once
#include <stdint.h>
void controller_adb_init();
bool controller_adb_activate(uint32_t consent);
void controller_adb_cancel();
int controller_adb_stage();
uint32_t controller_adb_ticket();

int controller_adb_error();

bool controller_adb_network_available();

#include "adb_command.h"
bool controller_adb_execute(const controller::AdbCommand &command,const char *expected,char *output,unsigned capacity,uint32_t ticket,const char **error=nullptr);
