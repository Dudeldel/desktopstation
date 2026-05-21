// pomodoro_overlay.h — Fullscreen modal shown while a pomodoro is active or paused.
#pragma once
#include <stdbool.h>
#include "lvgl.h"
#include "protocol.h"

// Lazy-built (created on first update with state != idle). Hidden on idle.
void pomodoro_overlay_update(const pomodoro_state_payload_t *data);

// True when the overlay is currently shown (active or paused). Lets the
// dispatcher gate carousel autoscroll resume after the lock overlay comes
// down — we shouldn't restart autoscroll while a pomodoro is still on screen.
bool pomodoro_overlay_visible(void);
