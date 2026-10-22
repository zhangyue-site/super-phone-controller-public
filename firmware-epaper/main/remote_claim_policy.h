#pragma once
#include <cstring>
namespace controller {
inline bool remote_claim_ready(bool idle,bool held,bool conversation,bool online,bool consent,bool usb){
 return idle&&!held&&!conversation&&online&&consent&&usb;
}
// Status must be parseable and known; losing STOP visibility is fail closed.
inline bool remote_status_cancel(const char *op){
 return !op||(std::strcmp(op,"wait")&&std::strcmp(op,"done"));
}
inline bool remote_task_id(const char *id){
 if(!id||std::strlen(id)!=32)return false;
 for(unsigned i=0;i<32;++i)if(!((id[i]>='0'&&id[i]<='9')||(id[i]>='a'&&id[i]<='f')))return false;
 return true;
}
}
