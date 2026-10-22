#pragma once
void controller_logs_start();
void controller_logs_dump();

#include <stddef.h>
void controller_event(const char *event,int page,int a=0,int b=0,int result=0);
size_t controller_events_snapshot(char *out,size_t capacity);
