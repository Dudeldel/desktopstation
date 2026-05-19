#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

esp_err_t ui_init(esp_lcd_panel_handle_t panel, esp_lcd_touch_handle_t touch);
void ui_build_main_screen(void);

// Spawn the LVGL renderer task on core 1. Must be called AFTER
// ui_build_main_screen() so widget construction (which runs on core 0 / main
// task) doesn't race with lvgl_task's first refresh — that race corrupts
// LVGL's TLSF heap and manifests as intermittent StoreProhibited panics
// during early boot.
esp_err_t ui_start_lvgl_task(void);
