#pragma once
#include "adb_packet.h"
namespace controller {
enum class StreamEvent {IGNORE,OPENED,ACK,DATA,CLOSED,ERROR};
struct AdbStream {
 uint32_t local,remote=0;bool can_send=false;
 explicit AdbStream(uint32_t id):local(id){}
 StreamEvent receive(uint32_t cmd,uint32_t a,uint32_t b){
  if(b!=local)return StreamEvent::IGNORE;
  if(cmd==ADB_CLSE && (!remote || a==remote))return StreamEvent::CLOSED;
  if(cmd==ADB_OKAY){
   if(!remote){remote=a;can_send=true;return remote?StreamEvent::OPENED:StreamEvent::ERROR;}
   if(a==remote){can_send=true;return StreamEvent::ACK;}
  }
  if(cmd==ADB_WRTE && remote && a==remote)return StreamEvent::DATA;
  return StreamEvent::ERROR;
 }
 bool sent(){if(!can_send)return false;can_send=false;return true;}
};
}
