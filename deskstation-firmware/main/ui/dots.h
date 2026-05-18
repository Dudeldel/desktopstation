// dots.h — 4-dot page indicator strip between top bar and carousel.
#pragma once
#include "lvgl.h"

#define DOTS_COUNT  4
#define DOTS_HEIGHT 8

// Build the dot strip inside `parent`. Positioned at y=TOP_BAR_HEIGHT (40),
// width 800, height DOTS_HEIGHT (8). Idempotent.
void dots_init(lv_obj_t *parent);

// Highlight one dot (0..DOTS_COUNT-1). All others are dimmed.
void dots_set_active(int idx);
