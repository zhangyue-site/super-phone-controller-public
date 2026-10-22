#pragma once
#include <cstdint>
namespace controller {
// 16 kHz mono frames. Bounded listening prevents accidental indefinite capture.
struct ConversationVad {
 unsigned samples=0, voiced=0, silence=0;
 bool speech=false;
 bool feed(unsigned count,unsigned rms){
  samples+=count;
  if(rms>=240){voiced+=count;silence=0;if(voiced>=2400)speech=true;}
  else silence+=count;
  return samples>=160000 || (speech&&silence>=14400);
 }
 bool send(bool manual=false)const{return manual?samples>=6400:speech&&voiced>=2400;}
};
}
