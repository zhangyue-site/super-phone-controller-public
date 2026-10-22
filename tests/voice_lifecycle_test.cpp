#include "voice_lifecycle.h"
#include <cassert>
#include <initializer_list>
int main(){
 controller::VoiceLifecycle v;
 assert(v.can_start());
 for(int stage:{10,11}){
  v.stage=stage;v.busy=true;unsigned old=v.epoch.load();
  v.cancel();assert(v.stage==0);assert(!v.current(old));
  assert(!v.can_start()); // Wait for old worker to release capture/network buffers.
  v.busy=false;assert(v.can_start());
 }
}
