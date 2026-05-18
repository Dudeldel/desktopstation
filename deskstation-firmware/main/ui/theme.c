#include "theme.h"

lv_color_t theme_bg(void)       { return lv_color_make(0x0d, 0x0d, 0x10); }
lv_color_t theme_card(void)     { return lv_color_make(0x16, 0x16, 0x1a); }
lv_color_t theme_accent(void)   { return lv_color_make(0x1d, 0x9e, 0x75); }
lv_color_t theme_text(void)     { return lv_color_make(0xf0, 0xf0, 0xf0); }
lv_color_t theme_text_dim(void) { return lv_color_make(0xa0, 0xa0, 0xa0); }
lv_color_t theme_danger(void)   { return lv_color_make(0xd9, 0x53, 0x4f); }

void theme_apply_to_screen(lv_obj_t *scr)
{
    lv_obj_set_style_bg_color(scr, theme_bg(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, theme_text(), 0);
    lv_obj_set_style_text_font(scr, THEME_FONT_NORMAL, 0);
    lv_obj_set_style_pad_all(scr, 0, 0);
}
