#include <cassert>
#include "preflight.h"
int main(){
 using namespace controller;
 auto s=preflight({true,true,3,false,WAIT,WAIT,WAIT});
 assert(s[0]==DONE && s[1]==DONE && s[2]==DONE);
 assert(s[3]==BLOCKED && s[4]==WAIT && s[7]==WAIT);
 s=preflight({true,true,2,false,WAIT,WAIT,WAIT});assert(s[2]==AUTHORIZE && s[3]==WAIT);
 s=preflight({true,false,4,false,WAIT,WAIT,WAIT});assert(s[1]==FAILED && s[2]==WAIT);
 s=preflight({true,true,5,false,WAIT,WAIT,WAIT});assert(s[2]==FAILED);
 s=preflight({false,true,3,true,DONE,DONE,DONE});for(auto row:s)assert(row!=DONE);
 s=preflight({true,true,3,true,DONE,DONE,DONE});for(auto row:s)assert(row==DONE);
 s=preflight({true,true,0,true,DONE,DONE,DONE});assert(s[3]!=DONE && s[7]!=DONE);
 s=preflight({true,true,3,true,DONE,FAILED,DONE});assert(s[7]!=DONE);
}
