#include "toast.h"

#include <string.h>

static lv_obj_t *s_toast;
static lv_obj_t *s_label;
static lv_timer_t *s_hide_timer;

static void hide_timer_cb(lv_timer_t *t)
{
    (void)t;
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);
}

void toast_init(lv_obj_t *parent)
{
    s_toast = lv_obj_create(parent);
    lv_obj_set_size(s_toast, 600, 60);
    lv_obj_align(s_toast, LV_ALIGN_TOP_MID, 0, 20);
    lv_obj_add_flag(s_toast, LV_OBJ_FLAG_HIDDEN);

    s_label = lv_label_create(s_toast);
    lv_obj_center(s_label);
}

static lv_color_t color_for_level(const char *level)
{
    if (strcmp(level, "warn") == 0) return lv_palette_main(LV_PALETTE_YELLOW);
    if (strcmp(level, "error") == 0) return lv_palette_main(LV_PALETTE_RED);
    return lv_palette_main(LV_PALETTE_BLUE);
}

void toast_show(const char *text, const char *level)
{
    lv_label_set_text(s_label, text);
    lv_obj_set_style_bg_color(s_toast, color_for_level(level), 0);
    lv_obj_set_style_text_color(s_label, lv_color_white(), 0);
    lv_obj_clear_flag(s_toast, LV_OBJ_FLAG_HIDDEN);

    if (s_hide_timer) lv_timer_del(s_hide_timer);
    s_hide_timer = lv_timer_create(hide_timer_cb, 3000, NULL);
    lv_timer_set_repeat_count(s_hide_timer, 1);
}
