// macro_overlay.h — full-screen 4x3 grid overlay invoked by the MAKRO top-bar button.
//
// The host pushes a `macro_list` snapshot; the overlay caches the items and
// renders one button per item (up to MACRO_LIST_MAX = 12). Tapping a button
// fires the registered trigger callback with the item's id (which main.c
// turns into a `macro_trigger.name=<id>` line on the USB bridge) and then
// closes the overlay. Tapping outside the grid also closes the overlay.
#pragma once

#include "protocol.h"
#include <stdbool.h>

typedef void (*macro_overlay_trigger_cb_t)(const char *macro_id);

void macro_overlay_init(void);
void macro_overlay_set_list(const macro_list_payload_t *list);
void macro_overlay_set_trigger_cb(macro_overlay_trigger_cb_t cb);
void macro_overlay_show(void);
void macro_overlay_hide(void);
bool macro_overlay_visible(void);
