// fullscreen_overlay.c — break / reminder modal. SKIP and OK send events.
//
// Layout:
//   - Full 800×480 panel on lv_layer_top with a kind-specific tinted background.
//   - Title (large) + message (normal) + submessage (small dim).
//   - mm:ss countdown derived from duration_sec (kept locally — host pushes the
//     payload once, firmware decrements until 0).
//   - SKIP button → pomodoro_action.action=skip_break
//   - OK button   → fullscreen_dismiss{kind} (only when dismissible=true)
#include "fullscreen_overlay.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

static lv_obj_t   *s_root         = NULL;
static lv_obj_t   *s_title_label  = NULL;
static lv_obj_t   *s_message_lbl  = NULL;
static lv_obj_t   *s_submsg_lbl   = NULL;
static lv_obj_t   *s_time_lbl     = NULL;
static lv_obj_t   *s_ok_btn       = NULL;
static lv_timer_t *s_count_timer  = NULL;
static int         s_remaining    = 0;
static char        s_kind_str[16] = {0};

static const char *kind_to_str(fullscreen_kind_t k)
{
    switch (k) {
        case FS_KIND_BREAK_SHORT: return "break_short";
        case FS_KIND_BREAK_LONG:  return "break_long";
        case FS_KIND_WATER:       return "water";
        case FS_KIND_EYES:        return "eyes";
        case FS_KIND_STANDUP:     return "standup";
    }
    return "break_short";
}

static lv_color_t kind_to_bg(fullscreen_kind_t k)
{
    // Greens for breaks; cooler tones for reminders. Keeps the carousel-dark
    // theme distinct from "you are on break" mood.
    switch (k) {
        case FS_KIND_BREAK_SHORT: return lv_color_make(0x14, 0x4a, 0x35);
        case FS_KIND_BREAK_LONG:  return lv_color_make(0x0e, 0x35, 0x26);
        case FS_KIND_WATER:       return lv_color_make(0x1d, 0x4a, 0x6e);
        case FS_KIND_EYES:        return lv_color_make(0x3a, 0x2a, 0x6e);
        case FS_KIND_STANDUP:     return lv_color_make(0x5a, 0x40, 0x1a);
    }
    return lv_color_make(0x14, 0x4a, 0x35);
}

static void format_mmss(int sec, char *out, size_t cap)
{
    if (sec < 0) sec = 0;
    int m = sec / 60;
    int s = sec % 60;
    snprintf(out, cap, "%02d:%02d", m, s);
}

static void send_skip_break(void)
{
    usb_line_t line;
    int n = protocol_serialize_pomodoro_action(line.data, sizeof(line.data), "skip_break");
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
}

static void send_fullscreen_dismiss(void)
{
    usb_line_t line;
    int n = protocol_serialize_fullscreen_dismiss(line.data, sizeof(line.data), s_kind_str);
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
}

static void skip_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    send_skip_break();
    // We do NOT hide here — wait for host to push the next pomodoro_state.
    // That keeps the overlay state machine driven by the host (per spec rule:
    // host pushes full snapshots, ESP sends events).
}

static void ok_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    send_fullscreen_dismiss();
}

static void count_timer_cb(lv_timer_t *t)
{
    (void)t;
    if (s_remaining > 0) s_remaining--;
    char buf[8];
    format_mmss(s_remaining, buf, sizeof(buf));
    if (s_time_lbl) lv_label_set_text(s_time_lbl, buf);
    if (s_remaining <= 0 && s_count_timer) {
        lv_timer_pause(s_count_timer);
    }
}

static void build_overlay(void)
{
    s_root = lv_obj_create(lv_layer_top());
    lv_obj_set_size(s_root, 800, 480);
    lv_obj_set_pos(s_root, 0, 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 24, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(s_root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(s_root, 12, 0);

    s_title_label = lv_label_create(s_root);
    lv_obj_set_style_text_color(s_title_label, lv_color_white(), 0);
    lv_obj_set_style_text_font(s_title_label, THEME_FONT_TITLE, 0);

    s_time_lbl = lv_label_create(s_root);
    lv_label_set_text(s_time_lbl, "00:00");
    lv_obj_set_style_text_color(s_time_lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(s_time_lbl, THEME_FONT_TITLE, 0);

    s_message_lbl = lv_label_create(s_root);
    lv_label_set_long_mode(s_message_lbl, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_message_lbl, 720);
    lv_obj_set_style_text_align(s_message_lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_message_lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(s_message_lbl, THEME_FONT_LARGE, 0);

    s_submsg_lbl = lv_label_create(s_root);
    lv_label_set_long_mode(s_submsg_lbl, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_submsg_lbl, 720);
    lv_obj_set_style_text_align(s_submsg_lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_submsg_lbl, lv_color_make(0xd0, 0xd0, 0xd0), 0);
    lv_obj_set_style_text_font(s_submsg_lbl, THEME_FONT_NORMAL, 0);

    // Button row
    lv_obj_t *row = lv_obj_create(s_root);
    lv_obj_set_size(row, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_pad_all(row, 0, 0);
    lv_obj_set_style_pad_column(row, 16, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *skip = lv_btn_create(row);
    lv_obj_set_size(skip, 180, 60);
    lv_obj_set_style_bg_color(skip, theme_danger(), 0);
    lv_obj_set_style_bg_opa(skip, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(skip, 8, 0);
    lv_obj_set_style_shadow_width(skip, 0, 0);
    lv_obj_add_event_cb(skip, skip_clicked_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *skip_lbl = lv_label_create(skip);
    lv_label_set_text(skip_lbl, "POMIŃ");
    lv_obj_set_style_text_color(skip_lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(skip_lbl, THEME_FONT_LARGE, 0);
    lv_obj_center(skip_lbl);

    s_ok_btn = lv_btn_create(row);
    lv_obj_set_size(s_ok_btn, 180, 60);
    lv_obj_set_style_bg_color(s_ok_btn, theme_accent(), 0);
    lv_obj_set_style_bg_opa(s_ok_btn, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(s_ok_btn, 8, 0);
    lv_obj_set_style_shadow_width(s_ok_btn, 0, 0);
    lv_obj_add_event_cb(s_ok_btn, ok_clicked_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *ok_lbl = lv_label_create(s_ok_btn);
    lv_label_set_text(ok_lbl, "OK");
    lv_obj_set_style_text_color(ok_lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(ok_lbl, THEME_FONT_LARGE, 0);
    lv_obj_center(ok_lbl);

    s_count_timer = lv_timer_create(count_timer_cb, 1000, NULL);
    lv_timer_pause(s_count_timer);
}

void fullscreen_overlay_show(const fullscreen_payload_t *data)
{
    if (!data) return;
    if (!s_root) build_overlay();

    // Background tint by kind
    lv_obj_set_style_bg_color(s_root, kind_to_bg(data->kind), 0);

    strncpy(s_kind_str, kind_to_str(data->kind), sizeof(s_kind_str) - 1);
    s_kind_str[sizeof(s_kind_str) - 1] = '\0';

    lv_label_set_text(s_title_label, data->title);
    lv_label_set_text(s_message_lbl, data->message);
    lv_label_set_text(s_submsg_lbl, data->submessage);

    s_remaining = data->duration_sec;
    char buf[8];
    format_mmss(s_remaining, buf, sizeof(buf));
    lv_label_set_text(s_time_lbl, buf);
    if (s_remaining > 0) lv_timer_resume(s_count_timer);
    else                 lv_timer_pause(s_count_timer);

    // OK button only when host allows dismissal.
    if (data->dismissible) lv_obj_clear_flag(s_ok_btn, LV_OBJ_FLAG_HIDDEN);
    else                   lv_obj_add_flag(s_ok_btn, LV_OBJ_FLAG_HIDDEN);

    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);
}

void fullscreen_overlay_hide(void)
{
    if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    if (s_count_timer) lv_timer_pause(s_count_timer);
}

bool fullscreen_overlay_visible(void)
{
    if (!s_root) return false;
    return !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}
