// carousel.h — 4-tile horizontal scroll-snap carousel below the top bar.
#pragma once
#include "lvgl.h"

#define CAROUSEL_TILES 4
#define CAROUSEL_HEIGHT 432  // 480 - 40 (top bar) - 8 (dots strip)

// Build the carousel inside `parent`. Positioned absolutely at y=48
// (below top bar + 8 px dot strip). Idempotent.
void carousel_init(lv_obj_t *parent);

// Return the inner tile object for `index` in [0, CAROUSEL_TILES). The
// screen modules (Phase C) attach their content to these tiles.
lv_obj_t *carousel_tile(int index);

// Programmatically set the active tile. Used by autoscroll (Task B6).
void carousel_set_active(int index, bool animate);

// Return current tile index 0..3 based on tileview's scroll position.
int carousel_active(void);
