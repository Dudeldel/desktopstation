#include "toast.h"

#include <string.h>

// Lazy-built on toast_show, destroyed on hide. Keeping a hidden widget in the
// tree caused LVGL's screen-bg fill to skip the widget's bounding rectangle
// (covered-by-child optimization), leaving uninitialized framebuffer bytes
// visible there as a white bar until the toast was actually shown.
static lv_obj_t *s_parent;
static lv_obj_t *s_toast;
static lv_obj_t *s_label;
static lv_timer_t *s_hide_timer;

static void hide_timer_cb(lv_timer_t *t)
{
    (void)t;
    if (s_toast) {
        lv_obj_del(s_toast);
        s_toast = NULL;
        s_label = NULL;
    }
    s_hide_timer = NULL;
}

void toast_init(lv_obj_t *parent)
{
    s_parent = parent;
}

static lv_color_t color_for_level(const char *level)
{
    if (strcmp(level, "warn") == 0) return lv_palette_main(LV_PALETTE_YELLOW);
    if (strcmp(level, "error") == 0) return lv_palette_main(LV_PALETTE_RED);
    return lv_palette_main(LV_PALETTE_BLUE);
}

void toast_show(const char *text, const char *level)
{
    if (!s_parent) return;

    if (s_hide_timer) {
        lv_timer_del(s_hide_timer);
        s_hide_timer = NULL;
    }
    if (!s_toast) {
        s_toast = lv_obj_create(s_parent);
        lv_obj_set_size(s_toast, 600, 60);
        lv_obj_align(s_toast, LV_ALIGN_TOP_MID, 0, 20);
        s_label = lv_label_create(s_toast);
        lv_obj_center(s_label);
    }
    lv_label_set_text(s_label, text);
    lv_obj_set_style_bg_color(s_toast, color_for_level(level), 0);
    lv_obj_set_style_text_color(s_label, lv_color_white(), 0);

    s_hide_timer = lv_timer_create(hide_timer_cb, 3000, NULL);
    lv_timer_set_repeat_count(s_hide_timer, 1);
}
