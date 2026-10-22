#pragma once
#include <cstdint>
namespace controller {
inline bool rotate_log(uint64_t existing,uint64_t incoming){
 return incoming>65536 || existing>65536-incoming;
}
}
