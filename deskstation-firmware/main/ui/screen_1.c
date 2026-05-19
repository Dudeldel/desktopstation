// screen_1.c — Jira: two task columns + meeting bar. Taps emit task_clicked.
#include "screen_1.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <string.h>

static bool      s_built       = false;
static lv_obj_t *s_col_today   = NULL;
static lv_obj_t *s_col_queued  = NULL;
static lv_obj_t *s_meeting_bar = NULL;     // recreated on each update
static lv_obj_t *s_root        = NULL;

static void task_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    const char *key = (const char *)lv_event_get_user_data(e);
    if (!key || !key[0]) return;

    usb_line_t line;
    int n = protocol_serialize_task_clicked(line.data, sizeof(line.data), key);
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

static void meeting_join_cb(lv_event_t *e)
{
    // M2: no real action — host side handles the URL on a future event type.
    // For now, treat tap on meeting bar as a no-op (logged via touch).
    (void)e;
}

// Build a static column container with a column header label.
static lv_obj_t *make_column(lv_obj_t *parent, const char *header_text)
{
    lv_obj_t *col = lv_obj_create(parent);
    lv_obj_set_size(col, 388, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_style_bg_color(col, theme_bg(), 0);
    lv_obj_set_style_bg_opa(col, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(col, 0, 0);
    lv_obj_set_style_pad_all(col, 6, 0);
    lv_obj_set_style_pad_row(col, 6, 0);
    lv_obj_set_scroll_dir(col, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(col, LV_SCROLLBAR_MODE_OFF);

    lv_obj_t *hdr = lv_label_create(col);
    lv_label_set_text(hdr, header_text);
    lv_obj_set_style_text_color(hdr, theme_text_dim(), 0);
    lv_obj_set_style_text_font(hdr, THEME_FONT_SMALL, 0);
    return col;
}

static void add_task_card(lv_obj_t *parent, const jira_task_t *task)
{
    // Clickable card. user_data is a stable pointer into the persistent payload
    // copy held on screen_1's own static buffer (see s_keys below).
    lv_obj_t *card = lv_btn_create(parent);
    lv_obj_set_width(card, lv_pct(100));
    lv_obj_set_height(card, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(card, task->is_current ? theme_accent() : theme_card(), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 6, 0);
    lv_obj_set_style_pad_all(card, 8, 0);
    lv_obj_set_style_shadow_width(card, 0, 0);

    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    // Top row: key + status
    lv_obj_t *top = lv_label_create(card);
    lv_label_set_text_fmt(top, "%s  •  %s", task->key, task->status);
    lv_obj_set_style_text_color(top, task->is_current ? theme_text() : theme_text_dim(), 0);
    lv_obj_set_style_text_font(top, THEME_FONT_SMALL, 0);

    // Summary
    lv_obj_t *sum = lv_label_create(card);
    lv_label_set_text(sum, task->summary);
    lv_label_set_long_mode(sum, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(sum, lv_pct(100));
    lv_obj_set_style_text_color(sum, theme_text(), 0);
    lv_obj_set_style_text_font(sum, THEME_FONT_NORMAL, 0);

    // Click handler — pass `key` via user_data. The key string lives inside the
    // card itself by allocating it through LVGL's user_data pointer; LVGL does
    // not free it for us, so we store it on the card via a custom property.
    // Simpler: store key in a child label and read it back in the handler.
    // To keep things robust, we strdup via lv_mem_alloc and free on delete.
    char *key_copy = lv_mem_alloc(JIRA_KEY_MAX);
    if (key_copy) {
        strncpy(key_copy, task->key, JIRA_KEY_MAX - 1);
        key_copy[JIRA_KEY_MAX - 1] = '\0';
        lv_obj_add_event_cb(card, task_clicked_cb, LV_EVENT_CLICKED, key_copy);
        // Free the strdup'd key when the card is deleted to avoid leaks on rebuild.
        lv_obj_add_event_cb(card, free_user_data_cb, LV_EVENT_DELETE, key_copy);
    }
}

static void rebuild_column(lv_obj_t *col, const jira_task_t *tasks, size_t count)
{
    // Wipe everything except the header (first child).
    while (lv_obj_get_child_cnt(col) > 1) {
        lv_obj_del(lv_obj_get_child(col, 1));
    }
    for (size_t i = 0; i < count; i++) {
        add_task_card(col, &tasks[i]);
    }
    if (count == 0) {
        lv_obj_t *empty = lv_label_create(col);
        lv_label_set_text(empty, "(brak)");
        lv_obj_set_style_text_color(empty, theme_text_dim(), 0);
        lv_obj_set_style_text_font(empty, THEME_FONT_SMALL, 0);
    }
}

static void rebuild_meeting_bar(const meeting_bar_t *mtg)
{
    if (s_meeting_bar) {
        lv_obj_del(s_meeting_bar);
        s_meeting_bar = NULL;
    }
    if (!mtg || !mtg->present) return;

    s_meeting_bar = lv_obj_create(s_root);
    lv_obj_set_size(s_meeting_bar, lv_pct(100), 56);
    lv_obj_set_style_bg_color(s_meeting_bar, theme_card(), 0);
    lv_obj_set_style_bg_opa(s_meeting_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_meeting_bar, 0, 0);
    lv_obj_set_style_radius(s_meeting_bar, 6, 0);
    lv_obj_set_style_pad_all(s_meeting_bar, 8, 0);
    lv_obj_set_flex_flow(s_meeting_bar, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_meeting_bar,
                          LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_add_event_cb(s_meeting_bar, meeting_join_cb, LV_EVENT_CLICKED, NULL);

    lv_obj_t *left = lv_label_create(s_meeting_bar);
    lv_label_set_text_fmt(left, "%s  •  %s", mtg->title, mtg->time);
    lv_label_set_long_mode(left, LV_LABEL_LONG_DOT);
    lv_obj_set_width(left, 600);
    lv_obj_set_style_text_color(left, theme_text(), 0);
    lv_obj_set_style_text_font(left, THEME_FONT_NORMAL, 0);

    lv_obj_t *right = lv_label_create(s_meeting_bar);
    if (mtg->in_minutes < 0) {
        lv_label_set_text(right, "TRWA");
    } else {
        lv_label_set_text_fmt(right, "za %d min", mtg->in_minutes);
    }
    lv_obj_set_style_text_color(right,
        mtg->in_minutes < 0 ? theme_danger() : theme_accent(), 0);
    lv_obj_set_style_text_font(right, THEME_FONT_NORMAL, 0);
}

void screen_1_init(lv_obj_t *tile)
{
    if (s_built) return;
    s_built = true;

    s_root = lv_obj_create(tile);
    lv_obj_set_size(s_root, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(s_root, theme_bg(), 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 6, 0);
    lv_obj_set_style_pad_row(s_root, 6, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_set_flex_flow(s_root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    // Two-column area on top
    lv_obj_t *cols = lv_obj_create(s_root);
    lv_obj_set_size(cols, lv_pct(100), 350);
    lv_obj_set_style_bg_opa(cols, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(cols, 0, 0);
    lv_obj_set_style_pad_all(cols, 0, 0);
    lv_obj_set_style_pad_column(cols, 6, 0);
    lv_obj_set_flex_flow(cols, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(cols, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_clear_flag(cols, LV_OBJ_FLAG_SCROLLABLE);

    s_col_today  = make_column(cols, "DZIŚ");
    s_col_queued = make_column(cols, "KOLEJKA");
    lv_obj_set_height(s_col_today, lv_pct(100));
    lv_obj_set_height(s_col_queued, lv_pct(100));
}

void screen_1_update(const screen1_payload_t *data)
{
    if (!s_built || !data) return;
    rebuild_column(s_col_today,  data->today_tasks,  data->today_count);
    rebuild_column(s_col_queued, data->queued_tasks, data->queued_count);
    rebuild_meeting_bar(&data->next_meeting);
}
