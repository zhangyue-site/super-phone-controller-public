#include "ota.h"
#include "ble_ota.h"
#include "device_config.h"
#include "usb.h"
#include "voice.h"
#include "adb_local.h"
#include "nvs.h"
#include "esp_ota_ops.h"
#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "psa/crypto.h"
#include <atomic>
#include <cstdio>
#include <cstring>
static std::atomic<bool> busy(false),cancelled(false);
static std::atomic<int> stage(0),progress(0);
bool controller_ota_busy(){return busy;}
int controller_ota_stage(){return stage;}
int controller_ota_progress(){return progress;}
static void set_stage(int value){stage=value;controller_ota_changed();}
void controller_ota_cancel(){cancelled=true;}
static esp_http_client_handle_t open_url(const char *path){
 char url[256],auth[128];snprintf(url,sizeof(url),"%s%s",controller_ota_endpoint(),path);
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=15000;cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;cfg.buffer_size=4096;
 auto c=esp_http_client_init(&cfg);if(!c)return nullptr;
 esp_http_client_set_header(c,"Host","erweima.zhangyue.site");esp_http_client_set_header(c,"Authorization",auth);
 if(esp_http_client_open(c,0)!=ESP_OK){esp_http_client_cleanup(c);return nullptr;}
 esp_http_client_fetch_headers(c);return c;
}
static void close_url(esp_http_client_handle_t c){if(c){esp_http_client_close(c);esp_http_client_cleanup(c);}}
static bool phone_ready(){
 if(controller_adb_network_available())return true;
 return controller_adb_activate(controller_adb_ticket());
}
static bool report(const char *phase){
 char url[256],auth[128],body[256];
 snprintf(url,sizeof(url),"%s/firmware/report",controller_ota_endpoint());
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 const auto *p=esp_ota_get_running_partition();esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
 esp_ota_get_state_partition(p,&state);
 snprintf(body,sizeof(body),"{\"version\":\"%s\",\"slot\":\"%s\",\"phase\":\"%s\",\"imageState\":%d}",esp_app_get_description()->version,p->label,phase,(int)state);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=15000;cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;
 auto c=esp_http_client_init(&cfg);if(!c)return false;
 esp_http_client_set_header(c,"Authorization",auth);esp_http_client_set_header(c,"Host","erweima.zhangyue.site");
 esp_http_client_set_header(c,"Content-Type","application/json");esp_http_client_set_method(c,HTTP_METHOD_POST);
 esp_http_client_set_post_field(c,body,strlen(body));auto err=esp_http_client_perform(c);int status=esp_http_client_get_status_code(c);
 esp_http_client_cleanup(c);ESP_LOGI("ota","Report phase=%s status=%d",phase,status);return err==ESP_OK&&status==200;
}
static void pending_report(bool value){
 nvs_handle_t n;if(nvs_open("ota",NVS_READWRITE,&n)==ESP_OK){nvs_set_u8(n,"report",value);nvs_commit(n);nvs_close(n);}
}
static void report_boot(void*){
 for(int i=0;i<3;++i){
  if(phone_ready()&&report("boot-confirmed")){pending_report(false);break;}
  vTaskDelay(pdMS_TO_TICKS(5000));
 }
 vTaskDelete(nullptr);
}
static void worker(void*){
 // A local update request authorizes connecting the existing fixed phone tunnel.
 phone_ready();

 esp_ota_handle_t handle=0;bool writing=false;auto c=open_url("/firmware/manifest");
 unsigned size=0;char expected[65]={},version[32]={},manifest[256]={};bool ok=false;
 do{
  if(!c||esp_http_client_get_status_code(c)!=200)break;
  int length=(int)esp_http_client_get_content_length(c);
  if(length<1||length>=sizeof(manifest))break;
  int got=esp_http_client_read_response(c,manifest,length);
  if(got!=length||sscanf(manifest,"PCOTA1\n%u\n%64[0-9a-f]\n%31s",&size,expected,version)!=3||strlen(expected)!=64)break;
  close_url(c);c=nullptr;
  const auto *partition=esp_ota_get_next_update_partition(nullptr);
  if(!partition||size<1024||size>partition->size||cancelled)break;
  if(!strcmp(version,esp_app_get_description()->version)){set_stage(4);ok=true;break;}
  char path[160];snprintf(path,sizeof(path),"/firmware/image?sha=%s",expected);
  c=open_url(path);
  if(!c||esp_http_client_get_status_code(c)!=200||esp_http_client_get_content_length(c)!=size)break;
  if(esp_ota_begin(partition,size,&handle)!=ESP_OK)break;
  writing=true;set_stage(2);
  psa_crypto_init();psa_hash_operation_t hash=PSA_HASH_OPERATION_INIT;
  if(psa_hash_setup(&hash,PSA_ALG_SHA_256)!=PSA_SUCCESS)break;
  unsigned received=0;unsigned char buffer[4096];int64_t deadline=esp_timer_get_time()+300000000;
  while(received<size&&!cancelled&&esp_timer_get_time()<deadline){
   int n=esp_http_client_read(c,(char*)buffer,(size-received)>sizeof(buffer)?sizeof(buffer):size-received);
   if(n<=0||psa_hash_update(&hash,buffer,n)!=PSA_SUCCESS||esp_ota_write(handle,buffer,n)!=ESP_OK)break;
   received+=n;int previous=progress.exchange(received*100/size);
   if(previous/10!=progress.load()/10)controller_ota_changed();
  }
  unsigned char digest[32];size_t digest_size=0;char actual[65]={};
  bool hashed=psa_hash_finish(&hash,digest,sizeof(digest),&digest_size)==PSA_SUCCESS;psa_hash_abort(&hash);
  if(hashed)for(int i=0;i<32;++i)snprintf(actual+i*2,3,"%02x",digest[i]);
  if(received!=size||cancelled||!hashed||digest_size!=32||strcmp(actual,expected))break;
  auto result=esp_ota_end(handle);writing=false;
  if(result!=ESP_OK){ESP_LOGE("ota","esp_ota_end: %s",esp_err_to_name(result));break;}
  esp_app_desc_t desc={};
  auto desc_err=esp_ota_get_partition_description(partition,&desc);
  ESP_LOGI("ota","Candidate version=%s expected=%s project=%s desc=%s",desc.version,version,desc.project_name,esp_err_to_name(desc_err));
  if(desc_err!=ESP_OK||strcmp(desc.version,version)||strcmp(desc.project_name,"phone_controller_epaper"))break;
  if(cancelled)break;
  auto boot_err=esp_ota_set_boot_partition(partition);
  ESP_LOGI("ota","Select boot partition: %s",esp_err_to_name(boot_err));
  if(boot_err!=ESP_OK)break;
  pending_report(true);
  set_stage(3);ok=true;ESP_LOGI("ota","Verified version=%s bytes=%u slot=%s",version,size,partition->label);
 }while(false);
 close_url(c);if(writing)esp_ota_abort(handle);
 if(!ok){report("failed");set_stage(5);ESP_LOGW("ota","Update failed/cancelled; active partition retained");}
 if(stage==3){vTaskDelay(pdMS_TO_TICKS(1500));esp_restart();}
 if(stage==4)report("current");
 busy=false;vTaskDelete(nullptr);
}
void controller_ota_start(){
 if(ble_ota_busy()||busy.exchange(true))return;
 cancelled=false;progress=0;set_stage(1);controller_voice_cancel();controller_usb_request_mode(false);controller_release();
 if(xTaskCreate(worker,"ota",12288,nullptr,3,nullptr)!=pdPASS){busy=false;set_stage(5);}
}
void controller_ota_confirm(){
 static bool reported=false;
 esp_ota_img_states_t state;auto p=esp_ota_get_running_partition();
 if(esp_ota_get_state_partition(p,&state)==ESP_OK&&state==ESP_OTA_IMG_PENDING_VERIFY){
  auto err=esp_ota_mark_app_valid_cancel_rollback();if(err==ESP_OK)pending_report(true);ESP_LOGI("ota","Boot confirmed slot=%s result=%s",p->label,esp_err_to_name(err));
 }
 if(!reported){
  reported=true;nvs_handle_t n;uint8_t pending=0;
  if(nvs_open("ota",NVS_READONLY,&n)==ESP_OK){nvs_get_u8(n,"report",&pending);nvs_close(n);}
  if(pending)xTaskCreate(report_boot,"ota_boot_report",8192,nullptr,2,nullptr);
 }
}
