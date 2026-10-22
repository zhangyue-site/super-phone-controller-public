#pragma once
bool controller_ota_busy();
int controller_ota_stage();
int controller_ota_progress();
void controller_ota_start();
void controller_ota_cancel();
void controller_ota_confirm();
const char *controller_ota_endpoint();

void controller_ota_changed();
