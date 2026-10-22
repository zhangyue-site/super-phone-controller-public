#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
void controller_usb_start(void);
void controller_usb_service(void);
void controller_usb_request_mode(bool enabled);
bool controller_usb_hid_enabled(void);
size_t controller_usb_read(uint8_t *data, size_t size);
void controller_usb_write(const char *text);
void controller_usb_prepare_reset(bool download);
void controller_release(void);
bool controller_usb_ready(void);

bool controller_usb_mouse(int dx,int dy,bool click);
bool controller_usb_phone_key(bool home);

// One-shot AI Home request; true means a USB press/release report was submitted, not observed UI success.
bool controller_usb_ai_home(bool (*live)(unsigned),unsigned sequence);

#include "hid_pointer_policy.h"
bool controller_usb_ai_pointer(const controller::PointerCommand& command,bool (*live)(unsigned),unsigned sequence);
