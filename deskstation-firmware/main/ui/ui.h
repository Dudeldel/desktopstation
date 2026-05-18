#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

esp_err_t ui_init(esp_lcd_panel_handle_t panel, esp_lcd_touch_handle_t touch);
void ui_build_main_screen(void);
