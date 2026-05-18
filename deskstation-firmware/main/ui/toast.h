#pragma once

#include "lvgl.h"

void toast_init(lv_obj_t *parent);
void toast_show(const char *text, const char *level);
