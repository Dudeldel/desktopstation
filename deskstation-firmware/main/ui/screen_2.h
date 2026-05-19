// screen_2.h — Comms: vertical list of notification cards.
#pragma once
#include "lvgl.h"
#include "protocol.h"

void screen_2_init(lv_obj_t *tile);
void screen_2_update(const screen2_payload_t *data);
