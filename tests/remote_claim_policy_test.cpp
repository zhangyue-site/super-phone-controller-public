#include "remote_claim_policy.h"
#include <cassert>
int main(){
 using controller::remote_claim_ready;
 assert(!controller::remote_status_cancel("wait"));
 assert(!controller::remote_status_cancel("done"));
 assert(controller::remote_status_cancel("cancelled"));
 assert(controller::remote_status_cancel(""));
 assert(controller::remote_status_cancel(nullptr));
 assert(remote_claim_ready(true,false,false,true,true,true));
 assert(!remote_claim_ready(false,false,false,true,true,true));
 assert(!remote_claim_ready(true,true,false,true,true,true));
 assert(!remote_claim_ready(true,false,true,true,true,true));
 assert(!remote_claim_ready(true,false,false,false,true,true));
 assert(!remote_claim_ready(true,false,false,true,false,true));
 assert(!remote_claim_ready(true,false,false,true,true,false));
 assert(controller::remote_task_id("0123456789abcdef0123456789abcdef"));
 assert(!controller::remote_task_id("0123456789abcdef0123456789abcdeg"));
 assert(!controller::remote_task_id(""));
}
