#include "top_bar.h"
#include "theme.h"

#include <stdbool.h>
#include <string.h>

static bool s_built = false;

static lv_obj_t *s_label_clock;
static lv_obj_t *s_label_date;
static lv_obj_t *s_label_weather;
static lv_obj_t *s_label_usage;
static lv_obj_t *s_label_pomodoro;
static lv_obj_t *s_label_macro;   // label inside the MAKRO button

static top_bar_macro_handler_t s_handler = NULL;

static void macro_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code != LV_EVENT_CLICKED) return;
    if (s_handler && s_label_macro) {
        s_handler(lv_label_get_text(s_label_macro));
    }
}

// Helper: create a label child of `parent` with theme defaults.
static lv_obj_t *make_label(lv_obj_t *parent, const char *initial_text)
{
    lv_obj_t *lbl = lv_label_create(parent);
    lv_label_set_text(lbl, initial_text);
    lv_obj_set_style_text_color(lbl, theme_text(), 0);
    lv_obj_set_style_text_font(lbl, THEME_FONT_NORMAL, 0);
    return lbl;
}

void top_bar_init(lv_obj_t *parent)
{
    if (s_built) return;
    s_built = true;

    // ── container ────────────────────────────────────────────────────────────
    lv_obj_t *bar = lv_obj_create(parent);
    lv_obj_set_size(bar, 800, TOP_BAR_HEIGHT);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);

    // Background: matches screen — seamless look.
    lv_obj_set_style_bg_color(bar, theme_bg(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);

    // Bottom border: 1 px dim line as visual separator.
    lv_obj_set_style_border_side(bar, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(bar, theme_text_dim(), 0);
    lv_obj_set_style_border_width(bar, 1, 0);

    // No rounded corners, no extra shadow.
    lv_obj_set_style_radius(bar, 0, 0);

    // Padding: 8 px horizontal, 0 px vertical.
    lv_obj_set_style_pad_left(bar, 8, 0);
    lv_obj_set_style_pad_right(bar, 8, 0);
    lv_obj_set_style_pad_top(bar, 0, 0);
    lv_obj_set_style_pad_bottom(bar, 0, 0);
    lv_obj_set_style_pad_column(bar, 0, 0);

    // Flex layout: horizontal row, space-between, center-aligned vertically.
    lv_obj_set_flex_flow(bar, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(bar,
                          LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);

    // Disable scroll — the bar is fixed height and should never scroll.
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

    // ── labels ───────────────────────────────────────────────────────────────
    s_label_clock    = make_label(bar, "--:--");
    s_label_date     = make_label(bar, "---");
    s_label_weather  = make_label(bar, "---");
    s_label_usage    = make_label(bar, "---");
    s_label_pomodoro = make_label(bar, "P: 0");

    // ── MAKRO button ─────────────────────────────────────────────────────────
    lv_obj_t *btn = lv_btn_create(bar);
    lv_obj_set_height(btn, TOP_BAR_HEIGHT - 6);  // 34 px — small vertical margin
    lv_obj_set_style_bg_color(btn, theme_accent(), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(btn, 4, 0);
    lv_obj_set_style_pad_left(btn, 10, 0);
    lv_obj_set_style_pad_right(btn, 10, 0);
    lv_obj_set_style_pad_top(btn, 0, 0);
    lv_obj_set_style_pad_bottom(btn, 0, 0);
    lv_obj_add_event_cb(btn, macro_btn_event_cb, LV_EVENT_CLICKED, NULL);

    s_label_macro = lv_label_create(btn);
    lv_label_set_text(s_label_macro, "MAKRO");
    lv_obj_set_style_text_color(s_label_macro, theme_text(), 0);
    lv_obj_set_style_text_font(s_label_macro, THEME_FONT_NORMAL, 0);
    lv_obj_center(s_label_macro);
}

void top_bar_update(const top_bar_payload_t *data)
{
    if (!s_built || !data) return;

    lv_label_set_text_fmt(s_label_clock,    "%s", data->clock);
    lv_label_set_text_fmt(s_label_date,     "%s", data->date);
    lv_label_set_text_fmt(s_label_weather,  "%s", data->weather);
    lv_label_set_text_fmt(s_label_usage,    "%s", data->claude_usage);
    lv_label_set_text_fmt(s_label_pomodoro, "P: %d", data->pomodoro_counter);

    // Update macro button label if the host supplies an override.
    if (data->macro_button_label[0] != '\0') {
        lv_label_set_text(s_label_macro, data->macro_button_label);
    }
}

void top_bar_set_macro_handler(top_bar_macro_handler_t handler)
{
    s_handler = handler;
}
