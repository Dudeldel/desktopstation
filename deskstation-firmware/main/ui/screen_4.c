// screen_4.c — Todo: vertical list of checkbox rows; tap emits todo_clicked.
#include "screen_4.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <string.h>

static bool      s_built = false;
static lv_obj_t *s_list  = NULL;

static void todo_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    const char *id = (const char *)lv_event_get_user_data(e);
    if (!id || !id[0]) return;

    usb_line_t line;
    int n = protocol_serialize_todo_clicked(line.data, sizeof(line.data), id);
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

static void add_row(lv_obj_t *parent, const todo_item_t *item)
{
    lv_obj_t *row = lv_btn_create(parent);
    lv_obj_set_width(row, lv_pct(100));
    lv_obj_set_height(row, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(row, theme_card(), 0);
    lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(row, 4, 0);
    lv_obj_set_style_pad_all(row, 10, 0);
    lv_obj_set_style_pad_column(row, 10, 0);
    lv_obj_set_style_shadow_width(row, 0, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t *box = lv_label_create(row);
    lv_label_set_text(box, item->done ? LV_SYMBOL_OK : LV_SYMBOL_BULLET);
    lv_obj_set_style_text_color(box,
        item->done ? theme_accent() : theme_text_dim(), 0);
    lv_obj_set_style_text_font(box, THEME_FONT_LARGE, 0);

    lv_obj_t *text = lv_label_create(row);
    lv_label_set_text(text, item->text);
    lv_label_set_long_mode(text, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(text, 680);
    lv_obj_set_style_text_color(text,
        item->done ? theme_text_dim() : theme_text(), 0);
    lv_obj_set_style_text_font(text, THEME_FONT_NORMAL, 0);

    char *id_copy = lv_mem_alloc(TODO_ID_MAX);
    if (id_copy) {
        strncpy(id_copy, item->id, TODO_ID_MAX - 1);
        id_copy[TODO_ID_MAX - 1] = '\0';
        lv_obj_add_event_cb(row, todo_clicked_cb, LV_EVENT_CLICKED, id_copy);
        lv_obj_add_event_cb(row, free_user_data_cb, LV_EVENT_DELETE, id_copy);
    }
}

void screen_4_init(lv_obj_t *tile)
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

void screen_4_update(const screen4_payload_t *data)
{
    if (!s_built || !data) return;
    lv_obj_clean(s_list);
    if (data->count == 0) {
        lv_obj_t *empty = lv_label_create(s_list);
        lv_label_set_text(empty, "Brak zadań");
        lv_obj_set_style_text_color(empty, theme_text_dim(), 0);
        return;
    }
    for (size_t i = 0; i < data->count; i++) add_row(s_list, &data->items[i]);
}
