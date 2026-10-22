#include "diagnostics.h"
#include "log_ring.h"
#include "usb.h"
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

static controller::LogRing<4096> logs;
static portMUX_TYPE log_mux=portMUX_INITIALIZER_UNLOCKED;
static int capture(const char *format,va_list args){
 char line[384];int total=vsnprintf(line,sizeof(line),format,args);
 if(total>0){
  size_t size=(size_t)total<sizeof(line)?(size_t)total:sizeof(line)-1;
  taskENTER_CRITICAL(&log_mux);logs.append(line,size);taskEXIT_CRITICAL(&log_mux);
 }
 return total;
}
void controller_logs_start(){esp_log_set_vprintf(capture);}
void controller_logs_dump(){
 static char snapshot[4097];
 taskENTER_CRITICAL(&log_mux);logs.snapshot(snapshot,sizeof(snapshot));taskEXIT_CRITICAL(&log_mux);
 controller_usb_write("--- LOGS BEGIN ---\r\n");
 controller_usb_write(snapshot);
 controller_usb_write("\r\n--- LOGS END ---\r\n");
}

static controller::LogRing<4096> events;
static uint32_t boot_id=0,event_seq=0;
void controller_event(const char *event,int page,int a,int b,int result){
 char line[192];
 taskENTER_CRITICAL(&log_mux);
 if(!boot_id)boot_id=esp_random();
 unsigned seq=++event_seq;
 int n=snprintf(line,sizeof(line),"{\"boot\":%u,\"seq\":%u,\"ms\":%lld,\"event\":\"%s\",\"page\":%d,\"a\":%d,\"b\":%d,\"result\":%d}\n",(unsigned)boot_id,seq,(long long)(esp_timer_get_time()/1000),event,page,a,b,result);
 if(n>0&&n<(int)sizeof(line))events.append(line,n);
 taskEXIT_CRITICAL(&log_mux);
}
size_t controller_events_snapshot(char *out,size_t capacity){
 taskENTER_CRITICAL(&log_mux);size_t n=events.snapshot(out,capacity);taskEXIT_CRITICAL(&log_mux);
 // The ring may begin in the middle of an old record.
 if(n&&out[0]!='{'){
  char *start=strchr(out,'\n');
  if(!start){out[0]=0;return 0;}
  size_t skip=start+1-out;n-=skip;memmove(out,out+skip,n+1);
 }
 return n;
}
