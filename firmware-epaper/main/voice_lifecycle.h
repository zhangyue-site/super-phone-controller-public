#pragma once
#include <atomic>
namespace controller {
struct VoiceLifecycle {
 std::atomic<int> stage{0};
 std::atomic<unsigned> epoch{0};
 std::atomic<bool> busy{false};
 bool current(unsigned token)const{return token==epoch.load();}
 void cancel(){epoch.fetch_add(1);stage=0;}
 bool can_start()const{int s=stage.load();return !busy&&s!=1&&s!=2&&s!=4&&s!=7&&s!=10&&s!=11;}
 struct Lease {
  VoiceLifecycle &owner;
  explicit Lease(VoiceLifecycle &v):owner(v){owner.busy=true;}
  ~Lease(){owner.busy=false;}
 };
};
}
