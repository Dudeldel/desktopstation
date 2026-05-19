// fullscreen_overlay.h — modal overlay for break / reminder fullscreens.
#pragma once
#include "lvgl.h"
#include "protocol.h"

// Show (lazy-built) / refresh the overlay from a parsed fullscreen payload.
void fullscreen_overlay_show(const fullscreen_payload_t *data);

// Hide the overlay without sending fullscreen_dismiss (used when the host
// transitions out of a break naturally, or for guard rails).
void fullscreen_overlay_hide(void);

// Returns true if the overlay is currently visible. Lets main.c decide
// whether to pause autoscroll.
bool fullscreen_overlay_visible(void);
