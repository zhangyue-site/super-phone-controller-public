#include "dialogue.h"
#include "voice.h"
#include "remote_claim_policy.h"
#include "usb.h"
#include "ota.h"
#include "ble_ota.h"
#include "adb_local.h"
#include "device_config.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <cstring>
#include <cstdlib>
#include <cmath>
extern const char *controller_ota_endpoint();
static char remote_lease[65]={};
static bool remote_dialogue=false;
static bool live(unsigned sequence){return controller_voice_cancel_sequence()<sequence;}
static int post(const char *path,unsigned sequence,const char *body,unsigned char *out,unsigned capacity,int timeout_ms=20000){
 if(!live(sequence))return -1;
 char url[256],auth[128],seq[16];snprintf(url,sizeof(url),"%s%s",controller_ota_endpoint(),path);
 snprintf(auth,sizeof(auth),"Bearer %s",DISPLAY_TOKEN);snprintf(seq,sizeof(seq),"%u",sequence);
 esp_http_client_config_t cfg={};cfg.url=url;cfg.common_name="erweima.zhangyue.site";cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.timeout_ms=timeout_ms;cfg.disable_auto_redirect=true;
 auto c=esp_http_client_init(&cfg);if(!c)return -1;
 esp_http_client_set_method(c,HTTP_METHOD_POST);esp_http_client_set_header(c,"Authorization",auth);esp_http_client_set_header(c,"Host","erweima.zhangyue.site");
 esp_http_client_set_header(c,"X-HID-Pointer","absolute-v1");esp_http_client_set_header(c,"Connection","close");esp_http_client_set_header(c,"X-Voice-Session",controller_voice_session());esp_http_client_set_header(c,"X-Voice-Sequence",seq);esp_http_client_set_header(c,"Content-Type","application/json");
 if(!strcmp(path,"/remote/claim")&&remote_lease[0])esp_http_client_set_header(c,"X-Remote-Lease",remote_lease);
 unsigned length=body?strlen(body):0;bool ok=esp_http_client_open(c,length)==ESP_OK;
 unsigned sent=0;while(ok&&sent<length&&live(sequence)){int n=esp_http_client_write(c,body+sent,length-sent);if(n<=0){ok=false;break;}sent+=n;}
 int used=0;
 if(ok&&sent==length&&live(sequence)&&esp_http_client_fetch_headers(c)>=0&&esp_http_client_get_status_code(c)==200){
  for(;;){if(!live(sequence)||used>=(int)capacity){ok=false;break;}int n=esp_http_client_read(c,(char*)out+used,capacity-used);if(n<0){ok=false;break;}if(n==0){ok=esp_http_client_is_complete_data_received(c);break;}used+=n;}
 }else ok=false;
 esp_http_client_close(c);esp_http_client_cleanup(c);return ok&&live(sequence)?used:-1;
}
static const char *str(cJSON *j,const char *key){auto v=cJSON_GetObjectItemCaseSensitive(j,key);return cJSON_IsString(v)?v->valuestring:"";}
// A lost claim response is never replayed; only validated dialogue commands execute.
bool controller_dialogue_remote_claim(unsigned sequence){
 bool had_lease=remote_lease[0]!=0;
 char response[192];int n=post("/remote/claim",sequence,"{\"ready\":true}",(unsigned char*)response,sizeof(response)-1,2500);
 if(n<0)return false;
 response[n]=0;cJSON *j=cJSON_Parse(response);if(!j)return false;
 const char *lease=str(j,"lease");bool valid_lease=strlen(lease)==64;
 for(unsigned i=0;valid_lease&&i<64;++i)valid_lease=(lease[i]>='0'&&lease[i]<='9')||(lease[i]>='a'&&lease[i]<='f');
 if(valid_lease)memcpy(remote_lease,lease,65);
 bool start=had_lease&&!strcmp(str(j,"op"),"start")&&controller::remote_task_id(str(j,"task_id"));
 cJSON_Delete(j);return start;
}
static bool remote_status_live(unsigned sequence){
 if(controller_ota_busy()||ble_ota_busy()){controller_voice_cancel();controller_release();return false;}
 if(!remote_dialogue)return live(sequence);
 char response[96];int n=post("/remote/status",sequence,nullptr,(unsigned char*)response,sizeof(response)-1,1500);
 bool cancel=n<0;
 if(n>=0){
  response[n]=0;cJSON *j=cJSON_Parse(response);
  cancel=controller::remote_status_cancel(str(j,"op"));cJSON_Delete(j);
 }
 if(cancel&&live(sequence)){controller_voice_cancel();controller_release();}
 return !cancel&&live(sequence);
}
bool controller_dialogue_remote_run(unsigned sequence){
 // The USB-local ADB proxy supports one socket. Cloud STOP is checked
 // synchronously between actions; never enqueue a parallel status socket
 // behind a Chinese shell or audio HTTP stream. Local STOP still revokes the
 // ADB gate immediately. Chinese shell EXIT/recovery retain IME restoration.
 remote_dialogue=true;
 bool ok=controller_dialogue_run(sequence);
 remote_dialogue=false;return ok&&live(sequence);
}
static bool pointer_command(cJSON *j,controller::PointerCommand& command){
 unsigned seen=0;
 for(cJSON *v=j->child;v;v=v->next){
  if(!v->string)return false;
  const char *keys[]={"op","id","kind","x","y","x2","y2","duration_ms"};
  unsigned bit=0;for(unsigned i=0;i<8;++i)if(!strcmp(v->string,keys[i]))bit=1u<<i;
  if(!bit||(seen&bit))return false;
  seen|=bit;
 }
 if((seen&31)!=31)return false;
 const char *id=str(j,"id");if(strlen(id)!=32)return false;
 for(unsigned i=0;i<32;++i)if(!((id[i]>='0'&&id[i]<='9')||(id[i]>='a'&&id[i]<='f')))return false;
 const char *kind=str(j,"kind");
 if(!strcmp(kind,"move"))command.kind=controller::PointerKind::move;
 else if(!strcmp(kind,"click"))command.kind=controller::PointerKind::click;
 else if(!strcmp(kind,"drag"))command.kind=controller::PointerKind::drag;
 else return false;
 auto number=[j](const char *name,int& out){
  cJSON *v=cJSON_GetObjectItemCaseSensitive(j,name);
  if(!cJSON_IsNumber(v)||!std::isfinite(v->valuedouble)||v->valuedouble<0||v->valuedouble>32767||std::floor(v->valuedouble)!=v->valuedouble)return false;
  out=(int)v->valuedouble;return true;
 };
 if(!number("x",command.x)||!number("y",command.y))return false;
 if((seen&32)&&!number("x2",command.x2))return false;
 if((seen&64)&&!number("y2",command.y2))return false;
 if((seen&128)&&!number("duration_ms",command.duration_ms))return false;
 return controller::valid_pointer(command,seen&32,seen&64,seen&128);
}
bool controller_dialogue_run(unsigned sequence){
 auto pointer_ids=(char (*)[33])heap_caps_calloc(64,33,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);unsigned pointer_count=0;
 if(!pointer_ids)return false;
 auto output=(char*)heap_caps_malloc(48001,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!output){free(pointer_ids);return false;}
 bool success=false;int64_t until=esp_timer_get_time()+180000000;uint32_t ticket=controller_adb_ticket();
 controller_voice_state(10);
 while(live(sequence)&&esp_timer_get_time()<until){
  if(!remote_status_live(sequence))break;
  char response[2048];int n=post("/dialogue/poll",sequence,nullptr,(unsigned char*)response,sizeof(response)-1);
  if(n<0)break;
  response[n]=0;cJSON *j=cJSON_Parse(response);if(!j)break;
  const char *op=str(j,"op");
  if(!strcmp(op,"cancelled")){cJSON_Delete(j);controller_voice_cancel();controller_release();break;}
  if(!strcmp(op,"wait")){cJSON_Delete(j);vTaskDelay(pdMS_TO_TICKS(200));continue;}
  if(!strcmp(op,"done")){
   success=!strcmp(str(j,"state"),"done");bool audio=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j,"audio"));cJSON_Delete(j);
   auto frame=(unsigned char*)heap_caps_malloc(5001,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
   if(frame){if(post("/dialogue/screen",sequence,nullptr,frame,5001)==5000&&live(sequence))controller_dialogue_screen(frame);free(frame);}
   if(audio&&!controller_audio_muted()&&controller_audio_volume()>0){
    controller_voice_state(11);auto pcm=(unsigned char*)heap_caps_malloc(960001,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(pcm){int size=post("/dialogue/audio",sequence,nullptr,pcm,960001);if(size>0&&size<=960000&&!(size%2)&&live(sequence)){if(!controller_audio_play_pcm(pcm,size))success=false;}else success=false;free(pcm);}else success=false;
   }
   break;
  }
  if(!strcmp(op,"hid_pointer")){
   controller::PointerCommand command{};const char *id=str(j,"id");bool valid=pointer_command(j,command);
   if(valid){for(unsigned i=0;i<pointer_count;++i)if(!strcmp(pointer_ids[i],id))valid=false;}
   if(pointer_count>=64)valid=false;
   // Reserve before submission: an ACK failure must never replay the action.
   if(valid)strcpy(pointer_ids[pointer_count++],id);
   bool ok=valid&&remote_status_live(sequence)&&controller_usb_ai_pointer(command,live,sequence);
   cJSON *ack=cJSON_CreateObject();cJSON_AddStringToObject(ack,"id",id);cJSON_AddBoolToObject(ack,"ok",ok);
   cJSON_AddStringToObject(ack,"output",ok?"HID_POINTER_REPORT_SENT":"");
   if(!ok)cJSON_AddStringToObject(ack,"error",!valid?"invalid_command":live(sequence)?"input_failed":"cancelled");
   char *body=cJSON_PrintUnformatted(ack);cJSON_Delete(ack);cJSON_Delete(j);
   char result[128];bool sent=body&&post("/dialogue/result",sequence,body,(unsigned char*)result,sizeof(result))>=0;free(body);
   if(!sent)break;
   continue;
  }
  if(!strcmp(op,"hid_home")){
   const char *id=str(j,"id");bool valid=strlen(id)==32;
   bool ok=valid&&remote_status_live(sequence)&&controller_usb_ai_home(live,sequence);
   cJSON *ack=cJSON_CreateObject();cJSON_AddStringToObject(ack,"id",id);cJSON_AddBoolToObject(ack,"ok",ok);
   cJSON_AddStringToObject(ack,"output",ok?"HID_HOME_REPORT_SENT":"");
   if(!ok)cJSON_AddStringToObject(ack,"error",live(sequence)?"input_failed":"cancelled");
   char *body=cJSON_PrintUnformatted(ack);cJSON_Delete(ack);cJSON_Delete(j);
   char result[128];bool sent=body&&post("/dialogue/result",sequence,body,(unsigned char*)result,sizeof(result))>=0;free(body);
   ESP_LOGI("dialogue","AI HID home report_sent=%d ack=%d",ok,sent);
   if(!sent)break;
   continue;
  }
  controller::AdbCommand cmd{};bool valid=!strcmp(op,"type_text");
  if(valid){const char *v=str(j,"text_b64");valid=strlen(v)>0&&strlen(v)<sizeof(cmd.text_b64);if(valid)strcpy(cmd.text_b64,v);}
  const char *id=str(j,"id");if(strlen(id)!=32)valid=false;
  const char *error=valid?"cancelled":"invalid_command";
  ESP_LOGI("dialogue","Command received op=%s id=%.8s valid=%d",op,id,valid);
  bool ok=valid&&remote_status_live(sequence)&&controller_adb_execute(cmd,nullptr,output,48001,ticket,&error);
  if(!ok)output[0]=0;
  cJSON *ack=cJSON_CreateObject();cJSON_AddStringToObject(ack,"id",id);cJSON_AddBoolToObject(ack,"ok",ok);cJSON_AddStringToObject(ack,"output",output);if(!ok)cJSON_AddStringToObject(ack,"error",error);
  char *body=cJSON_PrintUnformatted(ack);cJSON_Delete(ack);cJSON_Delete(j);
  char result[128];bool sent=body&&post("/dialogue/result",sequence,body,(unsigned char*)result,sizeof(result))>=0;free(body);
  ESP_LOGI("dialogue","Command result ok=%d error=%s ack=%d",ok,ok?"":error,sent);
  if(!sent)break;
 }
 free(pointer_ids);free(output);return success&&live(sequence);
}
