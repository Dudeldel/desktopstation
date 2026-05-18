#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

#define BOARD_LCD_WIDTH  800
#define BOARD_LCD_HEIGHT 480

// Initialize PSRAM-aware heap, RGB LCD panel, and GT911 touch controller.
// On success, populates *out_panel and *out_touch with handles.
esp_err_t board_init(esp_lcd_panel_handle_t *out_panel,
                     esp_lcd_touch_handle_t *out_touch);
