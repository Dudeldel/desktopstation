// macro_overlay.c — 4x3 grid of macro buttons, shown when MAKRO is tapped.
//
// Lifecycle mirrors lock_overlay: lazy-built on first show, lives on
// lv_layer_top, hidden by default. Tap anywhere outside the grid (on the
// dimmed background) closes the overlay; tap a grid cell fires its macro
// and closes.
#include "macro_overlay.h"
#include "theme.h"

#include "lvgl.h"

#include <stdbool.h>
#include <string.h>

#define GRID_COLS 4
#define GRID_ROWS 3

static lv_obj_t *s_root = NULL;   // full-screen dimmed background
static lv_obj_t *s_grid = NULL;   // inner grid container
static macro_overlay_trigger_cb_t s_trigger_cb = NULL;
static macro_list_payload_t s_list = {0};

static void close_cb(lv_event_t *e)
{
    (void)e;
    macro_overlay_hide();
}

static void cell_cb(lv_event_t *e)
{
    const char *id = (const char *)lv_event_get_user_data(e);
    if (id && id[0] && s_trigger_cb) {
        s_trigger_cb(id);
    }
    macro_overlay_hide();
}

static void rebuild_cells(void)
{
    if (!s_grid) return;
    lv_obj_clean(s_grid);

    // Static column / row descriptors — same memory each rebuild so LVGL's
    // layout pointers stay valid for the object's lifetime.
    static lv_coord_t col_dsc[GRID_COLS + 1] = {
        LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_TEMPLATE_LAST,
    };
    static lv_coord_t row_dsc[GRID_ROWS + 1] = {
        LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_TEMPLATE_LAST,
    };
    lv_obj_set_grid_dsc_array(s_grid, col_dsc, row_dsc);

    for (size_t i = 0; i < s_list.count && i < (size_t)(GRID_COLS * GRID_ROWS); i++) {
        const macro_list_item_t *item = &s_list.items[i];

        lv_obj_t *cell = lv_btn_create(s_grid);
        int col = (int)(i % GRID_COLS);
        int row = (int)(i / GRID_COLS);
        lv_obj_set_grid_cell(cell, LV_GRID_ALIGN_STRETCH, col, 1,
                                   LV_GRID_ALIGN_STRETCH, row, 1);
        lv_obj_set_style_radius(cell, 12, 0);
        lv_obj_set_style_bg_color(cell, theme_accent(), 0);
        lv_obj_set_style_bg_opa(cell, LV_OPA_COVER, 0);

        // user_data points at the id string baked into our static payload
        // copy, which lives as long as the overlay (i.e. forever after set).
        lv_obj_add_event_cb(cell, cell_cb, LV_EVENT_CLICKED, (void *)item->id);

        lv_obj_t *lbl = lv_label_create(cell);
        lv_label_set_text(lbl, item->label[0] ? item->label : item->id);
        lv_obj_set_style_text_color(lbl, theme_text(), 0);
        lv_obj_set_style_text_font(lbl, THEME_FONT_NORMAL, 0);
        lv_obj_center(lbl);
    }
}

static void build_overlay(void)
{
    s_root = lv_obj_create(lv_layer_top());
    lv_obj_set_size(s_root, 800, 480);
    lv_obj_set_pos(s_root, 0, 0);
    // Slightly dimmed (not opaque) so the lock overlay above us, if any,
    // still wins. Below the lock layer; above carousel/pomodoro.
    lv_obj_set_style_bg_color(s_root, theme_bg(), 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_80, 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 24, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    // Tap on background → close (analogous to clicking outside a modal).
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(s_root, close_cb, LV_EVENT_CLICKED, NULL);

    s_grid = lv_obj_create(s_root);
    lv_obj_set_size(s_grid, LV_PCT(100), LV_PCT(100));
    lv_obj_center(s_grid);
    lv_obj_set_style_bg_opa(s_grid, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_grid, 0, 0);
    lv_obj_set_style_pad_all(s_grid, 0, 0);
    lv_obj_set_style_pad_gap(s_grid, 16, 0);
    lv_obj_clear_flag(s_grid, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_layout(s_grid, LV_LAYOUT_GRID);

    lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

void macro_overlay_init(void)
{
    if (!s_root) build_overlay();
}

void macro_overlay_set_list(const macro_list_payload_t *list)
{
    if (!list) return;
    s_list = *list;  // value copy — payload is plain-old-data
    if (!s_root) build_overlay();
    rebuild_cells();
}

void macro_overlay_set_trigger_cb(macro_overlay_trigger_cb_t cb)
{
    s_trigger_cb = cb;
}

void macro_overlay_show(void)
{
    if (!s_root) build_overlay();
    if (s_list.count == 0) {
        // Nothing to show — staying hidden avoids an empty modal the user
        // can't get out of without an explicit close target.
        return;
    }
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);
}

void macro_overlay_hide(void)
{
    if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

bool macro_overlay_visible(void)
{
    if (!s_root) return false;
    return !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}
