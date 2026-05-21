// lock_overlay.h — opaque full-screen overlay shown when the host PC is locked.
// The overlay sits above every other UI layer (carousel, pomodoro, fullscreen)
// and absorbs all touch input so the panel cannot be operated while the host
// session is locked.
#pragma once
#include <stdbool.h>

void lock_overlay_init(void);
void lock_overlay_show(void);
void lock_overlay_hide(void);
bool lock_overlay_visible(void);
