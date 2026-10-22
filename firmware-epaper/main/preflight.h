#pragma once
#include <array>
namespace controller {
enum CheckStatus {WAIT,RUN,DONE,FAILED,BLOCKED,AUTHORIZE};
struct PreflightInput {bool usb,peer;int adb;bool sharing;CheckStatus server,chat,asr;};
inline std::array<CheckStatus,8> preflight(PreflightInput s){
 std::array<CheckStatus,8> rows{};rows.fill(WAIT);
 if(!s.usb)return rows;
 rows[0]=DONE;
 if(!s.peer){rows[1]=s.adb==4?FAILED:s.adb==1?RUN:WAIT;return rows;}
 rows[1]=DONE;
 rows[2]=s.adb==3?DONE:s.adb==2?AUTHORIZE:s.adb==1?RUN:s.adb==5?FAILED:WAIT;
 if(rows[2]!=DONE)return rows;
 if(!s.sharing){rows[3]=BLOCKED;return rows;}
 rows[3]=DONE;
 rows[4]=s.server;if(rows[4]!=DONE)return rows;
 rows[5]=s.chat;rows[6]=s.asr;
 if(rows[5]==DONE && rows[6]==DONE)rows[7]=DONE;
 return rows;
}
}
