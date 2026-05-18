// theme.h - Deskstation visual theme tokens (M2)
#pragma once
#include "lvgl.h"

// Colors (from docs/spec). Defined as functions because lv_color_t can be a
// runtime-built value depending on LV_COLOR_DEPTH; macros for these don't
// work cleanly across all LVGL build configs.
lv_color_t theme_bg(void);          // #0d0d10
lv_color_t theme_card(void);        // #16161a
lv_color_t theme_accent(void);      // #1d9e75
lv_color_t theme_text(void);        // #f0f0f0
lv_color_t theme_text_dim(void);    // #a0a0a0
lv_color_t theme_danger(void);      // #d9534f

// Font size aliases. Currently Montserrat (built into LVGL) — Polish glyphs
// will require swapping to a custom Inter subset converted via the LVGL Font
// Converter. See M2 plan task C6.
#define THEME_FONT_SMALL  (&lv_font_montserrat_14)
#define THEME_FONT_NORMAL (&lv_font_montserrat_16)
#define THEME_FONT_LARGE  (&lv_font_montserrat_20)
#define THEME_FONT_TITLE  (&lv_font_montserrat_28)

// Convenience: paint screen background, set default text color/font, zero padding.
void theme_apply_to_screen(lv_obj_t *scr);
