#pragma once
#include <stdbool.h>
#include <stdint.h>
void controller_usb_net_init();
void controller_usb_net_attach();
void controller_usb_net_mac_string(char *out);
void controller_usb_net_begin_detach();
void controller_usb_net_detach();
void controller_usb_net_link(bool up);
void controller_usb_net_service();
bool controller_usb_net_has_ip();
int controller_usb_net_stage();
void controller_usb_net_backend(bool ready);
void controller_usb_net_counters(uint32_t *rx,uint32_t *tx);
// Called from event/task context. Must only update application state.
void controller_net_changed();

uint32_t controller_usb_net_peer();
