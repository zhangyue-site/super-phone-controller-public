#pragma once
void controller_voice_init();
void controller_voice_hold(bool held);
void controller_voice_cancel();
int controller_voice_stage();
void controller_voice_changed(bool completed);
bool controller_voice_online();
bool controller_voice_upload(const unsigned char *pcm,unsigned size,unsigned sequence);

void controller_voice_test();
const char *controller_voice_session();
unsigned controller_voice_cancel_sequence();

bool controller_preflight_probe();

void controller_voice_prepare();
bool controller_voice_prepared();

#include <atomic>
struct VoiceStream {
 const unsigned char *pcm=nullptr;
 std::atomic<unsigned> bytes{0};
 std::atomic<bool> done{false},abort{false};
 std::atomic<int> result{0};
 std::atomic<int64_t> finished_at{0};
 unsigned sequence=0;
};
bool controller_voice_stream_upload(VoiceStream &stream);

#include "audio_policy.h"
void controller_audio_prompt(controller::SpeechPrompt prompt);
void controller_audio_interrupt();
int controller_audio_volume();
bool controller_audio_muted();
void controller_audio_adjust(int delta);
void controller_audio_toggle_mute();

void controller_voice_conversation();
bool controller_voice_conversing();

// End only this recording; keep the conversation and ADB task permission.
bool controller_voice_finish();

// Prevent telemetry from opening a second single-proxy socket during voice/remote work.
bool controller_voice_transport_busy();
bool controller_voice_background_http_begin();
void controller_voice_background_http_end();
