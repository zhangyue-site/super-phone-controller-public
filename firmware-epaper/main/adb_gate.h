#pragma once
#include <atomic>
#include <stdint.h>
namespace controller {
class AdbGate {
 std::atomic<uint32_t> value{0};
 public:
 uint32_t ticket()const{return value.load();}
 bool active(uint32_t token)const{return (token&1) && value.load()==token;}
 bool activate(uint32_t consent,uint32_t &token){
  token=(consent+2)|1u;
  return value.compare_exchange_strong(consent,token);
 }
 uint32_t revoke(){
  uint32_t previous=value.load(),next;
  do{next=(previous+2)&~1u;}while(!value.compare_exchange_weak(previous,next));
  return next;
 }
 bool finish(uint32_t token){return value.compare_exchange_strong(token,token&~1u);}
};
}
