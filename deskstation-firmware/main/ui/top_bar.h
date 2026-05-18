// top_bar.h — fixed top bar (40 px) showing host-driven status fields.
#pragma once
#include "lvgl.h"
#include "protocol.h"

#define TOP_BAR_HEIGHT 40

// Build the bar in `parent`. Idempotent — calling twice is allowed but only
// the first call adds widgets.
void top_bar_init(lv_obj_t *parent);

// Refresh from a parsed top_bar payload.
void top_bar_update(const top_bar_payload_t *data);

// Callback invoked when the MAKRO button is tapped. `name` is currently the
// label text ("MAKRO"); M6 will replace with a real macro picker.
typedef void (*top_bar_macro_handler_t)(const char *name);
void top_bar_set_macro_handler(top_bar_macro_handler_t handler);
