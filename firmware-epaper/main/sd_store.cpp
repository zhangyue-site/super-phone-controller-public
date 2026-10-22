#include "sd_store.h"
#include "diagnostics.h"
#include "storage_policy.h"
#include "usb.h"
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"
#include "driver/sdmmc_host.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_random.h"
#include "mbedtls/version.h"
#if MBEDTLS_VERSION_MAJOR >= 4
#include "psa/crypto.h"
#else
#include "mbedtls/sha256.h"
#endif
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <atomic>
#include <stdlib.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#if __has_include("device_skill_cache.h")
#include "device_skill_cache.h"
#define HAVE_SKILL_CACHE 1
#endif
static const char *DIR="/sdcard/SPASSIST",*LOG="/sdcard/SPASSIST/DIAG.LOG",*OLD="/sdcard/SPASSIST/DIAG.OLD";
static std::atomic<bool> mounted(false),logging(false),skill_cached(false);
static uint64_t total=0,free_bytes=0;
static SemaphoreHandle_t lock;
static bool append(const char *line){
 struct stat st={};
 if(stat(LOG,&st)==0 && controller::rotate_log(st.st_size,strlen(line))){
  if(remove(OLD)!=0 && errno!=ENOENT)return false;
  if(rename(LOG,OLD)!=0)return false;
 }
 FILE *f=fopen(LOG,"a");if(!f)return false;
 bool ok=fputs(line,f)>=0 && fflush(f)==0;
 if(ok)ok=fsync(fileno(f))==0;
 if(fclose(f)!=0)ok=false;
 return ok;
}
static bool append_event(const char *line){
 const char *path="/sdcard/SPASSIST/EVENTS.LOG",*old="/sdcard/SPASSIST/EVENTS.OLD";
 struct stat st={};
 if(stat(path,&st)==0&&st.st_size+(long)strlen(line)>65536){
  if(remove(old)!=0&&errno!=ENOENT)return false;
  if(rename(path,old)!=0)return false;
 }
 FILE *f=fopen(path,"a");if(!f)return false;
 bool ok=fputs(line,f)>=0&&fflush(f)==0;
 if(ok)ok=fsync(fileno(f))==0;
 if(fclose(f)!=0)ok=false;
 return ok;
}
static bool verify_skill(const char *path,const char *expected){
 FILE *f=fopen(path,"rb");if(!f)return false;
#if MBEDTLS_VERSION_MAJOR >= 4
 psa_hash_operation_t ctx=PSA_HASH_OPERATION_INIT;
 bool ok=psa_crypto_init()==PSA_SUCCESS&&psa_hash_setup(&ctx,PSA_ALG_SHA_256)==PSA_SUCCESS;
#else
 mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);bool ok=mbedtls_sha256_starts(&ctx,0)==0;
#endif
 unsigned char buffer[256],digest[32];size_t total=0,n;
 while(ok && (n=fread(buffer,1,sizeof(buffer),f))){total+=n;if(total>32768){ok=false;break;}
#if MBEDTLS_VERSION_MAJOR >= 4
 ok=psa_hash_update(&ctx,buffer,n)==PSA_SUCCESS;
#else
 ok=mbedtls_sha256_update(&ctx,buffer,n)==0;
#endif
}
 if(ferror(f))ok=false;
 fclose(f);
#if MBEDTLS_VERSION_MAJOR >= 4
 size_t digest_size=0;
 if(ok)ok=psa_hash_finish(&ctx,digest,sizeof(digest),&digest_size)==PSA_SUCCESS&&digest_size==32;
 psa_hash_abort(&ctx);
#else
 if(ok)ok=mbedtls_sha256_finish(&ctx,digest)==0;
 mbedtls_sha256_free(&ctx);
#endif
 if(!ok)return false;
 char hex[65];for(int i=0;i<32;++i)snprintf(hex+i*2,3,"%02x",digest[i]);
 return strcmp(hex,expected)==0;
}
static void cache_skill(){
#if HAVE_SKILL_CACHE
 const char *path="/sdcard/SPASSIST/CLOUD.MD";
 struct stat st={};
 if(stat(path,&st)==0){skill_cached=verify_skill(path,cached_skill_sha);ESP_LOGI("storage","Existing cloud snapshot preserved; current bundle match=%d",skill_cached.load());return;}
 FILE *f=fopen("/sdcard/SPASSIST/CLOUD.TMP","wb");if(!f)return;
 bool ok=fwrite(cached_skill,1,sizeof(cached_skill)-1,f)==sizeof(cached_skill)-1;
 if(ok)ok=fflush(f)==0 && fsync(fileno(f))==0;
 if(fclose(f)!=0)ok=false;
 if(!ok || rename("/sdcard/SPASSIST/CLOUD.TMP",path)!=0)return;
 f=fopen("/sdcard/SPASSIST/CLOUD.JSN","w");if(!f)return;
 ok=fprintf(f,"{\"schema\":1,\"skill\":\"cardputer-phone\",\"sha256\":\"%s\",\"source\":\"106-cloud\",\"mode\":\"reference-only\",\"transportVerified\":false}\n",cached_skill_sha)>0;
 if(ok)ok=fflush(f)==0 && fsync(fileno(f))==0;
 if(fclose(f)!=0)ok=false;
 skill_cached=ok && verify_skill(path,cached_skill_sha);
 ESP_LOGI("storage","Cloud skill snapshot cached as reference; not executable");
#endif
}
static void run(void*){
 esp_vfs_fat_sdmmc_mount_config_t config={};config.format_if_mount_failed=false;config.max_files=3;config.allocation_unit_size=16384;
 sdmmc_host_t host=SDMMC_HOST_DEFAULT();host.max_freq_khz=SDMMC_FREQ_DEFAULT;
 sdmmc_slot_config_t slot=SDMMC_SLOT_CONFIG_DEFAULT();slot.width=1;
 slot.clk=GPIO_NUM_39;slot.cmd=GPIO_NUM_41;slot.d0=GPIO_NUM_40;slot.flags|=SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
 sdmmc_card_t *card=nullptr;
 esp_err_t error=esp_vfs_fat_sdmmc_mount("/sdcard",&host,&slot,&config,&card);
 if(error!=ESP_OK){ESP_LOGW("storage","TF unavailable: %s; no formatting attempted",esp_err_to_name(error));vTaskDelete(nullptr);return;}
 esp_vfs_fat_info("/sdcard",&total,&free_bytes);
 mounted=true;
 ESP_LOGI("storage","TF mounted: total=%llu MiB free=%llu MiB",total/1048576,free_bytes/1048576);
 if(free_bytes<1048576 || (mkdir(DIR,0700)!=0 && errno!=EEXIST)){
  ESP_LOGW("storage","TF logging disabled: insufficient space or directory unavailable");vTaskDelete(nullptr);return;
 }
 cache_skill();logging=true;
 uint32_t last_event_seq=0;
 uint32_t boot=esp_random();char last[384]={};int64_t last_saved=-15000;
 for(;;){
  char state[384]={};controller_diagnostic_state(state,sizeof(state));int64_t now=esp_timer_get_time()/1000;
  if(strcmp(last,state)!=0 || now-last_saved>=15000){
   char line[512];snprintf(line,sizeof(line),"{\"schema\":1,\"boot\":\"%08lx\",\"reset\":%d,\"uptimeMs\":%lld,\"state\":%s}\n",(unsigned long)boot,esp_reset_reason(),(long long)now,state);
   xSemaphoreTake(lock,portMAX_DELAY);bool ok=append(line);xSemaphoreGive(lock);
   if(!ok){logging=false;ESP_LOGW("storage","TF write failed; in-memory diagnostics remain available");vTaskDelete(nullptr);return;}
   snprintf(last,sizeof(last),"%s",state);last_saved=now;
  }
  char event_buffer[4097];controller_events_snapshot(event_buffer,sizeof(event_buffer));
  char *cursor=event_buffer;
  while(*cursor){
   char *end=strchr(cursor,'\n');if(!end)break;
   char *field=strstr(cursor,"\"seq\":");
   if(field&&field<end){
    unsigned seq=strtoul(field+6,nullptr,10);
    if(seq>last_event_seq){
     char saved=end[1];end[1]=0;xSemaphoreTake(lock,portMAX_DELAY);bool ok=append_event(cursor);xSemaphoreGive(lock);end[1]=saved;
     if(!ok){ESP_LOGW("storage","TF operation log write failed");break;}
     last_event_seq=seq;
    }
   }
   cursor=end+1;
  }
  vTaskDelay(pdMS_TO_TICKS(1000));
 }
}
void controller_storage_start(){lock=xSemaphoreCreateMutex();if(lock)xTaskCreate(run,"tf_diagnostics",10240,nullptr,1,nullptr);}
void controller_storage_status(){
 char out[160];snprintf(out,sizeof(out),"STORAGE tf=%d logging=%d total_mib=%llu free_mib=%llu skill_written=%d\r\n",mounted.load(),logging.load(),total/1048576,free_bytes/1048576,skill_cached.load());controller_usb_write(out);
}
void controller_storage_dump(){
 if(!mounted || !lock){controller_usb_write("TF unavailable; use LOGS for memory diagnostics\r\n");return;}
 xSemaphoreTake(lock,portMAX_DELAY);
 FILE *f=fopen(LOG,"r");
 if(f){
  fseek(f,0,SEEK_END);long end=ftell(f);
  if(end>16384){fseek(f,end-16384,SEEK_SET);int c;while((c=fgetc(f))!=EOF&&c!='\n'){};}else rewind(f);
  controller_usb_write("--- TF DIAGNOSTICS BEGIN ---\r\n");char buffer[256];size_t remaining=16384;
  while(remaining){size_t n=fread(buffer,1,remaining<255?remaining:255,f);if(!n)break;buffer[n]=0;controller_usb_write(buffer);remaining-=n;}
  fclose(f);controller_usb_write("\r\n--- TF DIAGNOSTICS END ---\r\n");
 }else controller_usb_write("No persisted diagnostics yet\r\n");
 xSemaphoreGive(lock);
}

void controller_storage_events_dump(){
 if(!mounted||!lock){controller_usb_write("TF unavailable\r\n");return;}
 xSemaphoreTake(lock,portMAX_DELAY);
 FILE *f=fopen("/sdcard/SPASSIST/EVENTS.LOG","r");
 if(f){
  fseek(f,0,SEEK_END);long end=ftell(f);
  if(end>8192){fseek(f,end-8192,SEEK_SET);int c;while((c=fgetc(f))!=EOF&&c!='\n'){};}else rewind(f);
  controller_usb_write("--- EVENTS TF BEGIN ---\r\n");
  char line[256];while(fgets(line,sizeof(line),f))controller_usb_write(line);
  fclose(f);controller_usb_write("--- EVENTS TF END ---\r\n");
 }else controller_usb_write("No persisted operation events\r\n");
 xSemaphoreGive(lock);
}
