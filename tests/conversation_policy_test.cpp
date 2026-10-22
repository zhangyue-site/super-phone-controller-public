#include "conversation_policy.h"
#include <cassert>
int main(){
 controller::ConversationVad quiet;for(int i=0;i<624;i++)assert(!quiet.feed(256,20));assert(quiet.feed(256,20));assert(!quiet.send());
 controller::ConversationVad speech;for(int i=0;i<20;i++)assert(!speech.feed(256,700));assert(speech.send());for(int i=0;i<56;i++)assert(!speech.feed(256,30));assert(speech.feed(256,30));
 controller::ConversationVad click;click.feed(256,3000);for(int i=0;i<624;i++)click.feed(256,20);assert(!click.send());
 controller::ConversationVad manual;manual.feed(256,10);assert(!manual.send(true));
 for(int i=0;i<24;i++)manual.feed(256,10);
 assert(manual.send(true));assert(!manual.send()); // manual finish does not fabricate VAD speech
}
