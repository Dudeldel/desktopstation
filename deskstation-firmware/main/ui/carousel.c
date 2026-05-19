// carousel.c — 4-tile horizontal scroll-snap carousel below the top bar.
#include "carousel.h"
#include "dots.h"
#include "theme.h"
#include "top_bar.h"
#include "protocol.h"
#include "usb_cdc.h"

static lv_obj_t   *s_tv             = NULL;
static lv_obj_t   *s_tiles[CAROUSEL_TILES];
static int         s_active         = 0;
static bool        s_built          = false;
static lv_timer_t *s_autoscroll     = NULL;

/* Set to "autoscroll" by autoscroll_cb before calling carousel_set_active;
 * reset to "swipe" after the value-changed handler consumes it. */
static const char *s_pending_via    = "swipe";

/* ------------------------------------------------------------------ */
/* Forward declarations                                                 */
/* ------------------------------------------------------------------ */
static void _on_value_changed(lv_event_t *e);
static void _on_pressed(lv_event_t *e);
static void _on_gesture(lv_event_t *e);
static void autoscroll_cb(lv_timer_t *t);

/* ------------------------------------------------------------------ */
/* autoscroll_cb                                                        */
/* ------------------------------------------------------------------ */
static void autoscroll_cb(lv_timer_t *t)
{
    (void)t;
    /* Restore normal 10 s period (handles the one-shot 30 s grace window) */
    lv_timer_set_period(s_autoscroll, 10000);

    int next = (s_active + 1) % CAROUSEL_TILES;
    s_pending_via = "autoscroll";
    // Snap rather than animate. At 800×480 full_refresh on this hardware LVGL
    // only renders ~25 fps, so the ~300 ms slide animation breaks into ~7 large
    // visible steps that read as flicker rather than a smooth scroll. Snapping
    // also avoids the leftward-rewind on wrap (3 → 0).
    carousel_set_active(next, false);
}

/* ------------------------------------------------------------------ */
/* Touch handler — pause autoscroll until the user actually swipes.    */
/* Swiping completes via LV_EVENT_VALUE_CHANGED, which resumes the     */
/* timer afresh. A tap that doesn't lead to a swipe leaves the panel   */
/* on the user's current tile indefinitely — they're looking at it.    */
/* ------------------------------------------------------------------ */
static void _on_pressed(lv_event_t *e)
{
    (void)e;
    if (s_autoscroll) lv_timer_pause(s_autoscroll);
}

/* ------------------------------------------------------------------ */
/* Gesture handler — wrap around manual swipes at the carousel edges. */
/* LVGL's tileview hard-stops at the first/last tile; we want a swipe */
/* past the edge to snap to the opposite end, matching autoscroll.    */
/* ------------------------------------------------------------------ */
static void _on_gesture(lv_event_t *e)
{
    (void)e;
    lv_indev_t *indev = lv_indev_get_act();
    if (!indev) return;
    lv_dir_t dir = lv_indev_get_gesture_dir(indev);

    /* LV_DIR_LEFT = finger swept left = user wants the next-right tile.
     * LV_DIR_RIGHT = finger swept right = user wants the previous-left tile. */
    if (dir == LV_DIR_LEFT && s_active == CAROUSEL_TILES - 1) {
        lv_indev_wait_release(indev);
        s_pending_via = "swipe";
        carousel_set_active(0, false);
    } else if (dir == LV_DIR_RIGHT && s_active == 0) {
        lv_indev_wait_release(indev);
        s_pending_via = "swipe";
        carousel_set_active(CAROUSEL_TILES - 1, false);
    }
}

/* ------------------------------------------------------------------ */
/* Tile-change handler — update dot indicator + emit screen_changed     */
/* ------------------------------------------------------------------ */
static void _on_value_changed(lv_event_t *e)
{
    lv_obj_t *tv = lv_event_get_target(e);
    lv_coord_t sx = lv_obj_get_scroll_x(tv);
    int idx = (int)(sx / 800);
    if (idx < 0)               idx = 0;
    if (idx >= CAROUSEL_TILES) idx = CAROUSEL_TILES - 1;
    s_active = idx;

    /* Update dot indicator */
    dots_set_active(s_active);

    /* Emit screen_changed event to host */
    const char *via = s_pending_via;
    s_pending_via = "swipe";   /* reset for next manual swipe */

    usb_line_t line;
    int n = protocol_serialize_screen_changed_int(
                line.data, sizeof(line.data), s_active, via);
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }

    /* Re-arm the autoscroll: a successful tile change (manual swipe or wrap)
     * resumes the 10 s cycle. _on_pressed paused it; resuming here means a
     * tap-without-swipe stays paused, while a real swipe gets autoscroll back. */
    if (s_autoscroll) {
        lv_timer_set_period(s_autoscroll, 10000);
        lv_timer_reset(s_autoscroll);
        lv_timer_resume(s_autoscroll);
    }
}

/* ------------------------------------------------------------------ */
/* Public API                                                           */
/* ------------------------------------------------------------------ */

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

    /* Touch pauses autoscroll until a swipe completes */
    lv_obj_add_event_cb(s_tv, _on_pressed, LV_EVENT_PRESSED, NULL);

    /* Wrap manual swipes at the edges (LVGL tileview doesn't wrap by default) */
    lv_obj_add_event_cb(s_tv, _on_gesture, LV_EVENT_GESTURE, NULL);

    /* --- tiles: screen_N modules attach their content here in ui_build_main_screen --- */
    for (int i = 0; i < CAROUSEL_TILES; i++) {
        lv_obj_t *tile = lv_tileview_add_tile(s_tv, i, 0, LV_DIR_HOR);
        lv_obj_set_style_bg_color(tile, theme_bg(), 0);
        lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);
        s_tiles[i] = tile;
    }

    /* --- autoscroll timer (10 s) --- */
    s_autoscroll = lv_timer_create(autoscroll_cb, 10000, NULL);

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
    if (index < 0)               index = 0;
    if (index >= CAROUSEL_TILES) index = CAROUSEL_TILES - 1;
    s_active = index;
    lv_obj_set_tile_id(s_tv, index, 0, animate ? LV_ANIM_ON : LV_ANIM_OFF);
}

int carousel_active(void)
{
    return s_active;
}

void carousel_autoscroll_pause(void)
{
    if (s_autoscroll) lv_timer_pause(s_autoscroll);
}

void carousel_autoscroll_resume(void)
{
    if (s_autoscroll) lv_timer_resume(s_autoscroll);
}
