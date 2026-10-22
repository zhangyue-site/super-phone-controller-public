#pragma once
namespace controller {
inline int clamp_volume(int value){return value<0?0:value>100?100:value;}
enum class VoiceContact { KEEP, SEND, CANCEL };
inline VoiceContact voice_contact(int contact,int x,int y,bool same_epoch){
 if(!same_epoch)return VoiceContact::CANCEL;
 if(contact==0)return VoiceContact::SEND;
 if(contact<0||!same_epoch||x<8||x>=192||y<45||y>=155)return VoiceContact::CANCEL;
 return VoiceContact::KEEP;
}
enum class SpeechPrompt { NONE=0, READY, RECOGNIZED, FAILED, STOPPED, TEST, CLICK, LISTEN, SUCCESS, AUDIT };
}
