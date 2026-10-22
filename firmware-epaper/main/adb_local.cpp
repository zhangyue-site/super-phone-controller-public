#include "adb_local.h"
#include "sdkconfig.h"
#if CONFIG_CONTROLLER_USB_LOCAL
#include "adb_packet.h"
#include "adb_gate.h"
#include "adb_stream.h"
#include "device_adb_keys.h"
#include "usb_network.h"
#include "voice.h"
#include <atomic>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "mbedtls/pk.h"
#include "mbedtls/version.h"
#if MBEDTLS_VERSION_MAJOR >= 4
#include "psa/crypto.h"
#endif
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
using namespace controller;
static AdbGate gate;
static std::atomic<uint64_t> status(0),failure(0);
static int connect_error=0;
static TaskHandle_t worker;
static int fd=-1,listener=-1;
static uint32_t next_stream=2;
static SemaphoreHandle_t command_mutex;
static std::atomic<int> command_state(0); // 0 idle, 1 queued, 2 complete
static std::atomic<bool> command_ok(false);
static const char *command_error="";
static bool command_transport_broken=false;
static AdbCommand queued_command;
static uint32_t command_ticket;
static char *command_expected,*command_output;
static bool execute_queued(unsigned char *data);

static unsigned active_epoch;
static int64_t deadline;
static bool live(){return gate.active(active_epoch) && controller_usb_net_peer()!=0;}
static void state(uint32_t token,int s){status=((uint64_t)token<<32)|(unsigned)s;controller_net_changed();controller_voice_changed(false);}
static bool io(void *buffer,size_t len,bool write){
 auto p=(unsigned char*)buffer;size_t done=0;
 while(done<len && live() && esp_timer_get_time()<deadline){
  int n=write?send(fd,p+done,len-done,0):recv(fd,p+done,len-done,0);
  if(n>0){done+=n;continue;}
  if(n==0)return false;
  if(errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)return false;
  vTaskDelay(pdMS_TO_TICKS(10));
 }
 return done==len;
}
static bool packet(uint32_t cmd,uint32_t a,uint32_t b,const void *p=nullptr,size_t n=0){
 if(!live() || n>4096)return false;
 auto h=adb_header(cmd,a,b,(const unsigned char*)p,n);
 return io(&h,sizeof(h),true) && (!n || io((void*)p,n,true));
}
static bool receive(AdbHeader &h,unsigned char *p){
 if(!io(&h,sizeof(h),false) || h.magic!=(h.command^0xffffffffu) || h.length>4096)return false;
 if(h.length && !io(p,h.length,false))return false;
 return adb_valid(h,p,h.length);
}
#if MBEDTLS_VERSION_MAJOR < 4
static int random_bytes(void*,unsigned char *out,size_t size){esp_fill_random(out,size);return 0;}
#endif
static bool connect_peer(){
 connect_error=ETIMEDOUT;
 fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0){connect_error=errno;return false;}
 timeval timeout={0,100000};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
 sockaddr_in local={};local.sin_family=AF_INET;inet_pton(AF_INET,"192.168.77.1",&local.sin_addr);
 if(bind(fd,(sockaddr*)&local,sizeof(local))!=0){connect_error=errno;return false;}
 sockaddr_in peer={};peer.sin_family=AF_INET;peer.sin_port=htons(5555);peer.sin_addr.s_addr=controller_usb_net_peer();
 fcntl(fd,F_SETFL,fcntl(fd,F_GETFL,0)|O_NONBLOCK);
 if(connect(fd,(sockaddr*)&peer,sizeof(peer))==0)return true;
 if(errno!=EINPROGRESS){connect_error=errno;return false;}
 while(live() && esp_timer_get_time()<deadline){
  fd_set ready;FD_ZERO(&ready);FD_SET(fd,&ready);timeval wait={0,100000};
  if(select(fd+1,nullptr,&ready,nullptr,&wait)>0){int error=0;socklen_t size=sizeof(error);if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)!=0){connect_error=errno;return false;}connect_error=error;return error==0;}
 }
 return false;
}
static bool authenticate(unsigned char *data){
 const char banner[]="host::";
 if(!packet(ADB_CNXN,0x01000000,4096,banner,sizeof(banner)))return false;
 mbedtls_pk_context key;mbedtls_pk_init(&key);
#if MBEDTLS_VERSION_MAJOR >= 4
 bool parsed=psa_crypto_init()==PSA_SUCCESS&&mbedtls_pk_parse_key(&key,(const unsigned char*)board_adb_private,sizeof(board_adb_private),nullptr,0)==0;
#else
 bool parsed=mbedtls_pk_parse_key(&key,(const unsigned char*)board_adb_private,sizeof(board_adb_private),nullptr,0,random_bytes,nullptr)==0;
#endif
 bool signed_once=false,pub_sent=false,ok=false;AdbHeader h;
 while(parsed && receive(h,data)){
  if(h.command==ADB_CNXN){ok=true;break;}
  if(h.command!=ADB_AUTH || h.arg0!=1 || h.length!=20)break;
  if(!signed_once){
   unsigned char signature[256];size_t len=0;
#if MBEDTLS_VERSION_MAJOR >= 4
   if(mbedtls_pk_sign(&key,MBEDTLS_MD_SHA1,data,20,signature,sizeof(signature),&len)!=0)break;
#else
   if(mbedtls_pk_sign(&key,MBEDTLS_MD_SHA1,data,20,signature,sizeof(signature),&len,random_bytes,nullptr)!=0)break;
#endif
   signed_once=true;if(!packet(ADB_AUTH,2,0,signature,len))break;
  }else if(!pub_sent){
   pub_sent=true;state(active_epoch,2);
   if(!packet(ADB_AUTH,3,0,board_adb_public,sizeof(board_adb_public)))break;
  }else break;
 }
 mbedtls_pk_free(&key);return ok;
}
static bool shell_probe(unsigned char *data){
 const char command[]="shell:f=/data/local/tmp/controller-ime.restore; if test -f \"$f\"; then o=$(cat \"$f\"); case \"$o\" in ''|*[!a-zA-Z0-9_./$]*) exit 40;; esac; ime set \"$o\" >/dev/null && rm -f \"$f\" || exit 41; fi; echo __CONTROLLER_ADB_OK__";
 if(!packet(ADB_OPEN,1,0,command,sizeof(command)))return false;
 AdbHeader h;uint32_t remote=0;bool marker=false;size_t matched=0;
 while(receive(h,data)){
  if(h.command==ADB_OKAY && h.arg1==1){remote=h.arg0;continue;}
  if(h.command==ADB_WRTE && h.arg1==1){
   remote=h.arg0;
   // The fixed probe is tiny, but handle a marker split between WRTE packets.
   static const char expected[]="__CONTROLLER_ADB_OK__";
   static constexpr size_t expected_len=sizeof(expected)-1;

   for(size_t i=0;i<h.length;++i){matched=data[i]==expected[matched]?matched+1:(data[i]==expected[0]?1:0);if(matched==expected_len){marker=true;matched=0;}}
   if(!packet(ADB_OKAY,1,remote))return false;
  }else if(h.command==ADB_CLSE && h.arg1==1){packet(ADB_CLSE,1,h.arg0);return marker;}
  else return false;
 }
 return false;
}
// ADB is restricted to the approved ADB Keyboard text injection. It cannot observe UI, capture screenshots, launch apps, or synthesize touch input.
static bool shell_command(const char *command,char *out,unsigned capacity,unsigned char *data){
 char service[4096];int n=snprintf(service,sizeof(service),"shell:%s; echo __PC_EXIT_$?__",command);
 if(n<=0||n>=(int)sizeof(service))return false;
 command_transport_broken=true;
 AdbStream s(next_stream++);unsigned used=0;AdbReply reply;
 deadline=esp_timer_get_time()+12000000;
 if(!packet(ADB_OPEN,s.local,0,service,n+1))return false;
 bool complete=false;
 while(live()&&esp_timer_get_time()<deadline){
  AdbHeader h;if(!receive(h,data))break;
  auto e=s.receive(h.command,h.arg0,h.arg1);
  if(e==StreamEvent::ERROR)break;
  if(e==StreamEvent::DATA){
   reply.feed((char*)data,h.length);
   for(unsigned i=0;i<h.length;i++)if(data[i]!='\r'){
    if(used+1>=capacity){if(s.remote)packet(ADB_CLSE,s.local,s.remote);return false;}
    out[used++]=data[i];
   }
   if(!packet(ADB_OKAY,s.local,s.remote))break;
  }else if(e==StreamEvent::CLOSED){packet(ADB_CLSE,s.local,h.arg0);complete=true;break;}
 }
 out[used]=0;
 if(!complete&&s.remote&&live())packet(ADB_CLSE,s.local,s.remote);
 if(complete)command_transport_broken=false;
 bool ok=complete&&reply.success();
 if(ok){char *marker=strstr(out,"__PC_EXIT_0__");if(marker)*marker=0;}
 return ok;
}
static bool execute_queued(unsigned char *data){
 command_transport_broken=false;
 if(!live()||!command_output){command_error="adb_unavailable";return false;}
 command_output[0]=0;
 if(queued_command.op!=AdbOp::TYPE_TEXT){command_error="invalid_command";return false;}
 char command[4096];if(!adb_command(queued_command,command,sizeof(command))){command_error="invalid_command";return false;}
 bool ok=shell_command(command,command_output,48001,data);if(!ok)command_error="input_failed";return ok;
}
bool controller_adb_execute(const AdbCommand &command,const char *expected,char *out,unsigned capacity,uint32_t ticket,const char **error){
 auto fail=[&](const char *reason){if(error)*error=reason;return false;};
 if(error)*error="";
 if(!out||capacity<1||!command_mutex||!command_output||!command_expected||!gate.active(ticket))return fail("adb_unavailable");
 if(xSemaphoreTake(command_mutex,pdMS_TO_TICKS(100))!=pdTRUE)return fail("busy");
 if(command_state!=0||controller_adb_stage()!=3){xSemaphoreGive(command_mutex);return fail("adb_unavailable");}
 size_t size=expected?strlen(expected):0;
 if(command.op!=AdbOp::TYPE_TEXT||size!=0){xSemaphoreGive(command_mutex);return fail("invalid_command");}
 command_expected[0]=0;command_output[0]=0;queued_command=command;command_ticket=ticket;command_ok=false;command_error="";command_state=1;
 // The storage belongs to this module, so cancellation cannot leave a stack pointer queued.
 while(command_state==1&&gate.active(ticket))vTaskDelay(pdMS_TO_TICKS(20));
 bool ok=command_state==2&&command_ok&&gate.active(ticket);
 if(ok){size_t n=strlen(command_output);if(n>=capacity)ok=false;else memcpy(out,command_output,n+1);}
 // Wait for transport owner to release the buffers before a new request can reuse them.
 while(command_state==1)vTaskDelay(pdMS_TO_TICKS(20));
 if(!ok&&error)*error=*command_error?command_error:!gate.active(ticket)?"cancelled":"input_failed";
 command_state=0;xSemaphoreGive(command_mutex);return ok;
}

// Only this fixed server destination is permitted. TLS stays on the board.
static bool proxy_write(int client,const unsigned char *data,size_t length){
 size_t done=0;
 while(done<length && live() && esp_timer_get_time()<deadline){
  int n=send(client,data+done,length-done,0);
  if(n>0){done+=n;continue;}
  if(n==0 || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR))return false;
  vTaskDelay(pdMS_TO_TICKS(10));
 }
 return done==length;
}
static bool proxy_session(int client,unsigned char *data){
 const char service[]="exec:toybox nc 192.0.2.10 443";
 AdbStream stream(next_stream++);
 deadline=esp_timer_get_time()+150000000;
 if(!packet(ADB_OPEN,stream.local,0,service,sizeof(service)))return false;
 bool transport_ok=true,closed_by_phone=false;unsigned long to_phone=0,to_board=0;
 while(live() && esp_timer_get_time()<deadline){
  fd_set inputs;FD_ZERO(&inputs);FD_SET(fd,&inputs);
  if(stream.can_send)FD_SET(client,&inputs);
  timeval timeout={0,100000};int n=select((fd>client?fd:client)+1,&inputs,nullptr,nullptr,&timeout);
  if(n<0){if(errno==EINTR)continue;transport_ok=false;break;}
  if(FD_ISSET(fd,&inputs)){
   AdbHeader h;if(!receive(h,data)){transport_ok=false;break;}
   StreamEvent event=stream.receive(h.command,h.arg0,h.arg1);
   if(event==StreamEvent::ERROR){transport_ok=false;break;}
   if(event==StreamEvent::CLOSED){closed_by_phone=true;packet(ADB_CLSE,stream.local,h.arg0);break;}
   if(event==StreamEvent::DATA){
    if(!proxy_write(client,data,h.length))break;
    to_board+=h.length;
    if(!packet(ADB_OKAY,stream.local,stream.remote)){transport_ok=false;break;}
   }
  }
  if(stream.can_send && FD_ISSET(client,&inputs)){
   int count=recv(client,data,4096,0);
   if(count==0)break;
   if(count<0){if(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR)continue;break;}
   if(!stream.sent() || !packet(ADB_WRTE,stream.local,stream.remote,data,count)){transport_ok=false;break;}
   to_phone+=count;
  }
 }
 if(!closed_by_phone && stream.remote && live())packet(ADB_CLSE,stream.local,stream.remote);
 ESP_LOGI("adb_local","USB TLS pipe bytes up=%lu down=%lu transport=%d",to_phone,to_board,transport_ok);
 return transport_ok;
}
static bool proxy_loop(unsigned char *data){
 while(live()){
  if(command_state==1){
   int64_t began=esp_timer_get_time();
   bool ok=command_ticket==active_epoch&&execute_queued(data);
   ESP_LOGI("adb_local","Command op=%d ok=%d error=%s bytes=%u elapsed_ms=%lld",(int)queued_command.op,ok,command_error,(unsigned)strlen(command_output),(esp_timer_get_time()-began)/1000);
   command_ok=ok;command_state=2;
   // Safe refusals still need this same ADB tunnel to ACK and fetch TTS.
   if(!ok&&command_transport_broken)return false;
  }
  fd_set inputs;FD_ZERO(&inputs);FD_SET(listener,&inputs);FD_SET(fd,&inputs);
  timeval timeout={0,100000};int n=select((listener>fd?listener:fd)+1,&inputs,nullptr,nullptr,&timeout);
  if(n<0){if(errno==EINTR)continue;return false;}
  if(FD_ISSET(fd,&inputs)){
   // Consume late closes/acks instead of spinning on an unread packet.
   deadline=esp_timer_get_time()+2000000;AdbHeader h;
   if(!receive(h,data))return false;
   if(h.command==ADB_WRTE || h.command==ADB_CLSE)packet(ADB_CLSE,h.arg1,h.arg0);
  }
  if(FD_ISSET(listener,&inputs)){
   int client=accept(listener,nullptr,nullptr);if(client<0)continue;
   fcntl(client,F_SETFL,fcntl(client,F_GETFL,0)|O_NONBLOCK);
   bool ok=proxy_session(client,data);shutdown(client,SHUT_RDWR);close(client);
   if(!ok)return false;
  }
 }
 return false;
}
static void run(void*){

 unsigned char *data=(unsigned char*)malloc(4096);
 for(;;){
  ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
  active_epoch=gate.ticket();if(!gate.active(active_epoch))continue;
  state(active_epoch,1);
  int64_t lease_deadline=esp_timer_get_time()+10000000;
  while(gate.active(active_epoch) && !controller_usb_net_peer() && esp_timer_get_time()<lease_deadline)vTaskDelay(pdMS_TO_TICKS(100));
  if(!live() || !data){if(gate.finish(active_epoch)){failure=((uint64_t)(active_epoch&~1u)<<32)|1;state(active_epoch&~1u,4);}continue;}
  deadline=esp_timer_get_time()+2000000;
  bool ok=connect_peer();int reason=ok?0:connect_error==ECONNREFUSED?2:connect_error==ETIMEDOUT?3:4;
  if(ok){deadline=esp_timer_get_time()+25000000;ok=authenticate(data);if(!ok)reason=5;
   else{ok=shell_probe(data);if(!ok)reason=6;}
  }
  if(!ok)ESP_LOGW("adb_local","Probe failed phase=%d socket_error=%d; verify direct phone connection",reason,connect_error);
  if(ok && live()){
   state(active_epoch,3);ESP_LOGI("adb_local","Authorized USB-local ADB shell probe succeeded; no phone action executed");
   if(listener>=0)proxy_loop(data);
  }
  if(command_state==1){command_ok=false;command_state=2;}
  if(fd>=0){shutdown(fd,SHUT_RDWR);close(fd);fd=-1;}
  if(gate.finish(active_epoch)){failure=((uint64_t)(active_epoch&~1u)<<32)|(unsigned)(reason?reason:7);state(active_epoch&~1u,5);}
 }
}
void controller_adb_init(){
 command_mutex=xSemaphoreCreateMutex();
 command_expected=(char*)heap_caps_malloc(48001,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 command_output=(char*)heap_caps_malloc(786433,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 listener=socket(AF_INET,SOCK_STREAM,0);
 if(listener>=0){
  sockaddr_in address={};address.sin_family=AF_INET;address.sin_port=htons(18843);inet_pton(AF_INET,"127.0.0.1",&address.sin_addr);
  if(bind(listener,(sockaddr*)&address,sizeof(address))!=0 || listen(listener,2)!=0){close(listener);listener=-1;}
 }
 xTaskCreate(run,"usb_local_adb",10240,nullptr,3,&worker);
}
uint32_t controller_adb_ticket(){return gate.ticket();}
bool controller_adb_activate(uint32_t consent){
 if(gate.active(consent) && controller_adb_stage()==3)return true;
 if(!worker)return false;
 uint32_t token;if(!gate.activate(consent,token))return false;
 failure=(uint64_t)token<<32;state(token,1);xTaskNotifyGive(worker);
 int64_t end=esp_timer_get_time()+38000000;
 while(gate.active(token) && controller_adb_stage()!=3 && esp_timer_get_time()<end)vTaskDelay(pdMS_TO_TICKS(50));
 return gate.active(token) && controller_adb_stage()==3;
}
void controller_adb_cancel(){uint32_t token=gate.revoke();failure=(uint64_t)token<<32;state(token,0);}
int controller_adb_stage(){
 uint32_t token=gate.ticket();uint64_t snapshot=status.load();
 return (uint32_t)(snapshot>>32)==token?(int)(snapshot&0xffffffffu):((token&1)?1:0);
}
int controller_adb_error(){uint64_t snapshot=failure.load();return (uint32_t)(snapshot>>32)==gate.ticket()?(int)(snapshot&0xffffffffu):0;}

bool controller_adb_network_available(){return listener>=0 && controller_adb_stage()==3;}

#else
bool controller_adb_execute(const controller::AdbCommand&,const char*,char*,unsigned,uint32_t,const char **error){if(error)*error="adb_unavailable";return false;}
void controller_adb_init(){}
bool controller_adb_activate(uint32_t){return false;}
uint32_t controller_adb_ticket(){return 0;}
void controller_adb_cancel(){}
int controller_adb_stage(){return 0;}
int controller_adb_error(){return 0;}
bool controller_adb_network_available(){return false;}
#endif
