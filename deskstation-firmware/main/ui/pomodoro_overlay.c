// pomodoro_overlay.c — full-screen modal for active/paused pomodoro state.
//
// State mapping:
//   POMO_ACTIVE       → visible, header "POMODORO", buttons: pause + stop_with_log + cancel
//   POMO_PAUSED       → visible, header "PAUZA",     buttons: resume + stop_with_log + cancel
//   POMO_IDLE         → hidden
//   POMO_SHORT/LONG_BREAK → hidden (fullscreen_overlay handles break presentation)
#include "pomodoro_overlay.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

static lv_obj_t *s_root           = NULL;   // full-screen overlay on layer_top
static lv_obj_t *s_header_label   = NULL;
static lv_obj_t *s_task_label     = NULL;
static lv_obj_t *s_summary_label  = NULL;
static lv_obj_t *s_time_label     = NULL;
static lv_obj_t *s_counter_label  = NULL;
static lv_obj_t *s_primary_btn    = NULL;   // pause / resume — flips by state
static lv_obj_t *s_primary_lbl    = NULL;

static void format_mmss(int sec, char *out, size_t cap)
{
    if (sec < 0) sec = 0;
    int m = sec / 60;
    int s = sec % 60;
    snprintf(out, cap, "%02d:%02d", m, s);
}

static void send_action(const char *action)
{
    usb_line_t line;
    int n = protocol_serialize_pomodoro_action(line.data, sizeof(line.data), action);
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
}

static void primary_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    // The label text encodes intent: "PAUZA" → pause, "WZNÓW" → resume.
    const char *txt = lv_label_get_text(s_primary_lbl);
    if (txt && strcmp(txt, "WZNÓW") == 0) send_action("resume");
    else                                  send_action("pause");
}

static void stop_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    send_action("stop_with_log");
}

static void cancel_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    send_action("cancel");
}

static lv_obj_t *make_action_btn(lv_obj_t *parent, const char *label_text,
                                 lv_color_t bg, lv_event_cb_t cb,
                                 lv_obj_t **out_label)
{
    lv_obj_t *btn = lv_btn_create(parent);
    lv_obj_set_size(btn, 200, 60);
    lv_obj_set_style_bg_color(btn, bg, 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(btn, 8, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, NULL);

    lv_obj_t *lbl = lv_label_create(btn);
    lv_label_set_text(lbl, label_text);
    lv_obj_set_style_text_color(lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(lbl, THEME_FONT_LARGE, 0);
    lv_obj_center(lbl);

    if (out_label) *out_label = lbl;
    return btn;
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
    lv_obj_set_style_pad_all(s_root, 0, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(s_root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(s_root, 16, 0);

    s_header_label = lv_label_create(s_root);
    lv_label_set_text(s_header_label, "POMODORO");
    lv_obj_set_style_text_color(s_header_label, theme_accent(), 0);
    lv_obj_set_style_text_font(s_header_label, THEME_FONT_LARGE, 0);

    s_task_label = lv_label_create(s_root);
    lv_label_set_text(s_task_label, "");
    lv_obj_set_style_text_color(s_task_label, theme_text(), 0);
    lv_obj_set_style_text_font(s_task_label, THEME_FONT_LARGE, 0);

    s_summary_label = lv_label_create(s_root);
    lv_label_set_text(s_summary_label, "");
    lv_label_set_long_mode(s_summary_label, LV_LABEL_LONG_DOT);
    lv_obj_set_width(s_summary_label, 700);
    lv_obj_set_style_text_align(s_summary_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_summary_label, theme_text_dim(), 0);
    lv_obj_set_style_text_font(s_summary_label, THEME_FONT_NORMAL, 0);

    s_time_label = lv_label_create(s_root);
    lv_label_set_text(s_time_label, "25:00 / 25:00");
    lv_obj_set_style_text_color(s_time_label, theme_text(), 0);
    lv_obj_set_style_text_font(s_time_label, THEME_FONT_TITLE, 0);

    s_counter_label = lv_label_create(s_root);
    lv_label_set_text(s_counter_label, "");
    lv_obj_set_style_text_color(s_counter_label, theme_text_dim(), 0);
    lv_obj_set_style_text_font(s_counter_label, THEME_FONT_SMALL, 0);

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

    s_primary_btn = make_action_btn(row, "PAUZA", theme_accent(), primary_clicked_cb, &s_primary_lbl);
    make_action_btn(row, "STOP+LOG",  theme_accent(), stop_clicked_cb,   NULL);
    make_action_btn(row, "ANULUJ",    theme_danger(), cancel_clicked_cb, NULL);
}

bool pomodoro_overlay_visible(void)
{
    return s_root != NULL && !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

void pomodoro_overlay_update(const pomodoro_state_payload_t *data)
{
    if (!data) return;

    const bool should_show =
        (data->state == POMO_ACTIVE) || (data->state == POMO_PAUSED);

    if (!should_show) {
        if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    if (!s_root) build_overlay();
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);

    // Header + primary button reflect active vs paused.
    if (data->state == POMO_PAUSED) {
        lv_label_set_text(s_header_label, "PAUZA");
        lv_obj_set_style_text_color(s_header_label, theme_danger(), 0);
        lv_label_set_text(s_primary_lbl, "WZNÓW");
    } else {
        lv_label_set_text(s_header_label, "POMODORO");
        lv_obj_set_style_text_color(s_header_label, theme_accent(), 0);
        lv_label_set_text(s_primary_lbl, "PAUZA");
    }

    // Task identity
    if (data->has_task && data->task_key[0] != '\0') {
        lv_label_set_text(s_task_label, data->task_key);
    } else {
        lv_label_set_text(s_task_label, "(luźne)");
    }
    lv_label_set_text(s_summary_label, data->task_summary);

    // Timer (remaining / total)
    char rem[8], tot[8];
    format_mmss(data->remaining_sec, rem, sizeof(rem));
    format_mmss(data->total_sec, tot, sizeof(tot));
    lv_label_set_text_fmt(s_time_label, "%s / %s", rem, tot);

    // Today counter
    lv_label_set_text_fmt(s_counter_label, "Pomodoro #%d dzisiaj",
                          data->pomodoro_number_today);
}
