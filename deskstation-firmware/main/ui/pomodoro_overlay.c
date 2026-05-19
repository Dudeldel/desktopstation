// pomodoro_overlay.c — modal over the carousel. STOP sends pomodoro_action.
#include "pomodoro_overlay.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <stdio.h>

static lv_obj_t *s_root        = NULL;   // full-screen overlay
static lv_obj_t *s_task_label  = NULL;
static lv_obj_t *s_time_label  = NULL;

static void format_mmss(int sec, char *out, size_t cap)
{
    if (sec < 0) sec = 0;
    int m = sec / 60;
    int s = sec % 60;
    snprintf(out, cap, "%02d:%02d", m, s);
}

static void stop_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    usb_line_t line;
    int n = protocol_serialize_pomodoro_action(line.data, sizeof(line.data), "stop");
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
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
    lv_obj_set_style_pad_row(s_root, 24, 0);

    lv_obj_t *hdr = lv_label_create(s_root);
    lv_label_set_text(hdr, "POMODORO");
    lv_obj_set_style_text_color(hdr, theme_accent(), 0);
    lv_obj_set_style_text_font(hdr, THEME_FONT_NORMAL, 0);

    s_task_label = lv_label_create(s_root);
    lv_label_set_text(s_task_label, "");
    lv_obj_set_style_text_color(s_task_label, theme_text(), 0);
    lv_obj_set_style_text_font(s_task_label, THEME_FONT_LARGE, 0);

    s_time_label = lv_label_create(s_root);
    lv_label_set_text(s_time_label, "00:00 / 25:00");
    lv_obj_set_style_text_color(s_time_label, theme_text(), 0);
    lv_obj_set_style_text_font(s_time_label, THEME_FONT_TITLE, 0);

    lv_obj_t *btn = lv_btn_create(s_root);
    lv_obj_set_size(btn, 200, 60);
    lv_obj_set_style_bg_color(btn, theme_danger(), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(btn, 8, 0);
    lv_obj_set_style_shadow_width(btn, 0, 0);
    lv_obj_add_event_cb(btn, stop_clicked_cb, LV_EVENT_CLICKED, NULL);

    lv_obj_t *btn_lbl = lv_label_create(btn);
    lv_label_set_text(btn_lbl, "STOP");
    lv_obj_set_style_text_color(btn_lbl, lv_color_white(), 0);
    lv_obj_set_style_text_font(btn_lbl, THEME_FONT_LARGE, 0);
    lv_obj_center(btn_lbl);
}

void pomodoro_overlay_update(const pomodoro_fullscreen_payload_t *data)
{
    if (!data) return;

    if (!data->visible) {
        if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    if (!s_root) build_overlay();
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);

    if (data->task_key[0] != '\0') {
        lv_label_set_text(s_task_label, data->task_key);
    } else {
        lv_label_set_text(s_task_label, "(no task)");
    }

    char el[8], tot[8];
    format_mmss(data->elapsed_sec, el, sizeof(el));
    format_mmss(data->total_sec, tot, sizeof(tot));
    lv_label_set_text_fmt(s_time_label, "%s / %s", el, tot);
}
