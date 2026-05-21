#include "protocol.h"

#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "protocol";

static msg_type_t parse_type(const char *t)
{
    if (!t) return MSG_UNKNOWN;
    if (strcmp(t, "hello") == 0) return MSG_HELLO;
    if (strcmp(t, "heartbeat") == 0) return MSG_HEARTBEAT;
    if (strcmp(t, "toast") == 0) return MSG_TOAST;
    if (strcmp(t, "ack") == 0) return MSG_ACK;
    if (strcmp(t, "screen_changed") == 0) return MSG_SCREEN_CHANGED;
    if (strcmp(t, "top_bar") == 0) return MSG_TOP_BAR;
    if (strcmp(t, "screen_1") == 0) return MSG_SCREEN_1;
    if (strcmp(t, "screen_2") == 0) return MSG_SCREEN_2;
    if (strcmp(t, "screen_3") == 0) return MSG_SCREEN_3;
    if (strcmp(t, "screen_4") == 0) return MSG_SCREEN_4;
    if (strcmp(t, "pomodoro_state") == 0) return MSG_POMODORO_STATE;
    if (strcmp(t, "fullscreen") == 0) return MSG_FULLSCREEN;
    if (strcmp(t, "lock_state") == 0) return MSG_LOCK_STATE;
    if (strcmp(t, "macro_list") == 0) return MSG_MACRO_LIST;
    return MSG_UNKNOWN;
}

static pomo_state_t parse_pomo_state(const char *s)
{
    if (!s) return POMO_IDLE;
    if (strcmp(s, "active") == 0) return POMO_ACTIVE;
    if (strcmp(s, "paused") == 0) return POMO_PAUSED;
    if (strcmp(s, "short_break") == 0) return POMO_SHORT_BREAK;
    if (strcmp(s, "long_break") == 0) return POMO_LONG_BREAK;
    return POMO_IDLE;
}

static fullscreen_kind_t parse_fs_kind(const char *s)
{
    if (!s) return FS_KIND_BREAK_SHORT;
    if (strcmp(s, "break_short") == 0) return FS_KIND_BREAK_SHORT;
    if (strcmp(s, "break_long") == 0)  return FS_KIND_BREAK_LONG;
    if (strcmp(s, "water") == 0)       return FS_KIND_WATER;
    if (strcmp(s, "eyes") == 0)        return FS_KIND_EYES;
    if (strcmp(s, "standup") == 0)     return FS_KIND_STANDUP;
    return FS_KIND_BREAK_SHORT;
}

bool protocol_parse(const char *line, parsed_msg_t *out)
{
    cJSON *root = cJSON_Parse(line);
    if (!root) { ESP_LOGW(TAG, "malformed JSON"); return false; }

    bool ok = false;
    cJSON *v = cJSON_GetObjectItem(root, "v");
    if (!cJSON_IsNumber(v) || v->valueint != 1) {
        ESP_LOGW(TAG, "wrong version: %d", v ? v->valueint : -1);
        goto done;
    }

    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type)) { ESP_LOGW(TAG, "missing type"); goto done; }
    out->type = parse_type(type->valuestring);
    if (out->type == MSG_UNKNOWN) {
        ESP_LOGW(TAG, "unknown type: %s", type->valuestring);
        goto done;
    }

    cJSON *data = cJSON_GetObjectItem(root, "data");
    if (!cJSON_IsObject(data)) { ESP_LOGW(TAG, "missing data"); goto done; }

    if (out->type == MSG_TOAST) {
        cJSON *text = cJSON_GetObjectItem(data, "text");
        cJSON *level = cJSON_GetObjectItem(data, "level");
        if (!cJSON_IsString(text)) { ESP_LOGW(TAG, "toast missing text"); goto done; }
        strncpy(out->data.toast.text, text->valuestring, TEXT_MAX - 1);
        out->data.toast.text[TEXT_MAX - 1] = '\0';
        const char *lvl = (cJSON_IsString(level)) ? level->valuestring : "info";
        strncpy(out->data.toast.level, lvl, sizeof(out->data.toast.level) - 1);
        out->data.toast.level[sizeof(out->data.toast.level) - 1] = '\0';
    } else if (out->type == MSG_ACK) {
        cJSON *ref = cJSON_GetObjectItem(data, "ref");
        if (!cJSON_IsString(ref)) { ESP_LOGW(TAG, "ack missing ref"); goto done; }
        strncpy(out->data.ack.ref, ref->valuestring, sizeof(out->data.ack.ref) - 1);
        out->data.ack.ref[sizeof(out->data.ack.ref) - 1] = '\0';
    } else if (out->type == MSG_TOP_BAR) {
        cJSON *clock_j = cJSON_GetObjectItem(data, "clock");
        cJSON *date_j = cJSON_GetObjectItem(data, "date");
        cJSON *weather = cJSON_GetObjectItem(data, "weather");
        cJSON *cu = cJSON_GetObjectItem(data, "claude_usage");
        cJSON *pc = cJSON_GetObjectItem(data, "pomodoro_counter");
        cJSON *mbl = cJSON_GetObjectItem(data, "macro_button_label");
        if (!cJSON_IsString(clock_j) || !cJSON_IsString(date_j) || !cJSON_IsString(weather)
                || !cJSON_IsString(cu) || !cJSON_IsNumber(pc)) {
            ESP_LOGW(TAG, "top_bar missing fields");
            goto done;
        }
        strncpy(out->data.top_bar.clock, clock_j->valuestring, sizeof(out->data.top_bar.clock) - 1);
        out->data.top_bar.clock[sizeof(out->data.top_bar.clock) - 1] = '\0';
        strncpy(out->data.top_bar.date, date_j->valuestring, sizeof(out->data.top_bar.date) - 1);
        out->data.top_bar.date[sizeof(out->data.top_bar.date) - 1] = '\0';
        strncpy(out->data.top_bar.weather, weather->valuestring, sizeof(out->data.top_bar.weather) - 1);
        out->data.top_bar.weather[sizeof(out->data.top_bar.weather) - 1] = '\0';
        strncpy(out->data.top_bar.claude_usage, cu->valuestring, sizeof(out->data.top_bar.claude_usage) - 1);
        out->data.top_bar.claude_usage[sizeof(out->data.top_bar.claude_usage) - 1] = '\0';
        out->data.top_bar.pomodoro_counter = pc->valueint;
        const char *mbl_s = cJSON_IsString(mbl) ? mbl->valuestring : "MAKRO";
        strncpy(out->data.top_bar.macro_button_label, mbl_s, sizeof(out->data.top_bar.macro_button_label) - 1);
        out->data.top_bar.macro_button_label[sizeof(out->data.top_bar.macro_button_label) - 1] = '\0';
    } else if (out->type == MSG_SCREEN_1) {
        out->data.screen_1.today_count = 0;
        out->data.screen_1.queued_count = 0;
        memset(&out->data.screen_1.next_meeting, 0, sizeof(meeting_bar_t));

        cJSON *today = cJSON_GetObjectItem(data, "today_tasks");
        if (cJSON_IsArray(today)) {
            cJSON *item;
            cJSON_ArrayForEach(item, today) {
                if (out->data.screen_1.today_count >= SCREEN1_TASKS_MAX) break;
                cJSON *key_j = cJSON_GetObjectItem(item, "key");
                cJSON *sum_j = cJSON_GetObjectItem(item, "summary");
                cJSON *st_j  = cJSON_GetObjectItem(item, "status");
                cJSON *cur_j = cJSON_GetObjectItem(item, "is_current");
                if (!cJSON_IsString(key_j)) continue;
                size_t i = out->data.screen_1.today_count++;
                strncpy(out->data.screen_1.today_tasks[i].key, key_j->valuestring, JIRA_KEY_MAX - 1);
                out->data.screen_1.today_tasks[i].key[JIRA_KEY_MAX - 1] = '\0';
                if (cJSON_IsString(sum_j)) {
                    strncpy(out->data.screen_1.today_tasks[i].summary, sum_j->valuestring, JIRA_SUMMARY_MAX - 1);
                    out->data.screen_1.today_tasks[i].summary[JIRA_SUMMARY_MAX - 1] = '\0';
                }
                if (cJSON_IsString(st_j)) {
                    strncpy(out->data.screen_1.today_tasks[i].status, st_j->valuestring, JIRA_STATUS_MAX - 1);
                    out->data.screen_1.today_tasks[i].status[JIRA_STATUS_MAX - 1] = '\0';
                }
                out->data.screen_1.today_tasks[i].is_current = cJSON_IsTrue(cur_j);
            }
        }

        cJSON *queued = cJSON_GetObjectItem(data, "queued_tasks");
        if (cJSON_IsArray(queued)) {
            cJSON *item;
            cJSON_ArrayForEach(item, queued) {
                if (out->data.screen_1.queued_count >= SCREEN1_TASKS_MAX) break;
                cJSON *key_j = cJSON_GetObjectItem(item, "key");
                cJSON *sum_j = cJSON_GetObjectItem(item, "summary");
                cJSON *st_j  = cJSON_GetObjectItem(item, "status");
                cJSON *cur_j = cJSON_GetObjectItem(item, "is_current");
                if (!cJSON_IsString(key_j)) continue;
                size_t i = out->data.screen_1.queued_count++;
                strncpy(out->data.screen_1.queued_tasks[i].key, key_j->valuestring, JIRA_KEY_MAX - 1);
                out->data.screen_1.queued_tasks[i].key[JIRA_KEY_MAX - 1] = '\0';
                if (cJSON_IsString(sum_j)) {
                    strncpy(out->data.screen_1.queued_tasks[i].summary, sum_j->valuestring, JIRA_SUMMARY_MAX - 1);
                    out->data.screen_1.queued_tasks[i].summary[JIRA_SUMMARY_MAX - 1] = '\0';
                }
                if (cJSON_IsString(st_j)) {
                    strncpy(out->data.screen_1.queued_tasks[i].status, st_j->valuestring, JIRA_STATUS_MAX - 1);
                    out->data.screen_1.queued_tasks[i].status[JIRA_STATUS_MAX - 1] = '\0';
                }
                out->data.screen_1.queued_tasks[i].is_current = cJSON_IsTrue(cur_j);
            }
        }

        cJSON *mtg = cJSON_GetObjectItem(data, "next_meeting");
        if (cJSON_IsObject(mtg)) {
            cJSON *title_j   = cJSON_GetObjectItem(mtg, "title");
            cJSON *time_j    = cJSON_GetObjectItem(mtg, "time");
            cJSON *url_j     = cJSON_GetObjectItem(mtg, "join_url");
            cJSON *inmin_j   = cJSON_GetObjectItem(mtg, "in_minutes");
            if (cJSON_IsString(title_j)) {
                out->data.screen_1.next_meeting.present = true;
                strncpy(out->data.screen_1.next_meeting.title, title_j->valuestring, MEETING_TITLE_MAX - 1);
                out->data.screen_1.next_meeting.title[MEETING_TITLE_MAX - 1] = '\0';
                if (cJSON_IsString(time_j)) {
                    strncpy(out->data.screen_1.next_meeting.time, time_j->valuestring, MEETING_TIME_MAX - 1);
                    out->data.screen_1.next_meeting.time[MEETING_TIME_MAX - 1] = '\0';
                }
                if (cJSON_IsString(url_j)) {
                    strncpy(out->data.screen_1.next_meeting.join_url, url_j->valuestring, MEETING_URL_MAX - 1);
                    out->data.screen_1.next_meeting.join_url[MEETING_URL_MAX - 1] = '\0';
                }
                if (cJSON_IsNumber(inmin_j)) {
                    out->data.screen_1.next_meeting.in_minutes = inmin_j->valueint;
                }
            }
        }
    } else if (out->type == MSG_SCREEN_2) {
        out->data.screen_2.count = 0;
        cJSON *items = cJSON_GetObjectItem(data, "notifications");
        if (cJSON_IsArray(items)) {
            cJSON *item;
            cJSON_ArrayForEach(item, items) {
                if (out->data.screen_2.count >= SCREEN2_NOTIF_MAX) break;
                cJSON *src_j  = cJSON_GetObjectItem(item, "source");
                cJSON *snd_j  = cJSON_GetObjectItem(item, "sender");
                cJSON *prv_j  = cJSON_GetObjectItem(item, "preview");
                cJSON *ta_j   = cJSON_GetObjectItem(item, "time_ago");
                cJSON *id_j   = cJSON_GetObjectItem(item, "id");
                if (!cJSON_IsString(id_j)) continue;
                size_t i = out->data.screen_2.count++;
                strncpy(out->data.screen_2.items[i].id, id_j->valuestring, NOTIF_ID_MAX - 1);
                out->data.screen_2.items[i].id[NOTIF_ID_MAX - 1] = '\0';
                if (cJSON_IsString(src_j)) {
                    strncpy(out->data.screen_2.items[i].source, src_j->valuestring, NOTIF_SOURCE_MAX - 1);
                    out->data.screen_2.items[i].source[NOTIF_SOURCE_MAX - 1] = '\0';
                }
                if (cJSON_IsString(snd_j)) {
                    strncpy(out->data.screen_2.items[i].sender, snd_j->valuestring, NOTIF_SENDER_MAX - 1);
                    out->data.screen_2.items[i].sender[NOTIF_SENDER_MAX - 1] = '\0';
                }
                if (cJSON_IsString(prv_j)) {
                    strncpy(out->data.screen_2.items[i].preview, prv_j->valuestring, NOTIF_PREVIEW_MAX - 1);
                    out->data.screen_2.items[i].preview[NOTIF_PREVIEW_MAX - 1] = '\0';
                }
                if (cJSON_IsString(ta_j)) {
                    strncpy(out->data.screen_2.items[i].time_ago, ta_j->valuestring, NOTIF_TIME_MAX - 1);
                    out->data.screen_2.items[i].time_ago[NOTIF_TIME_MAX - 1] = '\0';
                }
            }
        }
    } else if (out->type == MSG_SCREEN_3) {
        out->data.screen_3.pr_count = 0;
        out->data.screen_3.standup_count = 0;

        cJSON *prs = cJSON_GetObjectItem(data, "prs");
        if (cJSON_IsArray(prs)) {
            cJSON *item;
            cJSON_ArrayForEach(item, prs) {
                if (out->data.screen_3.pr_count >= SCREEN3_PR_MAX) break;
                cJSON *id_j     = cJSON_GetObjectItem(item, "id");
                cJSON *title_j  = cJSON_GetObjectItem(item, "title");
                cJSON *author_j = cJSON_GetObjectItem(item, "author");
                cJSON *repo_j   = cJSON_GetObjectItem(item, "repo");
                cJSON *status_j = cJSON_GetObjectItem(item, "status");
                cJSON *ci_j     = cJSON_GetObjectItem(item, "ci");
                if (!cJSON_IsString(id_j)) continue;
                size_t i = out->data.screen_3.pr_count++;
                strncpy(out->data.screen_3.prs[i].id, id_j->valuestring, PR_ID_MAX - 1);
                out->data.screen_3.prs[i].id[PR_ID_MAX - 1] = '\0';
                if (cJSON_IsString(title_j)) {
                    strncpy(out->data.screen_3.prs[i].title, title_j->valuestring, PR_TITLE_MAX - 1);
                    out->data.screen_3.prs[i].title[PR_TITLE_MAX - 1] = '\0';
                }
                if (cJSON_IsString(author_j)) {
                    strncpy(out->data.screen_3.prs[i].author, author_j->valuestring, PR_AUTHOR_MAX - 1);
                    out->data.screen_3.prs[i].author[PR_AUTHOR_MAX - 1] = '\0';
                }
                if (cJSON_IsString(repo_j)) {
                    strncpy(out->data.screen_3.prs[i].repo, repo_j->valuestring, PR_REPO_MAX - 1);
                    out->data.screen_3.prs[i].repo[PR_REPO_MAX - 1] = '\0';
                }
                if (cJSON_IsString(status_j)) {
                    strncpy(out->data.screen_3.prs[i].status, status_j->valuestring, PR_STATUS_MAX - 1);
                    out->data.screen_3.prs[i].status[PR_STATUS_MAX - 1] = '\0';
                }
                if (cJSON_IsString(ci_j)) {
                    strncpy(out->data.screen_3.prs[i].ci, ci_j->valuestring, PR_STATUS_MAX - 1);
                    out->data.screen_3.prs[i].ci[PR_STATUS_MAX - 1] = '\0';
                }
            }
        }

        cJSON *standup = cJSON_GetObjectItem(data, "standup");
        if (cJSON_IsArray(standup)) {
            cJSON *item;
            cJSON_ArrayForEach(item, standup) {
                if (out->data.screen_3.standup_count >= SCREEN3_STANDUP_MAX) break;
                cJSON *text_j = cJSON_GetObjectItem(item, "text");
                cJSON *done_j = cJSON_GetObjectItem(item, "done");
                if (!cJSON_IsString(text_j)) continue;
                size_t i = out->data.screen_3.standup_count++;
                strncpy(out->data.screen_3.standup[i].text, text_j->valuestring, STANDUP_TEXT_MAX - 1);
                out->data.screen_3.standup[i].text[STANDUP_TEXT_MAX - 1] = '\0';
                out->data.screen_3.standup[i].done = cJSON_IsTrue(done_j);
            }
        }
    } else if (out->type == MSG_SCREEN_4) {
        out->data.screen_4.count = 0;
        cJSON *items = cJSON_GetObjectItem(data, "items");
        if (cJSON_IsArray(items)) {
            cJSON *item;
            cJSON_ArrayForEach(item, items) {
                if (out->data.screen_4.count >= SCREEN4_ITEM_MAX) break;
                cJSON *id_j   = cJSON_GetObjectItem(item, "id");
                cJSON *text_j = cJSON_GetObjectItem(item, "text");
                cJSON *done_j = cJSON_GetObjectItem(item, "done");
                if (!cJSON_IsString(id_j)) continue;
                size_t i = out->data.screen_4.count++;
                strncpy(out->data.screen_4.items[i].id, id_j->valuestring, TODO_ID_MAX - 1);
                out->data.screen_4.items[i].id[TODO_ID_MAX - 1] = '\0';
                if (cJSON_IsString(text_j)) {
                    strncpy(out->data.screen_4.items[i].text, text_j->valuestring, TODO_TEXT_MAX - 1);
                    out->data.screen_4.items[i].text[TODO_TEXT_MAX - 1] = '\0';
                }
                out->data.screen_4.items[i].done = cJSON_IsTrue(done_j);
            }
        }
    } else if (out->type == MSG_POMODORO_STATE) {
        cJSON *state_j   = cJSON_GetObjectItem(data, "state");
        cJSON *rem_j     = cJSON_GetObjectItem(data, "remaining_sec");
        cJSON *tot_j     = cJSON_GetObjectItem(data, "total_sec");
        cJSON *key_j     = cJSON_GetObjectItem(data, "task_key");
        cJSON *sum_j     = cJSON_GetObjectItem(data, "task_summary");
        cJSON *num_j     = cJSON_GetObjectItem(data, "pomodoro_number_today");
        if (!cJSON_IsString(state_j)) {
            ESP_LOGW(TAG, "pomodoro_state missing state");
            goto done;
        }
        out->data.pomo_state.state = parse_pomo_state(state_j->valuestring);
        out->data.pomo_state.remaining_sec = cJSON_IsNumber(rem_j) ? rem_j->valueint : 0;
        out->data.pomo_state.total_sec     = cJSON_IsNumber(tot_j) ? tot_j->valueint : 0;
        out->data.pomo_state.pomodoro_number_today = cJSON_IsNumber(num_j) ? num_j->valueint : 0;
        if (cJSON_IsString(key_j)) {
            out->data.pomo_state.has_task = true;
            strncpy(out->data.pomo_state.task_key, key_j->valuestring, JIRA_KEY_MAX - 1);
            out->data.pomo_state.task_key[JIRA_KEY_MAX - 1] = '\0';
        } else {
            out->data.pomo_state.has_task = false;
            out->data.pomo_state.task_key[0] = '\0';
        }
        if (cJSON_IsString(sum_j)) {
            strncpy(out->data.pomo_state.task_summary, sum_j->valuestring, POMO_SUMMARY_MAX - 1);
            out->data.pomo_state.task_summary[POMO_SUMMARY_MAX - 1] = '\0';
        } else {
            out->data.pomo_state.task_summary[0] = '\0';
        }
    } else if (out->type == MSG_FULLSCREEN) {
        cJSON *kind_j  = cJSON_GetObjectItem(data, "kind");
        cJSON *title_j = cJSON_GetObjectItem(data, "title");
        cJSON *msg_j   = cJSON_GetObjectItem(data, "message");
        cJSON *sub_j   = cJSON_GetObjectItem(data, "submessage");
        cJSON *dur_j   = cJSON_GetObjectItem(data, "duration_sec");
        cJSON *act_j   = cJSON_GetObjectItem(data, "activities");
        cJSON *dism_j  = cJSON_GetObjectItem(data, "dismissible");
        if (!cJSON_IsString(kind_j) || !cJSON_IsString(title_j)) {
            ESP_LOGW(TAG, "fullscreen missing kind/title");
            goto done;
        }
        out->data.fullscreen.kind = parse_fs_kind(kind_j->valuestring);
        strncpy(out->data.fullscreen.title, title_j->valuestring, FS_TITLE_MAX - 1);
        out->data.fullscreen.title[FS_TITLE_MAX - 1] = '\0';
        if (cJSON_IsString(msg_j)) {
            strncpy(out->data.fullscreen.message, msg_j->valuestring, FS_MSG_MAX - 1);
            out->data.fullscreen.message[FS_MSG_MAX - 1] = '\0';
        } else {
            out->data.fullscreen.message[0] = '\0';
        }
        if (cJSON_IsString(sub_j)) {
            strncpy(out->data.fullscreen.submessage, sub_j->valuestring, FS_MSG_MAX - 1);
            out->data.fullscreen.submessage[FS_MSG_MAX - 1] = '\0';
        } else {
            out->data.fullscreen.submessage[0] = '\0';
        }
        out->data.fullscreen.duration_sec = cJSON_IsNumber(dur_j) ? dur_j->valueint : 0;
        out->data.fullscreen.dismissible  = cJSON_IsBool(dism_j) ? cJSON_IsTrue(dism_j) : true;

        out->data.fullscreen.activity_count = 0;
        if (cJSON_IsArray(act_j)) {
            cJSON *item;
            cJSON_ArrayForEach(item, act_j) {
                if (out->data.fullscreen.activity_count >= FS_ACTIVITIES_MAX) break;
                if (!cJSON_IsString(item)) continue;
                size_t i = out->data.fullscreen.activity_count++;
                strncpy(out->data.fullscreen.activities[i], item->valuestring,
                        sizeof(out->data.fullscreen.activities[i]) - 1);
                out->data.fullscreen.activities[i][sizeof(out->data.fullscreen.activities[i]) - 1] = '\0';
            }
        }
    } else if (out->type == MSG_LOCK_STATE) {
        cJSON *locked_j = cJSON_GetObjectItem(data, "locked");
        if (!cJSON_IsBool(locked_j)) {
            ESP_LOGW(TAG, "lock_state missing locked");
            goto done;
        }
        out->data.lock_state.locked = cJSON_IsTrue(locked_j);
    } else if (out->type == MSG_MACRO_LIST) {
        out->data.macro_list.count = 0;
        cJSON *macros_arr = cJSON_GetObjectItem(data, "macros");
        if (cJSON_IsArray(macros_arr)) {
            cJSON *item = NULL;
            cJSON_ArrayForEach(item, macros_arr) {
                if (out->data.macro_list.count >= MACRO_LIST_MAX) break;
                if (!cJSON_IsObject(item)) continue;
                cJSON *id_j    = cJSON_GetObjectItem(item, "id");
                cJSON *label_j = cJSON_GetObjectItem(item, "label");
                if (!cJSON_IsString(id_j) || !cJSON_IsString(label_j)) continue;
                size_t i = out->data.macro_list.count++;
                macro_list_item_t *slot = &out->data.macro_list.items[i];
                strncpy(slot->id, id_j->valuestring, MACRO_ID_MAX - 1);
                slot->id[MACRO_ID_MAX - 1] = '\0';
                strncpy(slot->label, label_j->valuestring, MACRO_LABEL_MAX - 1);
                slot->label[MACRO_LABEL_MAX - 1] = '\0';
                // icon/color/subtitle fields are accepted on the wire but
                // ignored in this MVP render (label-only buttons).
            }
        }
    }

    ok = true;
done:
    cJSON_Delete(root);
    return ok;
}

int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"hello\",\"data\":{\"firmware_version\":\"%s\","
        "\"free_heap\":%u,\"psram_free\":%u}}",
        firmware_version,
        (unsigned)esp_get_free_heap_size(),
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
}

int protocol_serialize_heartbeat(char *buf, size_t cap)
{
    return snprintf(buf, cap, "{\"v\":1,\"type\":\"heartbeat\",\"data\":{}}");
}

int protocol_serialize_task_clicked(char *buf, size_t cap, const char *key)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"task_clicked\",\"data\":{\"key\":\"%s\"}}", key);
}

int protocol_serialize_pr_clicked(char *buf, size_t cap, const char *id)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"pr_clicked\",\"data\":{\"id\":\"%s\"}}", id);
}

int protocol_serialize_notification_clicked(char *buf, size_t cap, const char *id)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"notification_clicked\",\"data\":{\"id\":\"%s\"}}", id);
}

int protocol_serialize_todo_clicked(char *buf, size_t cap, const char *id)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"todo_clicked\",\"data\":{\"id\":\"%s\"}}", id);
}

int protocol_serialize_macro_trigger(char *buf, size_t cap, const char *name)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"macro_trigger\",\"data\":{\"name\":\"%s\"}}", name);
}

int protocol_serialize_pomodoro_action(char *buf, size_t cap, const char *action)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"pomodoro_action\",\"data\":{\"action\":\"%s\"}}", action);
}

int protocol_serialize_screen_changed_int(char *buf, size_t cap, int screen, const char *via)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"screen_changed\",\"data\":{\"screen\":%d,\"via\":\"%s\"}}", screen, via);
}

int protocol_serialize_fullscreen_dismiss(char *buf, size_t cap, const char *kind)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"fullscreen_dismiss\",\"data\":{\"kind\":\"%s\"}}", kind);
}
