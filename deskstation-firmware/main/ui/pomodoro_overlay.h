// pomodoro_overlay.h — Fullscreen modal shown while a pomodoro is running.
#pragma once
#include "lvgl.h"
#include "protocol.h"

// Lazy-built (created on first update with visible=true).
void pomodoro_overlay_update(const pomodoro_fullscreen_payload_t *data);
