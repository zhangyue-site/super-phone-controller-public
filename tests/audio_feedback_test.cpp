#include "audio_feedback.h"
#include <cassert>
#include <cstdlib>
int main(){
 using namespace controller;
 PressFeedback edge;assert(!edge.update(false));assert(edge.update(true));assert(!edge.update(true));assert(!edge.update(false));assert(edge.update(true));
 for(auto cue:{Feedback::CLICK,Feedback::LISTEN,Feedback::SUCCESS,Feedback::FAILURE,Feedback::STOP}){
  int n=feedback_samples(cue);assert(n>0&&n<=4800);
  assert(feedback_sample(cue,0)==0);assert(feedback_sample(cue,n-1)==0);
  int peak=0;for(int i=0;i<n;i++){int v=std::abs((int)feedback_sample(cue,i));if(v>peak)peak=v;}
  assert(peak>20000&&peak<=24000);
 }
 assert(feedback_samples(Feedback::CLICK)<1600);
 assert(feedback_allowed(60,false,false));
 assert(!feedback_allowed(0,false,false));assert(!feedback_allowed(60,true,false));assert(!feedback_allowed(60,false,true));
}
