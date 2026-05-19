// screen_2.c — Comms: scrollable notification list. Taps emit notification_clicked.
#include "screen_2.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <string.h>

static bool      s_built = false;
static lv_obj_t *s_list  = NULL;

static void notification_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    const char *id = (const char *)lv_event_get_user_data(e);
    if (!id || !id[0]) return;

    usb_line_t line;
    int n = protocol_serialize_notification_clicked(line.data, sizeof(line.data), id);
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
}

static void free_user_data_cb(lv_event_t *e)
{
    void *p = lv_event_get_user_data(e);
    if (p) lv_mem_free(p);
}

static lv_color_t source_color(const char *source)
{
    if (strcmp(source, "gmail") == 0)     return lv_color_make(0xea, 0x43, 0x35);
    if (strcmp(source, "chat") == 0)      return lv_color_make(0x4a, 0x90, 0xe2);
    if (strcmp(source, "messenger") == 0) return lv_color_make(0x00, 0x84, 0xff);
    if (strcmp(source, "whatsapp") == 0)  return lv_color_make(0x25, 0xd3, 0x66);
    return theme_text_dim();
}

static void add_notification(lv_obj_t *parent, const notification_t *n)
{
    lv_obj_t *card = lv_btn_create(parent);
    lv_obj_set_width(card, lv_pct(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(card, theme_card(), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 6, 0);
    lv_obj_set_style_pad_all(card, 8, 0);
    lv_obj_set_style_shadow_width(card, 0, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    // Top row: source pill + sender + time_ago
    lv_obj_t *top = lv_obj_create(card);
    lv_obj_set_size(top, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(top, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(top, 0, 0);
    lv_obj_set_style_pad_all(top, 0, 0);
    lv_obj_set_style_pad_column(top, 8, 0);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(top, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(top, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *pill = lv_label_create(top);
    lv_label_set_text(pill, n->source);
    lv_obj_set_style_text_color(pill, lv_color_white(), 0);
    lv_obj_set_style_text_font(pill, THEME_FONT_SMALL, 0);
    lv_obj_set_style_bg_color(pill, source_color(n->source), 0);
    lv_obj_set_style_bg_opa(pill, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(pill, 3, 0);
    lv_obj_set_style_pad_left(pill, 6, 0);
    lv_obj_set_style_pad_right(pill, 6, 0);
    lv_obj_set_style_pad_top(pill, 2, 0);
    lv_obj_set_style_pad_bottom(pill, 2, 0);

    lv_obj_t *sender = lv_label_create(top);
    lv_label_set_text(sender, n->sender);
    lv_label_set_long_mode(sender, LV_LABEL_LONG_DOT);
    lv_obj_set_width(sender, 480);
    lv_obj_set_style_text_color(sender, theme_text(), 0);
    lv_obj_set_style_text_font(sender, THEME_FONT_NORMAL, 0);

    lv_obj_t *when = lv_label_create(top);
    lv_label_set_text(when, n->time_ago);
    lv_obj_set_style_text_color(when, theme_text_dim(), 0);
    lv_obj_set_style_text_font(when, THEME_FONT_SMALL, 0);

    // Preview line
    lv_obj_t *prev = lv_label_create(card);
    lv_label_set_text(prev, n->preview);
    lv_label_set_long_mode(prev, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(prev, lv_pct(100));
    lv_obj_set_style_text_color(prev, theme_text_dim(), 0);
    lv_obj_set_style_text_font(prev, THEME_FONT_SMALL, 0);

    char *id_copy = lv_mem_alloc(NOTIF_ID_MAX);
    if (id_copy) {
        strncpy(id_copy, n->id, NOTIF_ID_MAX - 1);
        id_copy[NOTIF_ID_MAX - 1] = '\0';
        lv_obj_add_event_cb(card, notification_clicked_cb, LV_EVENT_CLICKED, id_copy);
        lv_obj_add_event_cb(card, free_user_data_cb, LV_EVENT_DELETE, id_copy);
    }
}

void screen_2_init(lv_obj_t *tile)
{
    if (s_built) return;
    s_built = true;

    s_list = lv_obj_create(tile);
    lv_obj_set_size(s_list, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(s_list, theme_bg(), 0);
    lv_obj_set_style_bg_opa(s_list, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_list, 0, 0);
    lv_obj_set_style_pad_all(s_list, 8, 0);
    lv_obj_set_style_pad_row(s_list, 6, 0);
    lv_obj_set_flex_flow(s_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_scroll_dir(s_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_list, LV_SCROLLBAR_MODE_AUTO);
}

void screen_2_update(const screen2_payload_t *data)
{
    if (!s_built || !data) return;
    lv_obj_clean(s_list);
    if (data->count == 0) {
        lv_obj_t *empty = lv_label_create(s_list);
        lv_label_set_text(empty, "Brak powiadomień");
        lv_obj_set_style_text_color(empty, theme_text_dim(), 0);
        return;
    }
    for (size_t i = 0; i < data->count; i++) {
        add_notification(s_list, &data->items[i]);
    }
}
