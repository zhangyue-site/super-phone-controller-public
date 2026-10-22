#include "voice.h"
#include "audio_feedback.h"
#include "audio_output_policy.h"
#include "conversation_policy.h"
#include "dialogue.h"
#include "usb.h"
#include "ota.h"
#include "ble_ota.h"
#include "remote_claim_policy.h"
#include "voice_lifecycle.h"
#include "touch.h"
#include "adb_local.h"
#include "sdkconfig.h"
#include <atomic>
#include <string.h>
#include <math.h>
#include "esp_random.h"
#include "nvs.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
static std::atomic<bool> held(false),cancelled(false),conversation(false);
static std::atomic<unsigned> conversation_turns(0);
static controller::VoiceLifecycle lifecycle;
// Serialize local start decisions with idle claim lease acquisition.
static std::atomic_flag start_guard=ATOMIC_FLAG_INIT;
static std::atomic<bool> background_http(false);
struct StartGuard {
 bool acquired;
 StartGuard():acquired(!start_guard.test_and_set()){}
 ~StartGuard(){if(acquired)start_guard.clear();}
};
static auto &conversation_epoch=lifecycle.epoch;
static auto &stage=lifecycle.stage;
static std::atomic<uint32_t> adb_consent(0);
static std::atomic<bool> diagnostic(false),prepare_only(false),manual_submit(false);
static TaskHandle_t worker,stream_worker;
static VoiceStream stream;
static void upload_run(void*){
 for(;;){ulTaskNotifyTake(pdTRUE,portMAX_DELAY);bool ok=controller_voice_stream_upload(stream);stream.result=ok?1:-1;}
}
static esp_codec_dev_handle_t mic;
static std::atomic<int> output_volume(100),pending_prompt(0);
static std::atomic<bool> output_muted(true),click_playing(false);
static std::atomic<unsigned> playback_epoch(0);
#define AUDIO_ASSET(name) extern const uint8_t name##_start[] asm("_binary_" #name "_pcm_start"); extern const uint8_t name##_end[] asm("_binary_" #name "_pcm_end");
AUDIO_ASSET(ready)
AUDIO_ASSET(recognized)
AUDIO_ASSET(failed)
AUDIO_ASSET(stopped)
AUDIO_ASSET(test)
static void save_audio(){
 nvs_handle_t h;if(nvs_open("audio",NVS_READWRITE,&h)!=ESP_OK)return;
 nvs_set_u8(h,"volume",output_volume.load());nvs_set_u8(h,"muted",output_muted.load());nvs_commit(h);nvs_close(h);
}
void controller_audio_interrupt(){playback_epoch.fetch_add(1);pending_prompt=0;}
int controller_audio_volume(){return output_volume.load();}
bool controller_audio_muted(){return output_muted.load();}
void controller_audio_adjust(int delta){int previous=output_volume.load();output_volume=controller::clamp_volume(previous+delta);save_audio();if(previous==0&&output_volume>0)controller_audio_prompt(controller::SpeechPrompt::CLICK);}
void controller_audio_toggle_mute(){output_muted=!output_muted.load();controller_audio_interrupt();save_audio();if(!output_muted)controller_audio_prompt(controller::SpeechPrompt::CLICK);}
void controller_audio_prompt(controller::SpeechPrompt value){
 if(!controller::feedback_allowed(output_volume,output_muted,held))return;
 if(lifecycle.busy && (value==controller::SpeechPrompt::CLICK||value==controller::SpeechPrompt::TEST||value==controller::SpeechPrompt::AUDIT))return;
 pending_prompt=(int)value;if(worker)xTaskNotifyGive(worker);
}

static bool attempted=false;
static char session[17];
static std::atomic<unsigned> next_sequence(1),record_sequence(0),cancel_sequence(0);
static void state(int value){stage=value;controller_voice_changed(false);}
static bool init_mic(){
 if(attempted)return mic!=nullptr;
 attempted=true;
 // V2 PA_EN is an active-low P-MOS supply for both ES8311 and amplifier.
 gpio_set_level(GPIO_NUM_42,0);vTaskDelay(pdMS_TO_TICKS(20));
 i2c_master_bus_handle_t bus=controller_i2c_bus();
 if(!bus)return false;
 if(i2c_master_probe(bus,0x18,100)!=ESP_OK){ESP_LOGW("voice","ES8311 not responding");return false;}
 i2s_chan_handle_t tx,rx;
 i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
 channel.dma_desc_num=controller::audio_dma_descriptors;channel.dma_frame_num=controller::audio_dma_frames;
 if(i2s_new_channel(&channel,&tx,&rx)!=ESP_OK)return false;
 i2s_std_config_t cfg={};cfg.clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(16000);
 cfg.slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO);
 cfg.gpio_cfg.mclk=GPIO_NUM_14;cfg.gpio_cfg.bclk=GPIO_NUM_15;cfg.gpio_cfg.ws=GPIO_NUM_38;
 cfg.gpio_cfg.dout=GPIO_NUM_45;cfg.gpio_cfg.din=GPIO_NUM_16;
 if(i2s_channel_init_std_mode(tx,&cfg)!=ESP_OK || i2s_channel_init_std_mode(rx,&cfg)!=ESP_OK)return false;
 audio_codec_i2c_cfg_t ctrlcfg={};ctrlcfg.port=0;ctrlcfg.addr=ES8311_CODEC_DEFAULT_ADDR;ctrlcfg.bus_handle=bus;
 auto ctrl=audio_codec_new_i2c_ctrl(&ctrlcfg);
 es8311_codec_cfg_t codec={};codec.ctrl_if=ctrl;codec.gpio_if=audio_codec_new_gpio();codec.codec_mode=ESP_CODEC_DEV_WORK_MODE_BOTH;
 codec.pa_pin=46;codec.hw_gain.pa_gain=controller::audio_pa_gain_db;codec.hw_gain.pa_voltage=3.3;codec.hw_gain.codec_dac_voltage=3.3;codec.use_mclk=true;
 auto cif=es8311_codec_new(&codec);
 audio_codec_i2s_cfg_t datacfg={};datacfg.port=0;datacfg.rx_handle=rx;datacfg.tx_handle=tx;
 auto data=audio_codec_new_i2s_data(&datacfg);
 if(!cif || !data)return false;
 esp_codec_dev_cfg_t dev={};dev.dev_type=ESP_CODEC_DEV_TYPE_IN_OUT;dev.codec_if=cif;dev.data_if=data;
 mic=esp_codec_dev_new(&dev);if(!mic)return false;
 ESP_LOGI("voice","ES8311 driver initialized; ADC remains closed until hold");return true;
}
static void audio_snapshot(const char *phase){
 int fmt=-1,mute=-1,volume=-1,power=-1,clock=-1;
 int rf=esp_codec_dev_read_reg(mic,0x09,&fmt),rm=esp_codec_dev_read_reg(mic,0x31,&mute);
 int rv=esp_codec_dev_read_reg(mic,0x32,&volume),rp=esp_codec_dev_read_reg(mic,0x12,&power),rc=esp_codec_dev_read_reg(mic,0x01,&clock);
 // Input-enable preserves the output driver and allows digital pad readback.
 int gp=gpio_input_enable(GPIO_NUM_46),ge=gpio_input_enable(GPIO_NUM_42);
 ESP_LOGI("voice","AUDIO HW %s power_en_n=%d pa_ctrl=%d gpio_rc=%d/%d fmt09=%02x dac31=%02x vol32=%02x power12=%02x clk01=%02x read_rc=%d/%d/%d/%d/%d",phase,gpio_get_level(GPIO_NUM_42),gpio_get_level(GPIO_NUM_46),ge,gp,fmt,mute,volume,power,clock,rf,rm,rv,rp,rc);
}
static bool configure_output_curve(){
 static bool configured=false;if(configured)return true;
 esp_codec_dev_vol_map_t points[]={{0,controller::audio_volume_floor_db},{100,controller::audio_volume_ceiling_db}};
 esp_codec_dev_vol_curve_t curve={};curve.vol_map=points;curve.count=2;
 configured=esp_codec_dev_set_vol_curve(mic,&curve)==ESP_CODEC_DEV_OK;
 return configured;
}
static bool play_pcm(const unsigned char *data,unsigned size,bool before_recording=false){
 if(!data||!size||(size%2)||size>960000||(held&&!before_recording)||!init_mic())return false;
 if(output_muted||output_volume==0)return true;
 unsigned epoch=playback_epoch.load();
 esp_codec_dev_sample_info_t fs={};fs.sample_rate=16000;fs.channel=2;fs.bits_per_sample=16;
 if(esp_codec_dev_open(mic,&fs)!=ESP_CODEC_DEV_OK)return false;
 if(!configure_output_curve()){esp_codec_dev_close(mic);return false;}
 // Match the working audit: stabilize DAC before asserting the PA.
 gpio_set_level(GPIO_NUM_46,0);
 int unmute_result=esp_codec_dev_set_out_mute(mic,false);
 ESP_LOGI("voice","AUDIO API unmute=%d",unmute_result);
 int16_t stereo[512];unsigned used=0;bool ok=true,io_ok=true;
 int64_t output_started=esp_timer_get_time();
 auto active=[&](){return (!held||before_recording)&&!output_muted&&output_volume>0&&epoch==playback_epoch.load();};
 auto silence=[&](unsigned frames){
  memset(stereo,0,sizeof(stereo));
  while(frames&&active()){
   unsigned count=frames>256?256:frames;
   if(esp_codec_dev_write(mic,stereo,count*4)!=ESP_CODEC_DEV_OK){io_ok=false;return false;}
   frames-=count;
  }
  return !frames;
 };
 int volume_result=esp_codec_dev_set_out_vol(mic,output_volume.load());
 ESP_LOGI("voice","AUDIO API volume=%d result=%d",output_volume.load(),volume_result);
 audio_snapshot("open");
 ok=silence(controller::audio_warmup_frames);
 if(ok&&active()){gpio_set_level(GPIO_NUM_46,1);ok=silence(4800);}
 audio_snapshot("pa_ready");
 while(ok&&used<size&&active()){
  unsigned n=(size-used)/2;if(n>256)n=256;
  for(unsigned i=0;i<n;i++){int16_t v=(int16_t)(data[used+2*i]|(data[used+2*i+1]<<8));stereo[2*i]=v;stereo[2*i+1]=v;}
  esp_codec_dev_set_out_vol(mic,output_volume.load());
  if(esp_codec_dev_write(mic,stereo,n*4)!=ESP_CODEC_DEV_OK){ok=false;io_ok=false;break;}
  used+=n*2;
 }
 // write() queues DMA; it does not wait for the last sample to reach the DAC.
 // Clock silence through the entire ring before muting/closing. Cancellation
 // bypasses the drain so STOP never waits for the tail.
 if(ok&&used==size&&active())ok=silence(controller::audio_tail_frames);
 ESP_LOGI("voice","OUTPUT bytes=%u/%u drained=%d interrupted=%d elapsed_ms=%lld",used,size,ok&&used==size,!active(),(long long)((esp_timer_get_time()-output_started)/1000));
 audio_snapshot("drained");
 esp_codec_dev_set_out_mute(mic,true);esp_codec_dev_close(mic);
 audio_snapshot("closed");
 return io_ok&&(!held||before_recording)&&(output_muted||output_volume==0||epoch==playback_epoch.load());
}
bool controller_audio_play_pcm(const unsigned char *data,unsigned size){return play_pcm(data,size);}
static void play_feedback(controller::Feedback cue,bool before_recording=false){
 static auto pcm=(int16_t*)heap_caps_malloc(4800*sizeof(int16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!pcm)return;
 int count=controller::feedback_samples(cue);
 int peak=0;
 for(int i=0;i<count;i++){pcm[i]=controller::feedback_sample(cue,i);if(abs(pcm[i])>peak)peak=abs(pcm[i]);}
 ESP_LOGI("voice","CUE id=%d frames=%d peak=%d",(int)cue,count,peak);
 play_pcm((const unsigned char*)pcm,count*2,before_recording);
}
static void audit_output(){
 if(held||!init_mic())return;
 unsigned epoch=playback_epoch.load();
 esp_codec_dev_sample_info_t fs={};fs.sample_rate=16000;fs.channel=2;fs.bits_per_sample=16;
 if(esp_codec_dev_open(mic,&fs)!=ESP_CODEC_DEV_OK)return;
 if(!configure_output_curve()){esp_codec_dev_close(mic);return;}
 esp_codec_dev_set_out_vol(mic,output_volume.load());esp_codec_dev_set_in_gain(mic,30);esp_codec_dev_set_out_mute(mic,false);
 static const int16_t sine[16]={0,12539,23170,30273,32767,30273,23170,12539,0,-12539,-23170,-30273,-32767,-30273,-23170,-12539};
 int16_t out[512],in[512];bool ok=true;
 for(int phase=0;phase<4&&ok;phase++){
  bool amp=phase>=2,tone=phase%2;gpio_set_level(GPIO_NUM_46,amp?1:0);
  int frames=tone?9600:4800,used=0;int64_t squares[2]={},si[2]={},sq[2]={};
  while(used<frames&&epoch==playback_epoch.load()&&!output_muted&&!held){
   int n=frames-used;if(n>256)n=256;
   for(int i=0;i<n;i++){int16_t value=tone?(int32_t)sine[(used+i)%16]*16000/32767:0;out[2*i]=out[2*i+1]=value;}
   if(esp_codec_dev_write(mic,out,n*4)!=ESP_CODEC_DEV_OK||esp_codec_dev_read(mic,in,n*4)!=ESP_CODEC_DEV_OK){ok=false;break;}
   for(int i=0;i<n;i++)for(int ch=0;ch<2;ch++){int64_t value=in[2*i+ch];squares[ch]+=value*value;si[ch]+=value*sine[(used+i)%16];sq[ch]+=value*sine[(used+i+4)%16];}
   used+=n;
  }
  if(used){
   double rms[2],bin[2];for(int ch=0;ch<2;ch++){rms[ch]=sqrt((double)squares[ch]/used);bin[ch]=2*hypot((double)si[ch],(double)sq[ch])/used/32767.;}
   ESP_LOGI("voice","AUDIO AUDIT amp=%d tone=%d frames=%d/%d left_rms=%.1f right_rms=%.1f left_1k=%.1f right_1k=%.1f pad46=%d",amp,tone,used,frames,rms[0],rms[1],bin[0],bin[1],gpio_get_level(GPIO_NUM_46));
  }
  if(used!=frames)break;
 }
 esp_codec_dev_set_out_mute(mic,true);esp_codec_dev_close(mic);
 ESP_LOGI("voice","AUDIO AUDIT finished ok=%d; samples discarded, no upload",ok);
}
static void play_prompt(int prompt){
 using controller::SpeechPrompt;using controller::Feedback;
 if(prompt==(int)SpeechPrompt::AUDIT){audit_output();return;}
 if(prompt==(int)SpeechPrompt::CLICK){click_playing=true;play_feedback(Feedback::CLICK,true);click_playing=false;return;}
 if(prompt==(int)SpeechPrompt::LISTEN){play_feedback(Feedback::LISTEN);return;}
 if(prompt==(int)SpeechPrompt::SUCCESS){play_feedback(Feedback::SUCCESS);return;}
 if(prompt==(int)SpeechPrompt::STOPPED){play_feedback(Feedback::STOP);return;}
 if(prompt==(int)SpeechPrompt::FAILED){play_feedback(Feedback::FAILURE);return;}
 const uint8_t *starts[]={nullptr,ready_start,recognized_start,failed_start,stopped_start,test_start};
 const uint8_t *ends[]={nullptr,ready_end,recognized_end,failed_end,stopped_end,test_end};
 if(prompt>=1&&prompt<=5)controller_audio_play_pcm(starts[prompt],ends[prompt]-starts[prompt]);
}
void controller_voice_state(int value){state(value);}
static void remote_idle(){
#if CONFIG_CONTROLLER_USB_LOCAL
 unsigned epoch=0,sequence=0;
 {
  StartGuard guard;if(!guard.acquired)return;
  if(background_http||controller_ota_busy()||ble_ota_busy())return;
  if(!controller::remote_claim_ready(lifecycle.can_start(),held,conversation,
       controller_voice_online(),controller_usb_hid_enabled(),controller_usb_ready()))return;
  if(diagnostic||prepare_only||pending_prompt)return;
  lifecycle.busy=true;epoch=conversation_epoch.load();
  cancelled=false;sequence=next_sequence.fetch_add(1);
 }
 {
  controller::VoiceLifecycle::Lease lease(lifecycle);
  bool claimed=controller_dialogue_remote_claim(sequence);
  if(!claimed||cancelled||!lifecycle.current(epoch))return;
  // Do not enable USB or ADB here: both retain their existing local consent.
  if(!controller_usb_hid_enabled()||!controller_usb_ready()){
   controller_voice_cancel();controller_release();return;
  }
  bool ok=controller_dialogue_remote_run(sequence);
  if(cancelled||!lifecycle.current(epoch))return;
  state(ok?3:5);if(ok)controller_voice_changed(true);
 }
#endif
}
static void run(void*){
 auto pcm=(int16_t*)heap_caps_malloc(320000,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 for(;;){
  if(!ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(3000))){remote_idle();continue;}
  int prompt=pending_prompt.exchange(0);
  if(prompt && (!held||prompt==(int)controller::SpeechPrompt::CLICK)){play_prompt(prompt);if(held)xTaskNotifyGive(worker);continue;}
  unsigned turn_epoch=conversation_epoch.load();
  bool test=diagnostic.exchange(false);
  bool prepare=prepare_only.exchange(false);
  if((!held || cancelled) && !test)continue;
  controller::VoiceLifecycle::Lease lease(lifecycle);
  if(cancelled||!lifecycle.current(turn_epoch))continue;
#if CONFIG_CONTROLLER_USB_LOCAL
  if(!test && (prepare || !controller_voice_prepared())){
   unsigned cancel_at_start=cancel_sequence.load();uint32_t consent=adb_consent.load();
   if(cancelled)continue;
   state(7);bool ready=controller_adb_activate(consent);
   if(ready && !cancelled && controller_voice_online())ready=controller_preflight_probe();
   if(!cancelled && cancel_sequence.load()==cancel_at_start){state(ready?8:9);held=false;if(ready&&controller_voice_prepared()){controller_audio_prompt(controller::SpeechPrompt::READY);}}
   if(ready&&controller_voice_prepared()&&conversation&&!cancelled&&lifecycle.current(turn_epoch)){
    pending_prompt=0;play_prompt((int)controller::SpeechPrompt::READY);vTaskDelay(pdMS_TO_TICKS(400));
    if(conversation&&!cancelled&&lifecycle.current(turn_epoch)){held=true;xTaskNotifyGive(worker);}
   }else if(lifecycle.current(turn_epoch))conversation=false;
   continue;
  }
#endif
  if(!test && prepare){state(6);held=false;continue;}
  if(!test && !controller_voice_online()){conversation=false;held=false;state(6);continue;}
  if(!pcm || !init_mic()){conversation=false;held=false;state(5);continue;}
  if(!test){
   play_feedback(controller::Feedback::LISTEN,true);
   if(cancelled||!held||!lifecycle.current(turn_epoch))continue;
  }
  unsigned sequence=record_sequence.load();
  state(4);unsigned count=0;int16_t stereo[512];
  esp_codec_dev_sample_info_t fs={};fs.sample_rate=16000;fs.channel=2;fs.bits_per_sample=16;
  if(esp_codec_dev_open(mic,&fs)!=ESP_CODEC_DEV_OK){conversation=false;held=false;state(5);continue;}
  esp_codec_dev_set_out_mute(mic,true);
  esp_codec_dev_set_in_gain(mic,30.0);
  if(!test){
   stream.pcm=(unsigned char*)pcm;stream.bytes=0;stream.done=false;stream.abort=false;stream.result=0;stream.finished_at=0;stream.sequence=sequence;
   xTaskNotifyGive(stream_worker);
  }
  // Every open restarts RX and resets its DMA queue; no pre-hold audio survives.
  // Discard codec startup transients while the local recording indicator prepares.
  bool warmed=true;
  for(int i=0;i<8 && !cancelled && (test || held);++i){
   if(esp_codec_dev_read(mic,stereo,sizeof(stereo))!=ESP_CODEC_DEV_OK){warmed=false;break;}
  }
  state(1);
  controller::ConversationVad vad;
  bool continuous=conversation.load();
  bool ok=warmed;
  while(ok && (test || held) && !cancelled && count<(test?16000u:160000u)){
   if(esp_codec_dev_read(mic,stereo,sizeof(stereo))!=ESP_CODEC_DEV_OK){ok=false;break;}
   if(cancelled || (!test && !held))break;
   for(unsigned i=0;i<256 && count<(test?16000u:160000u);++i)pcm[count++]=stereo[i*2];
   if(!test){stream.bytes=count*2;if(stream.result<0){ok=false;break;}}
   if(continuous){uint64_t energy=0;for(unsigned i=0;i<256;i++){int v=stereo[i*2];energy+=(int64_t)v*v;}if(vad.feed(256,(unsigned)sqrt((double)energy/256)))break;}
  }
  esp_codec_dev_close(mic);
  if(test){
   double squares=0;int peak=0;for(unsigned i=0;i<count;++i){int value=pcm[i];squares+=(double)value*value;if(abs(value)>peak)peak=abs(value);}
   ESP_LOGI("voice","MIC TEST samples=%u rms=%.1f peak=%d; audio discarded, no upload",count,count?sqrt(squares/count):0,peak);
   state(ok?0:5);continue;
  }
  bool submitted=manual_submit.exchange(false);
  bool speech=count>=6400&&(!continuous||vad.send(submitted));
  if(!speech&&!cancelled){
   // Nothing usable recorded (too short / VAD heard no voice): stop the live
   // upload and end the turn silently - no error screen, no failure cue.
   // Server-side tolerance would also absorb this, but skipping saves the
   // radio round-trip and keeps conversation turns from half-starting.
   stream.abort=true;stream.done=true;state(0);
   if(continuous){conversation=false;controller_audio_prompt(controller::SpeechPrompt::STOPPED);}
   continue;
  }
  stream.finished_at=esp_timer_get_time();stream.abort=cancelled||!ok;stream.done=true;
  if(!stream.abort)state(2);
  while(stream.result==0){if(cancelled)stream.abort=true;vTaskDelay(pdMS_TO_TICKS(10));}
  if(cancelled){state(0);continue;}
  if(!lifecycle.current(turn_epoch))continue;
  held=false;
  if(continuous&&!vad.send(submitted)){conversation=false;state(0);controller_audio_prompt(controller::SpeechPrompt::STOPPED);continue;}
  bool uploaded=stream.result==1;
  if(uploaded)uploaded=controller_dialogue_run(sequence);
  if(!lifecycle.current(turn_epoch)||cancelled)continue;
  state(uploaded?3:5);if(uploaded)controller_voice_changed(true);
  if(uploaded)play_feedback(controller::Feedback::SUCCESS);
  if(!lifecycle.current(turn_epoch)||cancelled)continue;
  if(continuous&&uploaded&&conversation&&lifecycle.current(turn_epoch)&&++conversation_turns<12){
   // Spoken reply has completed; keep a short acoustic guard before reopening RX.
   vTaskDelay(pdMS_TO_TICKS(400));
   if(conversation&&!cancelled&&lifecycle.current(turn_epoch)){record_sequence=next_sequence.fetch_add(1);manual_submit=false;held=true;xTaskNotifyGive(worker);}
  }else{conversation=false;if(!uploaded)controller_audio_prompt(controller::SpeechPrompt::FAILED);}
 }
}
void controller_voice_init(){
 // Every boot starts silent, including OTA from firmware that persisted muted=false.
 output_muted=true;
 nvs_handle_t h;if(nvs_open("audio",NVS_READONLY,&h)==ESP_OK){uint8_t v=100;nvs_get_u8(h,"volume",&v);output_volume=controller::clamp_volume(v)/20*20;nvs_close(h);}
 snprintf(session,sizeof(session),"%08x%08x",(unsigned)esp_random(),(unsigned)esp_random());xTaskCreate(upload_run,"voice_stream",8192,nullptr,3,&stream_worker);xTaskCreate(run,"voice",12288,nullptr,4,&worker);}
static void begin_voice_request(){
 if(!click_playing&&pending_prompt!=(int)controller::SpeechPrompt::CLICK)controller_audio_interrupt();
 controller_dialogue_screen(nullptr);
 manual_submit=false;adb_consent=controller_adb_ticket();record_sequence=next_sequence.fetch_add(1);cancelled=false;held=true;xTaskNotifyGive(worker);
}
void controller_voice_prepare(){
 StartGuard guard;if(!guard.acquired)return;
 if(!lifecycle.can_start())return;
 prepare_only=true;begin_voice_request();
}
void controller_voice_hold(bool value){
 if(!value){held=false;return;}
 StartGuard guard;if(!guard.acquired)return;
 if(!lifecycle.can_start())return;
 conversation=false;conversation_epoch.fetch_add(1);prepare_only=false;begin_voice_request();
}
bool controller_voice_finish(){
 if(stage.load()!=1||!held.load()||cancelled)return false;
 manual_submit=true;held=false;state(2);return true;
}
void controller_voice_cancel(){if(conversation||lifecycle.busy)controller_adb_cancel();lifecycle.cancel();controller_voice_changed(false);conversation=false;if(!click_playing&&pending_prompt!=(int)controller::SpeechPrompt::CLICK)controller_audio_interrupt();cancel_sequence=next_sequence.fetch_add(1);cancelled=true;held=false;}
int controller_voice_stage(){
#if CONFIG_CONTROLLER_USB_LOCAL
 if(stage>=7&&stage<=9){int adb=controller_adb_stage();return adb==3?8:(adb==1||adb==2)?7:(adb==0?0:9);}
#endif
 return stage.load();
}

void controller_voice_test(){StartGuard guard;if(!guard.acquired||!lifecycle.can_start())return;controller_audio_interrupt();cancelled=false;diagnostic=true;xTaskNotifyGive(worker);}

const char *controller_voice_session(){return session;}
unsigned controller_voice_cancel_sequence(){return cancel_sequence.load();}

bool controller_voice_conversing(){return conversation.load();}
void controller_voice_conversation(){
 StartGuard guard;if(!guard.acquired)return;
 if(!lifecycle.can_start())return;
 if(conversation)return;
 conversation_epoch.fetch_add(1);conversation_turns=0;conversation=true;prepare_only=false;begin_voice_request();
}

bool controller_voice_transport_busy(){return lifecycle.busy.load();}
bool controller_voice_background_http_begin(){
 StartGuard guard;if(!guard.acquired||background_http||lifecycle.busy||held||conversation||prepare_only||diagnostic)return false;
 background_http=true;return true;
}
void controller_voice_background_http_end(){background_http=false;}
