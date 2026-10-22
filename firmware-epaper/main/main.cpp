#include <stdio.h>
#include <string.h>
#include <time.h>
#include <atomic>
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_psram.h"
#include "esp_sntp.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "epaper_driver_bsp.h"
#include "usb.h"
#include "device_config.h"
#include "boot_screen.h"
#include "mode_screens.h"
#include "mode_consent.h"
#include "diagnostics.h"
#include "usb_network.h"
#include "network_screens.h"
#include "ui_assets.h"
#include "voice.h"
#include "audio_feedback.h"
#include "adb_local.h"
#include "voice_screens.h"
#include "preflight.h"
#include "preparation_screens.h"
#include "touch.h"
#include "touch_ui.h"
#include "touch_screens.h"
#include "button_gesture.h"
#include "sd_store.h"
#include "ota.h"
#include "ble_ota.h"
#include "gesture.h"
#include "interaction_screens.h"
#include "esp_ota_ops.h"
#include "esp_app_desc.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

static const char *TAG="controller";
static std::atomic<bool> online(false), stopped(false), stop_pending(false);
static std::atomic<unsigned> stop_sequence(0);
#if CONFIG_TINYUSB_NET_MODE_NCM
static const int HOME_PAGE=5;
#else
static const int HOME_PAGE=4;
#endif
static std::atomic<int> page(HOME_PAGE);
static std::atomic<int64_t> consent_visible_at(0);
static std::atomic<unsigned> screen_epoch(1), painted_epoch(0);
static std::atomic<bool> painted_hid(false), screen_failed(false), screen_dirty(false), screen_painting(true);
static TaskHandle_t screen_task_handle;
static uint8_t panel_frame[5000];
static bool panel_frame_valid=false;
static portMUX_TYPE consent_mux=portMUX_INITIALIZER_UNLOCKED;
static void go_page(int target){
 taskENTER_CRITICAL(&consent_mux);
 consent_visible_at=0;screen_epoch.fetch_add(1);page=target;
 controller_event("page",target);
 taskEXIT_CRITICAL(&consent_mux);
 screen_dirty=true;if(screen_task_handle)xTaskNotifyGive(screen_task_handle);
}
void controller_ota_changed(){screen_dirty=true;if(screen_task_handle)xTaskNotifyGive(screen_task_handle);}

static char ssid[33],password[65];
static int network_slot=0,retries=0;
static std::atomic<bool> wifi_enabled(false);
static bool wifi_initialized=false,sntp_started=false;
static std::atomic<int> check_server(controller::WAIT),check_chat(controller::WAIT),check_asr(controller::WAIT);
static std::atomic<bool> wifi_connected(false);
#if CONFIG_TINYUSB_NET_MODE_NCM
static const int PAGE_COUNT=5;
#else
static const int PAGE_COUNT=4;
#endif
void controller_net_changed(){online=wifi_connected.load()||controller_usb_net_has_ip()||controller_adb_network_available();screen_dirty=true;}
void controller_usb_disconnected(){
 controller_adb_cancel();controller_voice_cancel();stop_pending=true;
 taskENTER_CRITICAL(&consent_mux);
 controller_usb_request_mode(false);controller_release();go_page(HOME_PAGE);
 taskEXIT_CRITICAL(&consent_mux);
}


static bool load_wifi(int slot){
 nvs_handle_t h;
 if(nvs_open("wifi",NVS_READONLY,&h)!=ESP_OK)return false;
 char skey[16],pkey[16];
 if(slot==0){strcpy(skey,"ssid");strcpy(pkey,"password");}
 else {snprintf(skey,sizeof(skey),"ssid%d",slot);snprintf(pkey,sizeof(pkey),"password%d",slot);}
 size_t n=sizeof(ssid),p=sizeof(password);
 esp_err_t err=nvs_get_str(h,skey,ssid,&n);
 password[0]=0;nvs_get_str(h,pkey,password,&p);nvs_close(h);
 return err==ESP_OK && ssid[0];
}
static void connect_saved(){
 if(!load_wifi(network_slot)){network_slot=0;if(!load_wifi(0)){ESP_LOGW(TAG,"No saved WiFi; configure using USB WIFI command");return;}}
 wifi_config_t cfg={};
 memcpy(cfg.sta.ssid,ssid,strlen(ssid));memcpy(cfg.sta.password,password,strlen(password));
 cfg.sta.pmf_cfg.capable=true;
 ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&cfg));
 esp_wifi_connect();
}
static void wifi_event(void*,esp_event_base_t base,int32_t id,void*){
 if(!wifi_enabled){wifi_connected=false;online=controller_usb_net_has_ip();return;}
 if(base==IP_EVENT && id==IP_EVENT_STA_GOT_IP){wifi_connected=true;online=true;retries=0;ESP_LOGI(TAG,"WiFi connected");if(screen_task_handle)xTaskNotifyGive(screen_task_handle);}
 else if(base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED){wifi_connected=false;online=controller_usb_net_has_ip(); if(++retries>=3){retries=0;network_slot=(network_slot+1)%10;connect_saved();}else esp_wifi_connect();}
 else if(base==WIFI_EVENT && id==WIFI_EVENT_STA_START)connect_saved();
}
static void wifi_start(){
 if(wifi_enabled.exchange(true))return;
 if(wifi_initialized){esp_wifi_start();return;}
 esp_netif_create_default_wifi_sta();wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
 ESP_ERROR_CHECK(esp_wifi_init(&init));
 ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
 ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,nullptr));
 ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,nullptr));
 ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_start());
 wifi_initialized=true;
}
static const char *server_endpoint(){
#if CONFIG_CONTROLLER_USB_LOCAL
 if(controller_adb_network_available())return "https://127.0.0.1:18843/phone-controller";
#endif
 return DISPLAY_ENDPOINT;
}
const char *controller_ota_endpoint(){
 if(controller_adb_network_available())return "https://127.0.0.1:18843/phone-controller";
 if(!wifi_connected && controller_usb_net_peer())return "https://192.168.77.2:18843/phone-controller";
 return DISPLAY_ENDPOINT;
}
static bool request(const char *path,uint8_t *out){
 char url[256],auth[128];snprintf(url,sizeof(url),"%s%s",server_endpoint(),path);
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=8000;
 cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.buffer_size=2048;cfg.disable_auto_redirect=true;
 esp_http_client_handle_t client=esp_http_client_init(&cfg);if(!client)return false;
 esp_http_client_set_header(client,"Authorization",auth);
 esp_http_client_set_header(client,"Host","erweima.zhangyue.site");
 if(!out){
  esp_http_client_set_method(client,HTTP_METHOD_POST);
  char seq[16];snprintf(seq,sizeof(seq),"%u",controller_voice_cancel_sequence());
  esp_http_client_set_header(client,"X-Voice-Session",controller_voice_session());esp_http_client_set_header(client,"X-Voice-Sequence",seq);
 }
 esp_err_t err=esp_http_client_open(client,0);
 int total=0,status=0;
 if(err==ESP_OK){
  int64_t length=esp_http_client_fetch_headers(client);
  status=esp_http_client_get_status_code(client);
  if(out && status==200 && length==5000){
   while(total<5000){int n=esp_http_client_read(client,(char*)out+total,5000-total);if(n<=0)break;total+=n;}
  }
 }
 esp_http_client_close(client);esp_http_client_cleanup(client);
 bool ok=err==ESP_OK && status==200 && (!out || total==5000);
 controller_usb_net_backend(ok);
 if(!ok)ESP_LOGW(TAG,"Display request failed status=%d bytes=%d error=%s",status,total,esp_err_to_name(err));
 return ok;
}
// Operation telemetry is separate from free-form ESP logs/user content.
static void upload_events(){
 if(controller_ota_busy())return;
 if(controller_voice_conversing() || controller_voice_stage()==10 || controller_voice_stage()==11)return;
 if(!online || controller_voice_stage()==1 || controller_voice_stage()==2 || controller_voice_stage()==4 || controller_voice_stage()==7)return;
 static char body[4097];size_t size=controller_events_snapshot(body,sizeof(body));if(!size)return;
 char url[256],auth[128];snprintf(url,sizeof(url),"%s/events",server_endpoint());snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=5000;cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;
 esp_http_client_handle_t client=esp_http_client_init(&cfg);if(!client)return;
 esp_http_client_set_header(client,"Authorization",auth);esp_http_client_set_header(client,"Host","erweima.zhangyue.site");
 esp_http_client_set_header(client,"Content-Type","application/x-ndjson");esp_http_client_set_method(client,HTTP_METHOD_POST);
 esp_http_client_set_post_field(client,body,size);
 esp_err_t err=esp_http_client_perform(client);int status=esp_http_client_get_status_code(client);
 esp_http_client_cleanup(client);
 ESP_LOGI(TAG,"Operation log upload status=%d ok=%d",status,err==ESP_OK&&status==200);
}
static bool paint(epaper_driver_display &display,const uint8_t *frame,bool full){
 for(int y=0;y<200;y++)for(int x=0;x<200;x++)
  display.EPD_DrawColorPixel(x,y,frame[y*25+x/8]&(0x80>>(x%8))?255:0);
 if(full){display.EPD_Init();display.EPD_DisplayPartBaseImage();display.EPD_Init_Partial();}
 else display.EPD_DisplayPart();
 return display.healthy();
}
// Clock uses UTC+8 explicitly; never display a fabricated time before SNTP sync.
[[maybe_unused]] static void draw_footer(uint8_t *frame,int mode){
 memset(frame+176*25,255,24*25);
 time_t utc=time(nullptr);
 if(utc>=1704067200){
  time_t china=utc+8*3600;struct tm local={};gmtime_r(&china,&local);
  char stamp[20];strftime(stamp,sizeof(stamp),"%Y-%m-%d %H:%M",&local);
  for(unsigned i=0;stamp[i];++i){
   const char *alphabet="0123456789-: ";
   const char *found=strchr(alphabet,stamp[i]);
   unsigned glyph=found?found-alphabet:12;
   for(int y=0;y<12;++y)frame[(176+y)*25+1+i]=clock_glyphs[glyph][y];
  }
 }else memcpy(frame+176*25,clock_unknown,300);
 memcpy(frame+188*25,mode==2?check_hint:mode==1?voice_hint:footer_hint,300); // Two full twelve-row lines fit below the controls.
}
bool controller_voice_online(){return online.load()&&!stop_pending.load();}
static uint8_t dialogue_frame[5000];
static std::atomic<bool> dialogue_frame_valid(false);
static portMUX_TYPE dialogue_mux=portMUX_INITIALIZER_UNLOCKED;
void controller_dialogue_screen(const unsigned char *frame){
 taskENTER_CRITICAL(&dialogue_mux);
 dialogue_frame_valid=frame!=nullptr;
 if(frame)memcpy(dialogue_frame,frame,5000);
 taskEXIT_CRITICAL(&dialogue_mux);screen_dirty=true;
}
static bool dialogue_copy(uint8_t *frame){
 taskENTER_CRITICAL(&dialogue_mux);bool valid=dialogue_frame_valid;if(valid)memcpy(frame,dialogue_frame,5000);taskEXIT_CRITICAL(&dialogue_mux);return valid;
}
void controller_voice_changed(bool completed){
 // Local completion feedback avoids another TLS round-trip for a 5000-byte screen.
 if(completed)ESP_LOGI(TAG,"Voice recognized; local result shown without fetching task bitmap");
 screen_dirty=true;
}
bool controller_voice_upload(const unsigned char *pcm,unsigned size,unsigned sequence){
 char url[256],auth[128];snprintf(url,sizeof(url),"%s/voice",server_endpoint());
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=80000;
 cfg.common_name="erweima.zhangyue.site";cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;
 auto client=esp_http_client_init(&cfg);if(!client)return false;
 esp_http_client_set_header(client,"Authorization",auth);esp_http_client_set_header(client,"Host","erweima.zhangyue.site");
 char seq[16];snprintf(seq,sizeof(seq),"%u",sequence);
 esp_http_client_set_header(client,"X-Voice-Session",controller_voice_session());esp_http_client_set_header(client,"X-Voice-Sequence",seq);
 esp_http_client_set_header(client,"Content-Type","application/octet-stream");esp_http_client_set_header(client,"X-Voice-Dialogue","1");esp_http_client_set_method(client,HTTP_METHOD_POST);
 esp_err_t err=esp_http_client_open(client,size);unsigned sent=0;
 if(err==ESP_OK){
  while(sent<size){int n=esp_http_client_write(client,(const char*)pcm+sent,size-sent);if(n<=0)break;sent+=n;}
 }
 int status=0;if(sent==size && esp_http_client_fetch_headers(client)>=0)status=esp_http_client_get_status_code(client);
 esp_http_client_close(client);esp_http_client_cleanup(client);
 ESP_LOGI(TAG,"Voice upload bytes=%u status=%d",sent,status);return status==200;
}
bool controller_voice_stream_upload(VoiceStream &stream){
 char url[256],auth[128],seq[16];snprintf(url,sizeof(url),"%s/voice/stream",server_endpoint());
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);snprintf(seq,sizeof(seq),"%u",stream.sequence);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=15000;cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;
 auto client=esp_http_client_init(&cfg);if(!client)return false;
 esp_http_client_set_header(client,"Authorization",auth);esp_http_client_set_header(client,"Host","erweima.zhangyue.site");
 esp_http_client_set_header(client,"X-Voice-Session",controller_voice_session());esp_http_client_set_header(client,"X-Voice-Sequence",seq);
 esp_http_client_set_header(client,"Content-Type","application/octet-stream");esp_http_client_set_header(client,"X-Voice-Dialogue","1");esp_http_client_set_method(client,HTTP_METHOD_POST);
 int64_t began=esp_timer_get_time(),first=0;bool ok=esp_http_client_open(client,-1)==ESP_OK;unsigned sent=0;
 auto write=[&](const char *p,unsigned n){return !stream.abort&&esp_http_client_write(client,p,n)==(int)n;};
 while(ok&&!stream.abort){
  unsigned available=stream.bytes.load();
  if(available>sent&&(available-sent>=3200||stream.done)){
   unsigned size=available-sent;if(size>3200)size=3200;char header[16];int n=snprintf(header,sizeof(header),"%x\r\n",size);
   ok=write(header,n)&&write((const char*)stream.pcm+sent,size)&&write("\r\n",2);
   if(ok){sent+=size;if(!first)first=esp_timer_get_time();}
  }else if(stream.done&&available==sent)break;
  else vTaskDelay(pdMS_TO_TICKS(10));
 }
 ok=ok&&!stream.abort&&sent>=12800;
 if(ok)ok=write("0\r\n\r\n",5);
 int status=0;
 if(ok){esp_http_client_set_timeout_ms(client,80000);if(esp_http_client_fetch_headers(client)>=0)status=esp_http_client_get_status_code(client);}
 esp_http_client_close(client);esp_http_client_cleanup(client);
 ESP_LOGI(TAG,"Voice stream bytes=%u first_ms=%lld total_ms=%lld status=%d",sent,(long long)(first?(first-began)/1000:-1),(long long)((esp_timer_get_time()-began)/1000),status);
 controller_event("upload",page.load(),first?(first-began)/1000:-1,stream.finished_at?(esp_timer_get_time()-stream.finished_at)/1000:-1,status);
 return ok&&status==200&&!stream.abort;
}
bool controller_preflight_probe(){
 if(!online)return false;
 check_server=controller::RUN;check_chat=check_asr=controller::WAIT;screen_dirty=true;
 char url[256],auth[128];snprintf(url,sizeof(url),"%s/checks.bin",server_endpoint());
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.timeout_ms=120000;cfg.common_name="erweima.zhangyue.site";
 cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.disable_auto_redirect=true;
 auto client=esp_http_client_init(&cfg);if(!client){check_server=controller::FAILED;return false;}
 esp_http_client_set_header(client,"Authorization",auth);esp_http_client_set_header(client,"Host","erweima.zhangyue.site");
 esp_http_client_set_method(client,HTTP_METHOD_POST);
 char flags[3]={};int size=0;bool ok=esp_http_client_open(client,0)==ESP_OK;
 if(ok && esp_http_client_fetch_headers(client)==3 && esp_http_client_get_status_code(client)==200){
  while(size<3){int n=esp_http_client_read(client,flags+size,3-size);if(n<=0)break;size+=n;}
 }
 esp_http_client_close(client);esp_http_client_cleanup(client);
 ok=size==3;for(int i=0;i<3;++i)ok=ok&&(flags[i]=='1'||flags[i]=='2');
 check_server=ok?(flags[0]=='1'?controller::DONE:controller::FAILED):controller::FAILED;
 check_chat=ok?(flags[1]=='1'?controller::DONE:controller::FAILED):controller::WAIT;
 check_asr=ok?(flags[2]=='1'?controller::DONE:controller::FAILED):controller::WAIT;
 screen_dirty=true;return ok && flags[0]=='1' && flags[1]=='1' && flags[2]=='1';
}
static auto current_preflight(){
 controller::PreflightInput input={controller_usb_ready(),controller_usb_net_peer()!=0,controller_adb_stage(),
  controller_usb_net_has_ip()||controller_adb_network_available(),(controller::CheckStatus)check_server.load(),(controller::CheckStatus)check_chat.load(),(controller::CheckStatus)check_asr.load()};
 return controller::preflight(input);
}
bool controller_voice_prepared(){return online && current_preflight()[7]==controller::DONE;}
static void preparation(uint8_t *frame){
 int adb_error=controller_adb_error();
 if(adb_error>0&&adb_error<8){memcpy(frame,interaction_adb_error[adb_error],5000);return;}
 auto rows=current_preflight();memset(frame,255,5000);
 int step=0;while(step<7 && rows[step]==controller::DONE)++step;
 // The tiny display shows one actual current step at readable size, not eight small rows.
 memcpy(frame,preparation_base,31*25);
 if(rows[7]==controller::DONE)memcpy(frame,assistant_online,sizeof(assistant_online));
 memcpy(frame+44*25,focus_titles[step],sizeof(focus_titles[step]));
 memcpy(frame+82*25,focus_status[rows[step]],sizeof(focus_status[0]));
 memcpy(frame+122*25,focus_hints[step],sizeof(focus_hints[step]));
}
void controller_diagnostic_state(char *out,unsigned size){
 snprintf(out,size,"{\"usb\":%d,\"peer\":%d,\"adb\":%d,\"adbError\":%d,\"net\":%d,\"online\":%d,\"server\":%d,\"chat\":%d,\"asr\":%d,\"hid\":%d,\"wifi\":%d,\"page\":%d,\"voice\":%d,\"screenError\":%d}",
 controller_usb_ready(),controller_usb_net_peer()!=0,controller_adb_stage(),controller_adb_error(),controller_usb_net_stage(),online.load(),check_server.load(),check_chat.load(),check_asr.load(),controller_usb_hid_enabled(),wifi_enabled.load(),page.load(),controller_voice_stage(),screen_failed.load());
}
extern "C" void controller_ble_diagnostic_state(char *out,unsigned size){controller_diagnostic_state(out,size);}
static uint8_t cached_screens[2][5000];
static bool cached_valid[2]={false,false};
static portMUX_TYPE cache_mux=portMUX_INITIALIZER_UNLOCKED;
static void telemetry_task(void*){
 auto *fresh=(uint8_t*)malloc(5000);
 for(;;){
  if(!controller_ota_busy()&&controller_voice_background_http_begin()){
   if(online && stop_pending.exchange(false) && !request("/stop",nullptr))stop_pending=true;
   int selected=page.load();
   if(online&&fresh&&(selected==0||selected==1)){
    char path[48];snprintf(path,sizeof(path),"/screen.bin?page=%d",selected);
    if(request(path,fresh)){
     taskENTER_CRITICAL(&cache_mux);memcpy(cached_screens[selected],fresh,5000);cached_valid[selected]=true;taskEXIT_CRITICAL(&cache_mux);
     if(page==selected)controller_ota_changed();
    }
   }
   upload_events();
   controller_voice_background_http_end();
  }
  vTaskDelay(pdMS_TO_TICKS(5000));
 }
}
static void screen_task(void*){
 custom_lcd_spi_t pins={11,10,9,8,13,12,SPI3_HOST,5000};
 epaper_driver_display display(200,200,pins);
 uint8_t frame[5000],previous[5000];memset(previous,0,sizeof(previous));
 int refreshes=0;unsigned previous_epoch=0;
 for(;;){
  const unsigned epoch=screen_epoch.load();
  const int current_page=page.load();
  const bool hid=controller_usb_hid_enabled();
  bool success=false;
  ble_ota_state_t ble_state;uint8_t ble_progress,ble_error;
  ble_ota_status(&ble_state,&ble_progress,&ble_error);
  if(ble_ota_busy()||ble_state==BLE_OTA_READY){
   memcpy(frame,interaction_ble[(int)ble_state],5000);
   for(int y=143;y<151;++y)for(int x=8;x<192;++x)
    if(y==143||y==150||x==8||x==191||x<8+184*ble_progress/100)frame[y*25+x/8]&=~(0x80>>(x%8));
  }else if(current_page==HOME_PAGE+5){
   memcpy(frame,interaction_ota[controller_ota_stage()],5000);
  }else if(current_page==HOME_PAGE){
   int status=stopped?3:controller_voice_prepared()?2:online?1:0;
   memcpy(frame,interaction_home[status],5000);
  }else if(current_page==HOME_PAGE+1){
   memcpy(frame,interaction_manual[0],5000);
  }else if(current_page==HOME_PAGE+2){
   memcpy(frame,interaction_manual[1],5000);
  }else if(current_page==HOME_PAGE+3){
   memcpy(frame,interaction_manual[2],5000);
  }else if(current_page==HOME_PAGE+4){
   memcpy(frame,interaction_manual[3],5000);
  }else if(current_page==HOME_PAGE+6){
   memcpy(frame,interaction_sound[(controller_audio_muted()?6:0)+controller_audio_volume()/20],5000);
  }else if(current_page==2){
   memcpy(frame,hid?mode_enabled_screen:mode_disabled_screen,5000);
  }else if(current_page==PAGE_COUNT-1){
   int voice=controller_voice_stage();
   bool result_shown=(voice==11||voice==3||voice==5)&&dialogue_copy(frame);
   if(!result_shown){
#if CONFIG_CONTROLLER_USB_LOCAL
   if((voice>=7&&voice<=9) || voice==0 || voice==6){if(controller_voice_prepared())memcpy(frame,interaction_voice[0],5000);else preparation(frame);}
   else memcpy(frame,interaction_voice[(voice>=0&&voice<12)?voice:5],5000);
#else
   memcpy(frame,interaction_voice[(voice>=0&&voice<12)?voice:5],5000);
#endif
   }
  }else if(current_page==3){
   int stage=controller_usb_net_stage();memcpy(frame,stage?network_screens[stage-1]:boot_screen,5000);
  }else{
   int selected=current_page==1?1:0;
   taskENTER_CRITICAL(&cache_mux);
   success=cached_valid[selected];if(success)memcpy(frame,cached_screens[selected],5000);
   taskEXIT_CRITICAL(&cache_mux);
   if(!success)memcpy(frame,selected?loading_screen_1:loading_screen_0,5000);
  }
  memcpy(frame+162*25,interaction_footer,sizeof(interaction_footer));
  if(current_page==HOME_PAGE+5&&controller_ota_stage()==2){
   // Progress is local, drawn without any network round-trip.
   memset(frame+29*25,255,12*25);int percent=controller_ota_progress();
   for(int y=31;y<39;++y)for(int x=8;x<192;++x)
    if(y==31||y==38||x==8||x==191||x<8+184*percent/100)frame[y*25+x/8]&=~(0x80>>(x%8));
  }
  memset(frame+188*25,255,12*25); // Keep tiny build metadata off the 1.54-inch display.
  if(epoch!=screen_epoch.load() || current_page!=page.load())continue;
  if(memcmp(frame,previous,5000) || previous_epoch!=epoch){
   screen_painting=true;
   if(!paint(display,frame,refreshes++%20==0)){
    consent_visible_at=0;screen_failed=true;
    ESP_LOGE(TAG,"Screen disabled after driver fault; USB recovery remains available");
    esp_ota_img_states_t state;auto running=esp_ota_get_running_partition();
    if(esp_ota_get_state_partition(running,&state)==ESP_OK&&state==ESP_OTA_IMG_PENDING_VERIFY)esp_ota_mark_app_invalid_rollback_and_reboot();
    vTaskSuspend(nullptr);
   }
   memcpy(previous,frame,5000);previous_epoch=epoch;
   taskENTER_CRITICAL(&consent_mux);
   if(epoch==screen_epoch.load() && current_page==page.load()){
    painted_epoch=epoch;memcpy(panel_frame,frame,5000);panel_frame_valid=true;
   }
   if(current_page==2 && epoch==screen_epoch.load() && page==2){
    painted_hid=hid;painted_epoch=epoch;
    consent_visible_at=esp_timer_get_time()/1000;
   }
   taskEXIT_CRITICAL(&consent_mux);
   screen_painting=false;
   controller_ota_confirm();
   ESP_LOGI(TAG,"Screen updated page=%d",current_page);controller_event("page",current_page,0,0,1);
  }
  ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(5000));
 }
}
static void stop_now(){
 stop_sequence.fetch_add(1);
 controller_event("stop",page.load());
 taskENTER_CRITICAL(&consent_mux);
 ble_ota_cancel();controller_ota_cancel();controller_adb_cancel();controller_voice_cancel();controller_audio_interrupt();stopped=true;stop_pending=true;controller_release();controller_usb_request_mode(false);go_page(1);
 taskEXIT_CRITICAL(&consent_mux);
 if(screen_task_handle)xTaskNotifyGive(screen_task_handle);
 ESP_LOGI(TAG,"Local stop latched; no actuator enabled");
}
static void touch_action(controller::TouchTarget target,int64_t began,int64_t now){
 using controller::TouchTarget;
 controller_event("action",page.load(),(int)target);
 switch(target){
 case TouchTarget::SOUND_SETTINGS:go_page(HOME_PAGE+6);break;
 case TouchTarget::VOLUME_DOWN:controller_audio_adjust(-20);controller_ota_changed();break;
 case TouchTarget::VOLUME_UP:controller_audio_adjust(20);controller_ota_changed();break;
 case TouchTarget::MUTE:controller_audio_toggle_mute();controller_ota_changed();break;
 case TouchTarget::SOUND_TEST:controller_audio_prompt(controller::SpeechPrompt::TEST);break;
 case TouchTarget::UPDATE:controller_ota_start();screen_dirty=true;break;
 case TouchTarget::START:
  if(controller_voice_conversing()){stop_now();go_page(HOME_PAGE);break;}
  go_page(PAGE_COUNT-1);
  stopped=false;controller_voice_conversation();
  break;
 case TouchTarget::HOME:controller_voice_cancel();go_page(HOME_PAGE);break;
 case TouchTarget::QUOTA:go_page(0);break;
 case TouchTarget::CONTROL:go_page(controller_usb_hid_enabled()?HOME_PAGE+1:2);break;
 case TouchTarget::PHONE_HOME:case TouchTarget::PHONE_BACK:{
  if(!controller_usb_hid_enabled()){go_page(2);break;}
  bool ok=controller_usb_phone_key(target==TouchTarget::PHONE_HOME);
  controller_event("action",page.load(),(int)target,1,ok?1:0);break;
 }
 case TouchTarget::UP:case TouchTarget::DOWN:case TouchTarget::LEFT:case TouchTarget::RIGHT:case TouchTarget::CLICK:{
  if(!controller_usb_hid_enabled()){go_page(2);break;}
  bool ok=controller_usb_mouse(target==TouchTarget::LEFT?-24:target==TouchTarget::RIGHT?24:0,
    target==TouchTarget::UP?-24:target==TouchTarget::DOWN?24:0,target==TouchTarget::CLICK);
  controller_event("mouse",page.load(),(int)target,0,ok?1:0);break;
 }
 case TouchTarget::STOP:stop_now();go_page(HOME_PAGE);break;
 case TouchTarget::CONFIRM:{
  taskENTER_CRITICAL(&consent_mux);
  bool same=page==2 && painted_epoch.load()==screen_epoch.load() &&
            painted_hid.load()==controller_usb_hid_enabled() && !screen_failed;
  if(controller::can_confirm(consent_visible_at.load(),began,now,same)){
   bool enable=!painted_hid.load();controller_usb_request_mode(enable);go_page(enable?HOME_PAGE+1:HOME_PAGE);
  }
  taskEXIT_CRITICAL(&consent_mux);break;
 }
 default:break;
 }
}
static void input_task(void*){
 controller::TouchGesture gesture;controller::TouchContact contact_state;int touch_page=-1;
 controller::ButtonGesture side_key;controller::ControlButton control_key;controller::GestureDetector swipes;
 controller::DebouncedButton voice_debounce,power_debounce,external_control_debounce;
 controller::PressFeedback voice_press,power_press,external_press;
 unsigned swipe_epoch=0;bool swipe_contact=false;
 bool touch_voicing=false,key_voicing=false;unsigned touch_voice_epoch=0;
 bool updating=false;
 controller::PowerOffHold power_off;controller::StopReleaseGate stop_gate;unsigned seen_stop=stop_sequence.load();
 for(;;){
  int64_t now=esp_timer_get_time()/1000;
  bool voice_raw=gpio_get_level(GPIO_NUM_0)==0,external_control_raw=false;
#if CONFIG_CONTROLLER_EXTERNAL_KEYS
  voice_raw=voice_raw||gpio_get_level(GPIO_NUM_1)==0;
  external_control_raw=gpio_get_level(GPIO_NUM_2)==0;
#endif
  bool down=voice_debounce.update(voice_raw,now);
  bool power_down=power_debounce.update(gpio_get_level(GPIO_NUM_18)==0,now);
  bool external_control_down=external_control_debounce.update(external_control_raw,now);
  bool control_down=power_down||external_control_down;
  bool voice_pressed=voice_press.update(down),power_pressed=power_press.update(power_down),external_pressed=external_press.update(external_control_down);
  if(voice_pressed||power_pressed||external_pressed)controller_audio_prompt(controller::SpeechPrompt::CLICK);
  int tx=0,ty=0;int contact=controller_touch_read(tx,ty);auto edge=contact_state.update(contact);
  auto target=contact==1?controller::touch_target(page.load(),tx,ty,HOME_PAGE):controller::TouchTarget::NONE;
  if(edge==controller::TouchEdge::DOWN)controller_event("touch_down",page.load(),tx,ty,(int)target);
  if(edge==controller::TouchEdge::UP)controller_event("touch_up",page.load(),(int)(now-gesture.began),(int)gesture.target,screen_failed?3:screen_painting?2:0);
  // Stop is acted on at contact-down, including during display refresh and OTA.
  if(page==PAGE_COUNT-1&&contact==1)target=controller::voice_touch_target(tx,ty,controller_voice_stage(),controller_voice_conversing(),dialogue_frame_valid.load());
  if(edge==controller::TouchEdge::DOWN&&target!=controller::TouchTarget::STOP)controller_audio_prompt(controller::SpeechPrompt::CLICK);
  if(edge==controller::TouchEdge::DOWN&&target==controller::TouchTarget::STOP){
   stop_now();go_page(HOME_PAGE);touch_voicing=key_voicing=false;gesture.cancel();swipes.reset();
  }
  if(edge==controller::TouchEdge::DOWN&&target==controller::TouchTarget::FINISH){
   bool accepted=controller_voice_finish();controller_event("voice_finish",page.load(),0,0,accepted?1:0);
   gesture.cancel();swipes.reset();swipe_contact=false;
   vTaskDelay(pdMS_TO_TICKS(20));continue;
  }
  auto control_event=control_key.update(control_down,now);
  bool ota_busy=controller_ota_busy()||ble_ota_busy();
  if(control_event==controller::ControlEvent::STOP){
   stop_now();go_page(HOME_PAGE);touch_voicing=key_voicing=false;gesture.cancel();swipes.reset();
  }else if(control_event==controller::ControlEvent::MUTE){
   controller_audio_toggle_mute();
   if(!ota_busy&&!touch_voicing&&!key_voicing)go_page(HOME_PAGE+6);else controller_ota_changed();
  }else if(control_event==controller::ControlEvent::HOME&&!ota_busy){
   if(page==HOME_PAGE+6){controller_audio_adjust(-20);controller_ota_changed();}
   else{controller_voice_cancel();touch_voicing=key_voicing=false;gesture.cancel();swipes.reset();if(page!=HOME_PAGE)go_page(HOME_PAGE);}
  }
  // Only the onboard power key can shut down. External B is always a control key.
  if(power_off.update(power_down,now)){stop_now();gpio_set_level(GPIO_NUM_17,0);}
  if(seen_stop!=stop_sequence.load()){
   stop_gate.stop();seen_stop=stop_sequence.load();controller_voice_cancel();
   controller_audio_prompt(controller::SpeechPrompt::STOPPED);
  }
  if(stop_gate.blocked(down,control_down,contact==1)){
   gesture.cancel();swipes.reset();side_key=controller::ButtonGesture{};control_key=controller::ControlButton{};
   touch_voicing=key_voicing=false;vTaskDelay(pdMS_TO_TICKS(20));continue;
  }
  if(ota_busy){
   (void)side_key.update(down,now);
   if(!updating){controller_voice_cancel();touch_voicing=key_voicing=false;}
   updating=true;
   gesture.cancel();swipes.reset();vTaskDelay(pdMS_TO_TICKS(20));continue;
  }
  updating=false;
  // Recording release always wins over long-press/double-tap classification.
  if(touch_voicing){
   auto voice_contact=controller::voice_contact(contact,tx,ty,screen_epoch.load()==touch_voice_epoch);
   if(voice_contact==controller::VoiceContact::SEND){touch_voicing=false;controller_voice_hold(false);gesture.cancel();swipes.reset();}
   else if(voice_contact==controller::VoiceContact::CANCEL){
    controller_voice_cancel();touch_voicing=false;gesture.cancel();swipes.reset();
   }
  }else if(contact<0){gesture.cancel();swipes.reset();}
  else{
   auto swipe=controller::Gesture::None;
   if(edge==controller::TouchEdge::DOWN){swipe_epoch=screen_epoch.load();swipe_contact=true;}
   if(!screen_painting&&!screen_failed&&page!=2&&!key_voicing&&swipe_contact&&swipe_epoch==screen_epoch.load())
    swipe=swipes.feed(contact==1,tx,ty,now);
   else {swipes.reset();swipe_contact=false;}
   if(contact==0)swipe_contact=false;
   if(swipe!=controller::Gesture::None){
    gesture.cancel();
    switch(swipe){
    case controller::Gesture::SwipeUp:controller_voice_cancel();go_page(controller::next_page(page.load(),HOME_PAGE));break;
    case controller::Gesture::SwipeDown:controller_voice_cancel();go_page(controller::previous_page(page.load(),HOME_PAGE));break;
    case controller::Gesture::DoubleTap:controller_voice_cancel();go_page(HOME_PAGE);break;
    default:break; // Hold-to-talk starts while held; never start it after release.
    }
   }else if(contact==1){
    if(edge==controller::TouchEdge::DOWN){
     touch_page=page.load();
     if(!screen_failed&&!screen_painting)gesture.begin(screen_epoch.load(),painted_epoch.load(),target,now);
    }else if(screen_painting||page!=touch_page||target!=gesture.target)gesture.cancel();
   }else if(edge==controller::TouchEdge::UP){
    auto action=gesture.target;int64_t began=gesture.began;
    if(!screen_failed&&!screen_painting&&gesture.release(screen_epoch.load(),now))touch_action(action,began,now);
   }
  }
  switch(side_key.update(down,now)){
  case controller::ButtonEvent::NEXT:
   if(page==HOME_PAGE+6){controller_audio_adjust(20);controller_ota_changed();}
   else{controller_voice_cancel();touch_voicing=key_voicing=false;gesture.cancel();swipes.reset();go_page(controller::next_page(page.load(),HOME_PAGE));}
   break;
  case controller::ButtonEvent::HOME:
   controller_voice_cancel();touch_voicing=key_voicing=false;gesture.cancel();swipes.reset();go_page(HOME_PAGE);break;
  case controller::ButtonEvent::VOICE_DOWN:
   // A always means hold-to-talk, regardless of the current page. It never
   // silently confirms HID access or starts a firmware update.
   if(!touch_voicing){key_voicing=true;go_page(PAGE_COUNT-1);stopped=false;controller_voice_hold(true);}
   break;
  case controller::ButtonEvent::VOICE_UP:
   if(key_voicing){key_voicing=false;controller_voice_hold(false);}
   break;
  default:break;
  }
  if(page==2&&consent_visible_at>0&&now-consent_visible_at.load()>=15000)go_page(HOME_PAGE);
  vTaskDelay(pdMS_TO_TICKS(20));
 }
}
static void console_command(char *line){
 if(strcmp(line,"STOP")==0)stop_now();
 else if(strcmp(line,"LOGS")==0)controller_logs_dump();
 else if(strcmp(line,"SCREEN")==0){
  static uint8_t snapshot[5000];bool valid;
  taskENTER_CRITICAL(&consent_mux);valid=panel_frame_valid;if(valid)memcpy(snapshot,panel_frame,5000);taskEXIT_CRITICAL(&consent_mux);
  if(valid){
   controller_usb_write("--- SCREEN BEGIN ---\r\n");
   for(int row=0;row<200;++row){char hex[53];for(int x=0;x<25;++x)snprintf(hex+x*2,3,"%02x",snapshot[row*25+x]);strcpy(hex+50,"\r\n");controller_usb_write(hex);}
   controller_usb_write("--- SCREEN END ---\r\n");
  }else controller_usb_write("SCREEN unavailable: no completed panel refresh\r\n");
 }
 else if(strcmp(line,"EVENTS")==0){static char snapshot[4097];controller_events_snapshot(snapshot,sizeof(snapshot));controller_usb_write(snapshot);}
 else if(strcmp(line,"STORAGE")==0)controller_storage_status();
 else if(strcmp(line,"SDLOGS")==0)controller_storage_dump();
 else if(strcmp(line,"SDEVENTS")==0)controller_storage_events_dump();
 else if(strcmp(line,"WIFI ON")==0){
#if CONFIG_CONTROLLER_USB_LOCAL
  controller_usb_write("WiFi forbidden in USB-local test build\r\n");
#else
  wifi_start();controller_usb_write("WiFi enabled for this boot\r\n");
#endif
 }
 else if(strcmp(line,"WIFI OFF")==0){wifi_enabled=false;wifi_connected=false;online=controller_usb_net_has_ip();if(wifi_initialized){esp_wifi_stop();}controller_usb_write("WiFi disabled\r\n");}
 else if(strcmp(line,"HEAP")==0){char out[180];snprintf(out,sizeof(out),"HEAP internal=%u largest=%u dma=%u dma_largest=%u\r\n",(unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),(unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA),(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_DMA));controller_usb_write(out);}
 else if(strcmp(line,"AUDIO")==0){char out[120];snprintf(out,sizeof(out),"AUDIO volume=%d muted=%d stage=%d\r\n",controller_audio_volume(),controller_audio_muted(),controller_voice_stage());controller_usb_write(out);}
 else if(strcmp(line,"AUDIO UP")==0){controller_audio_adjust(20);controller_ota_changed();}
 else if(strcmp(line,"AUDIO DOWN")==0){controller_audio_adjust(-20);controller_ota_changed();}
 else if(strcmp(line,"AUDIO MUTE")==0){controller_audio_toggle_mute();controller_ota_changed();}
 else if(strcmp(line,"AUDIO TEST")==0){controller_audio_prompt(controller::SpeechPrompt::TEST);}
 else if(strcmp(line,"AUDIO AUDIT")==0){controller_audio_prompt(controller::SpeechPrompt::AUDIT);}
 else if(strcmp(line,"AUDIO CLICK")==0){controller_audio_prompt(controller::SpeechPrompt::CLICK);}
 else if(strcmp(line,"VOICE PREPARE")==0){stopped=false;go_page(PAGE_COUNT-1);controller_voice_prepare();controller_usb_write("Voice connection check requested\r\n");}
 else if(strcmp(line,"VOICE START")==0){stopped=false;go_page(PAGE_COUNT-1);controller_voice_conversation();controller_usb_write("Continuous voice requested\r\n");}
 else if(strcmp(line,"VOICE DOWN")==0){stopped=false;go_page(PAGE_COUNT-1);controller_voice_hold(true);controller_usb_write("Voice hold requested\r\n");}
 else if(strcmp(line,"VOICE FINISH")==0){controller_usb_write(controller_voice_finish()?"Voice submitted\r\n":"Not recording\r\n");}
 else if(strcmp(line,"VOICE UP")==0){controller_voice_hold(false);controller_usb_write("Voice hold released\r\n");}
 else if(strcmp(line,"MIC TEST")==0){controller_voice_test();controller_usb_write("Microphone diagnostic: one second; samples discarded\r\n");}
 else if(strcmp(line,"PAGE")==0)go_page(controller::next_page(page.load(),HOME_PAGE));
 else if(strcmp(line,"SAFE")==0){taskENTER_CRITICAL(&consent_mux);controller_usb_request_mode(false);go_page(0);taskEXIT_CRITICAL(&consent_mux);}
 else if(strcmp(line,"OTA")==0){controller_ota_start();go_page(HOME_PAGE+5);controller_usb_write("OTA requested\r\n");}
 else if(strcmp(line,"VERSION")==0){char out[200];snprintf(out,sizeof(out),"VERSION %s slot=%s ota=%d progress=%d\r\n",esp_app_get_description()->version,esp_ota_get_running_partition()->label,controller_ota_stage(),controller_ota_progress());controller_usb_write(out);}
 else if(strcmp(line,"STATUS")==0){
  uint32_t rx,tx;controller_usb_net_counters(&rx,&tx);
  char status[256];snprintf(status,sizeof(status),"STATUS online=%d wifi=%d wifi_enabled=%d usb=%d hid=%d bluetooth=0 page=%d stopped=%d screen_error=%d psram=%u net=%d rx=%u tx=%u voice=%d time=%lld peer=%08x adb=%d\r\n",
   online.load(),wifi_connected.load(),wifi_enabled.load(),controller_usb_ready(),controller_usb_hid_enabled(),page.load(),stopped.load(),screen_failed.load(),(unsigned)esp_psram_get_size(),controller_usb_net_stage(),(unsigned)rx,(unsigned)tx,controller_voice_stage(),(long long)time(nullptr),(unsigned)controller_usb_net_peer(),controller_adb_stage());
  controller_usb_write(status);
 }else if(strcmp(line,"REBOOT")==0 || strcmp(line,"BOOTLOADER")==0){
  controller_usb_request_mode(false);
  controller_usb_prepare_reset(strcmp(line,"BOOTLOADER")==0);
  if(strcmp(line,"BOOTLOADER")==0)REG_SET_BIT(RTC_CNTL_OPTION1_REG,RTC_CNTL_FORCE_DOWNLOAD_BOOT);
  esp_restart();
 }else if(strncmp(line,"WIFI\t",5)==0){
  char *split=strchr(line+5,'\t');
  if(split && split-line-5<=32 && strlen(split+1)<=64){
   *split=0;nvs_handle_t h;
   if(nvs_open("wifi",NVS_READWRITE,&h)==ESP_OK){
    nvs_set_str(h,"ssid",line+5);nvs_set_str(h,"password",split+1);nvs_commit(h);nvs_close(h);
    controller_usb_write("WiFi saved; restarting\r\n");vTaskDelay(pdMS_TO_TICKS(300));esp_restart();
   }
  }
 }else controller_usb_write("Commands: STATUS LOGS PAGE STOP SAFE REBOOT BOOTLOADER WIFI ON/OFF; HID requires local screen confirmation\r\n");
}
static void console_task(void*){
 char line[256]={};size_t used=0;bool overflow=false;
 for(;;){
  controller_usb_service();
  if(online && !sntp_started){
   esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);esp_sntp_setservername(0,"ntp.aliyun.com");esp_sntp_init();sntp_started=true;
  }
  if(screen_dirty.exchange(false) && screen_task_handle)xTaskNotifyGive(screen_task_handle);
  uint8_t bytes[64];size_t n=controller_usb_read(bytes,sizeof(bytes));
  for(size_t i=0;i<n;++i){
   if(bytes[i]=='\n' || bytes[i]=='\r'){
    if(used && !overflow){line[used]=0;console_command(line);}
    memset(line,0,sizeof(line));used=0;overflow=false;
   }else if(used<sizeof(line)-1)line[used++]=(char)bytes[i];
   else overflow=true;
  }
  vTaskDelay(pdMS_TO_TICKS(20));
 }
}
extern "C" void app_main(){
 controller_logs_start();controller_event("boot",HOME_PAGE);
 ESP_LOGI(TAG,"Boot reset_reason=%d; HID=OFF WiFi=OFF Bluetooth=BLE-OTA",esp_reset_reason());
 ESP_ERROR_CHECK(nvs_flash_init());
 ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
 gpio_config_t power={};power.pin_bit_mask=(1ULL<<6)|(1ULL<<42)|(1ULL<<17);power.mode=GPIO_MODE_OUTPUT;
 ESP_ERROR_CHECK(gpio_config(&power));gpio_set_level(GPIO_NUM_6,0);gpio_set_level(GPIO_NUM_42,1);gpio_set_level(GPIO_NUM_17,1);
 gpio_config_t button={};button.pin_bit_mask=(1ULL<<0)|(1ULL<<18);
#if CONFIG_CONTROLLER_EXTERNAL_KEYS
 button.pin_bit_mask|=(1ULL<<1)|(1ULL<<2);
#endif
button.mode=GPIO_MODE_INPUT;button.pull_up_en=GPIO_PULLUP_ENABLE;ESP_ERROR_CHECK(gpio_config(&button));
 controller_touch_init();
 controller_usb_start();controller_adb_init();controller_voice_init();
 controller_storage_start();
 // BLE OTA 先起：板子即使没 Wi-Fi/USB，也能靠手机蓝牙推固件。
 { int rc=ble_ota_start(); if(rc!=0)ESP_LOGE(TAG,"BLE OTA start failed rc=%d",rc); }
 xTaskCreate(screen_task,"screen",24576,nullptr,3,&screen_task_handle);
 xTaskCreate(telemetry_task,"telemetry",12288,nullptr,2,nullptr);
 xTaskCreate(input_task,"button",3072,nullptr,5,nullptr);
 xTaskCreate(console_task,"console",4096,nullptr,2,nullptr);
 if(controller::wifi_on_boot())wifi_start();
 ESP_LOGI(TAG,"Epaper controller boot: PSRAM=%u; no automatic HID actions",(unsigned)esp_psram_get_size());
}
