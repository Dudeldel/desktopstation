// dots.c — 4-dot page indicator strip between top bar and carousel.
#include "dots.h"
#include "theme.h"
#include "top_bar.h"

static lv_obj_t *s_dots[DOTS_COUNT];
static bool      s_built = false;

void dots_init(lv_obj_t *parent)
{
    if (s_built) return;

    /* Container: 800x8 at (0, TOP_BAR_HEIGHT) */
    lv_obj_t *cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 800, DOTS_HEIGHT);
    lv_obj_set_pos(cont, 0, TOP_BAR_HEIGHT);
    lv_obj_set_style_bg_color(cont, theme_bg(), 0);
    lv_obj_set_style_bg_opa(cont, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(cont, 0, 0);
    lv_obj_set_style_pad_all(cont, 0, 0);
    lv_obj_clear_flag(cont, LV_OBJ_FLAG_SCROLLABLE);

    /* Evenly space 4 dots across 800 px.
     * Section width = 800 / DOTS_COUNT = 200.
     * Dot centre = section_start + section_width/2.
     * Dot is 6x6 px so x = centre - 3, y = (8 - 6) / 2 = 1.
     */
    const int section_w = 800 / DOTS_COUNT;
    for (int i = 0; i < DOTS_COUNT; i++) {
        lv_obj_t *d = lv_obj_create(cont);
        lv_obj_set_size(d, 6, 6);
        lv_obj_set_pos(d, section_w * i + section_w / 2 - 3, 1);
        lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(d, 0, 0);
        lv_obj_set_style_pad_all(d, 0, 0);
        lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(d, theme_text_dim(), 0);
        lv_obj_clear_flag(d, LV_OBJ_FLAG_SCROLLABLE);
        s_dots[i] = d;
    }

    /* Highlight index 0 by default */
    lv_obj_set_style_bg_color(s_dots[0], theme_accent(), 0);

    s_built = true;
}

void dots_set_active(int idx)
{
    if (!s_built) return;
    if (idx < 0 || idx >= DOTS_COUNT) return;

    for (int i = 0; i < DOTS_COUNT; i++) {
        lv_obj_set_style_bg_color(s_dots[i],
            (i == idx) ? theme_accent() : theme_text_dim(), 0);
    }
}
