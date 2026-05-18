// carousel.c — 4-tile horizontal scroll-snap carousel below the top bar.
#include "carousel.h"
#include "theme.h"
#include "top_bar.h"

static lv_obj_t *s_tv        = NULL;
static lv_obj_t *s_tiles[CAROUSEL_TILES];
static int       s_active    = 0;
static bool      s_built     = false;

static void _on_value_changed(lv_event_t *e)
{
    lv_obj_t *tv = lv_event_get_target(e);
    lv_coord_t sx = lv_obj_get_scroll_x(tv);
    int idx = (int)(sx / 800);
    if (idx < 0)              idx = 0;
    if (idx >= CAROUSEL_TILES) idx = CAROUSEL_TILES - 1;
    s_active = idx;
}

void carousel_init(lv_obj_t *parent)
{
    if (s_built) return;

    /* --- tileview container --- */
    s_tv = lv_tileview_create(parent);
    lv_obj_set_size(s_tv, 800, CAROUSEL_HEIGHT);
    lv_obj_set_pos(s_tv, 0, TOP_BAR_HEIGHT + 8);
    lv_obj_set_style_bg_color(s_tv, theme_bg(), 0);
    lv_obj_set_style_bg_opa(s_tv, LV_OPA_COVER, 0);
    lv_obj_set_scrollbar_mode(s_tv, LV_SCROLLBAR_MODE_OFF);

    /* Track active index via scroll events */
    lv_obj_add_event_cb(s_tv, _on_value_changed, LV_EVENT_VALUE_CHANGED, NULL);

    /* --- tiles --- */
    for (int i = 0; i < CAROUSEL_TILES; i++) {
        lv_obj_t *tile = lv_tileview_add_tile(s_tv, i, 0, LV_DIR_HOR);
        lv_obj_set_style_bg_color(tile, theme_bg(), 0);
        lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);

        /* Placeholder label */
        lv_obj_t *label = lv_label_create(tile);
        lv_label_set_text_fmt(label, "Screen %d - TBD", i + 1);
        lv_obj_set_style_text_font(label, THEME_FONT_LARGE, 0);
        lv_obj_set_style_text_color(label, theme_text_dim(), 0);
        lv_obj_center(label);

        s_tiles[i] = tile;
    }

    s_built = true;
}

lv_obj_t *carousel_tile(int index)
{
    if (index < 0 || index >= CAROUSEL_TILES) return NULL;
    return s_tiles[index];
}

void carousel_set_active(int index, bool animate)
{
    if (!s_built) return;
    if (index < 0)              index = 0;
    if (index >= CAROUSEL_TILES) index = CAROUSEL_TILES - 1;
    s_active = index;
    lv_obj_set_tile_id(s_tv, index, 0, animate ? LV_ANIM_ON : LV_ANIM_OFF);
}

int carousel_active(void)
{
    return s_active;
}
