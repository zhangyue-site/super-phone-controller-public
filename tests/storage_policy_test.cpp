#include <cassert>
#include <cstdint>
#include "storage_policy.h"
int main(){
 assert(controller::rotate_log(65530,20));
 assert(!controller::rotate_log(65500,36));
 assert(!controller::rotate_log(0,65536));
 assert(controller::rotate_log(UINT64_MAX,1));
}
