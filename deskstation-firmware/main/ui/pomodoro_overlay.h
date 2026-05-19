// pomodoro_overlay.h — Fullscreen modal shown while a pomodoro is active or paused.
#pragma once
#include "lvgl.h"
#include "protocol.h"

// Lazy-built (created on first update with state != idle). Hidden on idle.
void pomodoro_overlay_update(const pomodoro_state_payload_t *data);
