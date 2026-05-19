// screen_3.c — Dev: PR list (clickable) + standup checklist.
#include "screen_3.h"
#include "theme.h"
#include "protocol.h"
#include "usb_cdc.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <stdbool.h>
#include <string.h>

static bool      s_built     = false;
static lv_obj_t *s_col_prs   = NULL;
static lv_obj_t *s_col_stand = NULL;

static void pr_clicked_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    const char *id = (const char *)lv_event_get_user_data(e);
    if (!id || !id[0]) return;

    usb_line_t line;
    int n = protocol_serialize_pr_clicked(line.data, sizeof(line.data), id);
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

static lv_color_t status_color(const char *status)
{
    if (strcmp(status, "approved") == 0)           return theme_accent();
    if (strcmp(status, "needs_review") == 0)       return lv_color_make(0xe0, 0xa0, 0x40);
    if (strcmp(status, "changes_requested") == 0)  return theme_danger();
    return theme_text_dim();  // "open"
}

static lv_color_t ci_color(const char *ci)
{
    if (strcmp(ci, "passing") == 0) return theme_accent();
    if (strcmp(ci, "failing") == 0) return theme_danger();
    if (strcmp(ci, "running") == 0) return lv_color_make(0xe0, 0xa0, 0x40);
    return theme_text_dim();
}

static lv_obj_t *make_column(lv_obj_t *parent, const char *header_text)
{
    lv_obj_t *col = lv_obj_create(parent);
    lv_obj_set_size(col, 388, lv_pct(100));
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

static void add_pr_card(lv_obj_t *parent, const pull_request_t *pr)
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

    lv_obj_t *title = lv_label_create(card);
    lv_label_set_text(title, pr->title);
    lv_label_set_long_mode(title, LV_LABEL_LONG_DOT);
    lv_obj_set_width(title, lv_pct(100));
    lv_obj_set_style_text_color(title, theme_text(), 0);
    lv_obj_set_style_text_font(title, THEME_FONT_NORMAL, 0);

    lv_obj_t *meta = lv_label_create(card);
    lv_label_set_text_fmt(meta, "%s • %s", pr->repo, pr->author);
    lv_obj_set_style_text_color(meta, theme_text_dim(), 0);
    lv_obj_set_style_text_font(meta, THEME_FONT_SMALL, 0);

    lv_obj_t *badges = lv_obj_create(card);
    lv_obj_set_size(badges, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(badges, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(badges, 0, 0);
    lv_obj_set_style_pad_all(badges, 0, 0);
    lv_obj_set_style_pad_column(badges, 6, 0);
    lv_obj_set_flex_flow(badges, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(badges, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(badges, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *st = lv_label_create(badges);
    lv_label_set_text(st, pr->status);
    lv_obj_set_style_bg_color(st, status_color(pr->status), 0);
    lv_obj_set_style_bg_opa(st, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st, 3, 0);
    lv_obj_set_style_text_color(st, lv_color_white(), 0);
    lv_obj_set_style_text_font(st, THEME_FONT_SMALL, 0);
    lv_obj_set_style_pad_left(st, 6, 0);
    lv_obj_set_style_pad_right(st, 6, 0);
    lv_obj_set_style_pad_top(st, 2, 0);
    lv_obj_set_style_pad_bottom(st, 2, 0);

    lv_obj_t *ci = lv_label_create(badges);
    lv_label_set_text_fmt(ci, "CI: %s", pr->ci);
    lv_obj_set_style_bg_color(ci, ci_color(pr->ci), 0);
    lv_obj_set_style_bg_opa(ci, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(ci, 3, 0);
    lv_obj_set_style_text_color(ci, lv_color_white(), 0);
    lv_obj_set_style_text_font(ci, THEME_FONT_SMALL, 0);
    lv_obj_set_style_pad_left(ci, 6, 0);
    lv_obj_set_style_pad_right(ci, 6, 0);
    lv_obj_set_style_pad_top(ci, 2, 0);
    lv_obj_set_style_pad_bottom(ci, 2, 0);

    char *id_copy = lv_mem_alloc(PR_ID_MAX);
    if (id_copy) {
        strncpy(id_copy, pr->id, PR_ID_MAX - 1);
        id_copy[PR_ID_MAX - 1] = '\0';
        lv_obj_add_event_cb(card, pr_clicked_cb, LV_EVENT_CLICKED, id_copy);
        lv_obj_add_event_cb(card, free_user_data_cb, LV_EVENT_DELETE, id_copy);
    }
}

static void add_standup_row(lv_obj_t *parent, const standup_item_t *item)
{
    lv_obj_t *row = lv_obj_create(parent);
    lv_obj_set_size(row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(row, theme_card(), 0);
    lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_radius(row, 4, 0);
    lv_obj_set_style_pad_all(row, 6, 0);
    lv_obj_set_style_pad_column(row, 8, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *mark = lv_label_create(row);
    lv_label_set_text(mark, item->done ? LV_SYMBOL_OK : LV_SYMBOL_BULLET);
    lv_obj_set_style_text_color(mark,
        item->done ? theme_accent() : theme_text_dim(), 0);
    lv_obj_set_style_text_font(mark, THEME_FONT_NORMAL, 0);

    lv_obj_t *text = lv_label_create(row);
    lv_label_set_text(text, item->text);
    lv_label_set_long_mode(text, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(text, 320);
    lv_obj_set_style_text_color(text,
        item->done ? theme_text_dim() : theme_text(), 0);
    lv_obj_set_style_text_font(text, THEME_FONT_NORMAL, 0);
}

static void rebuild_prs(lv_obj_t *col, const pull_request_t *prs, size_t count)
{
    while (lv_obj_get_child_cnt(col) > 1) lv_obj_del(lv_obj_get_child(col, 1));
    if (count == 0) {
        lv_obj_t *empty = lv_label_create(col);
        lv_label_set_text(empty, "(brak)");
        lv_obj_set_style_text_color(empty, theme_text_dim(), 0);
        return;
    }
    for (size_t i = 0; i < count; i++) add_pr_card(col, &prs[i]);
}

static void rebuild_standup(lv_obj_t *col, const standup_item_t *items, size_t count)
{
    while (lv_obj_get_child_cnt(col) > 1) lv_obj_del(lv_obj_get_child(col, 1));
    if (count == 0) {
        lv_obj_t *empty = lv_label_create(col);
        lv_label_set_text(empty, "(brak)");
        lv_obj_set_style_text_color(empty, theme_text_dim(), 0);
        return;
    }
    for (size_t i = 0; i < count; i++) add_standup_row(col, &items[i]);
}

void screen_3_init(lv_obj_t *tile)
{
    if (s_built) return;
    s_built = true;

    lv_obj_t *root = lv_obj_create(tile);
    lv_obj_set_size(root, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(root, theme_bg(), 0);
    lv_obj_set_style_bg_opa(root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(root, 0, 0);
    lv_obj_set_style_pad_all(root, 6, 0);
    lv_obj_set_style_pad_column(root, 6, 0);
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_clear_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    s_col_prs   = make_column(root, "PULL REQUESTS");
    s_col_stand = make_column(root, "STANDUP");
}

void screen_3_update(const screen3_payload_t *data)
{
    if (!s_built || !data) return;
    rebuild_prs(s_col_prs, data->prs, data->pr_count);
    rebuild_standup(s_col_stand, data->standup, data->standup_count);
}
