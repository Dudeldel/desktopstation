// lock_overlay.c — opaque modal shown while the host PC's screensaver is active.
//
// Sits on lv_layer_top (above carousel + pomodoro + fullscreen overlays) and
// absorbs all touch input so the panel cannot be operated while the host is
// locked. The host owns the state: ``lock_overlay_show()`` / ``lock_overlay_hide()``
// are invoked from the MSG_LOCK_STATE dispatch in main.c.
//
// Lazy-built on first show so widget construction races nothing on boot
// (matches fullscreen_overlay.c's lifecycle).
#include "lock_overlay.h"
#include "theme.h"

#include "lvgl.h"

#include <stdbool.h>

static lv_obj_t *s_root = NULL;

static void touch_swallow_cb(lv_event_t *e)
{
    // No-op. The mere presence of an LV_EVENT_CLICKED handler combined with
    // LV_OBJ_FLAG_CLICKABLE on the full-screen container is enough to absorb
    // touches so they never bubble to the carousel underneath.
    (void)e;
}

static void build_overlay(void)
{
    s_root = lv_obj_create(lv_layer_top());
    lv_obj_set_size(s_root, 800, 480);
    lv_obj_set_pos(s_root, 0, 0);
    lv_obj_set_style_bg_color(s_root, theme_bg(), 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 24, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(s_root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(s_root, 24, 0);

    // Touch absorption: clickable container + no-op handler means any tap on
    // the overlay terminates here instead of propagating to the carousel.
    // Clearing LV_OBJ_FLAG_GESTURE_BUBBLE prevents swipes from reaching the
    // carousel underneath (so the lock screen swallows screen-change gestures).
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(s_root, touch_swallow_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_GESTURE_BUBBLE);

    // Lock glyph — LV_SYMBOL_CLOSE is universally available in LVGL 8.x's
    // built-in FontAwesome subset. The project's Polish font does not embed
    // a dedicated lock glyph (U+F023), so we use CLOSE as a recognisable
    // "blocked" indicator and rely on the large Polish label below to carry
    // the meaning.
    lv_obj_t *icon = lv_label_create(s_root);
    lv_label_set_text(icon, LV_SYMBOL_CLOSE);
    lv_obj_set_style_text_color(icon, theme_text(), 0);
    lv_obj_set_style_text_font(icon, THEME_FONT_TITLE, 0);

    lv_obj_t *title = lv_label_create(s_root);
    lv_label_set_text(title, "EKRAN ZABLOKOWANY");
    lv_obj_set_style_text_color(title, theme_text(), 0);
    lv_obj_set_style_text_font(title, THEME_FONT_TITLE, 0);

    lv_obj_t *sub = lv_label_create(s_root);
    lv_label_set_text(sub, "Odblokuj komputer, aby kontynuować");
    lv_obj_set_style_text_color(sub, theme_text_dim(), 0);
    lv_obj_set_style_text_font(sub, THEME_FONT_NORMAL, 0);

    // Start hidden — only ``lock_overlay_show()`` reveals it.
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

void lock_overlay_init(void)
{
    if (!s_root) build_overlay();
}

void lock_overlay_show(void)
{
    if (!s_root) build_overlay();
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);
}

void lock_overlay_hide(void)
{
    if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

bool lock_overlay_visible(void)
{
    if (!s_root) return false;
    return !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}
