#pragma once

/* One RGB LED.
 * White, solid then blink: reading a regular Wi-Fi network.
 * Green, 5 seconds then off: conversation can start.
 * Cyan, fast blink: recording while the button is held.
 * Yellow, solid: recording ended, waiting for a reply.
 * Blue, solid: first skill.
 * Purple, solid: another skill.
 * Red, three blinks then off: could not connect.
 */

void led_start(void);
void led_plugged(void);
void led_wifi_read(void);
void led_session_ready(void);
void led_await_reply(void);
void led_listen(void);
void led_skill(void);
void led_skill_other(void);
void led_fail(void);
void led_off(void);
