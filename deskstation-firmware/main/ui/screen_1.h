// screen_1.h — Jira screen: two columns of task cards + meeting bar.
#pragma once
#include "lvgl.h"
#include "protocol.h"

// Build the screen inside `tile`. Idempotent: container persists, contents
// get rebuilt on every update.
void screen_1_init(lv_obj_t *tile);

// Re-render from a parsed screen_1 payload.
void screen_1_update(const screen1_payload_t *data);
