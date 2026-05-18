#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    MSG_HELLO,
    MSG_HEARTBEAT,
    MSG_TOAST,
    MSG_ACK,
    MSG_SCREEN_CHANGED,
    MSG_TOP_BAR,
    MSG_SCREEN_1,
    MSG_SCREEN_2,
    MSG_SCREEN_3,
    MSG_SCREEN_4,
    MSG_POMODORO_FULLSCREEN,
    MSG_UNKNOWN,
} msg_type_t;

#define TEXT_MAX 256

typedef struct {
    char text[TEXT_MAX];
    char level[8];
} toast_payload_t;

typedef struct {
    char ref[64];
} ack_payload_t;

// ---- top_bar (host -> esp) ----
#define TOP_BAR_FIELD_MAX 32
typedef struct {
    char clock[8];            // "HH:MM"
    char date[TOP_BAR_FIELD_MAX];
    char weather[TOP_BAR_FIELD_MAX];
    char claude_usage[TOP_BAR_FIELD_MAX];
    int  pomodoro_counter;
    char macro_button_label[16];
} top_bar_payload_t;

// ---- screen_1 (Jira) ----
#define JIRA_KEY_MAX        16
#define JIRA_SUMMARY_MAX    96
#define JIRA_STATUS_MAX     32
#define SCREEN1_TASKS_MAX   8
typedef struct {
    char key[JIRA_KEY_MAX];
    char summary[JIRA_SUMMARY_MAX];
    char status[JIRA_STATUS_MAX];
    bool is_current;
} jira_task_t;

#define MEETING_TITLE_MAX 64
#define MEETING_TIME_MAX  16
#define MEETING_URL_MAX   128
typedef struct {
    bool present;
    char title[MEETING_TITLE_MAX];
    char time[MEETING_TIME_MAX];
    char join_url[MEETING_URL_MAX];
    int  in_minutes;
} meeting_bar_t;

typedef struct {
    jira_task_t   today_tasks[SCREEN1_TASKS_MAX];
    size_t        today_count;
    jira_task_t   queued_tasks[SCREEN1_TASKS_MAX];
    size_t        queued_count;
    meeting_bar_t next_meeting;
} screen1_payload_t;

// ---- screen_2 (Comms) ----
#define NOTIF_SOURCE_MAX  16
#define NOTIF_SENDER_MAX  48
#define NOTIF_PREVIEW_MAX 128
#define NOTIF_TIME_MAX    16
#define NOTIF_ID_MAX      64
#define SCREEN2_NOTIF_MAX 16
typedef struct {
    char source[NOTIF_SOURCE_MAX];
    char sender[NOTIF_SENDER_MAX];
    char preview[NOTIF_PREVIEW_MAX];
    char time_ago[NOTIF_TIME_MAX];
    char id[NOTIF_ID_MAX];
} notification_t;

typedef struct {
    notification_t items[SCREEN2_NOTIF_MAX];
    size_t         count;
} screen2_payload_t;

// ---- screen_3 (Dev) ----
#define PR_ID_MAX     32
#define PR_TITLE_MAX  96
#define PR_AUTHOR_MAX 48
#define PR_REPO_MAX   48
#define PR_STATUS_MAX 24
#define SCREEN3_PR_MAX 8
typedef struct {
    char id[PR_ID_MAX];
    char title[PR_TITLE_MAX];
    char author[PR_AUTHOR_MAX];
    char repo[PR_REPO_MAX];
    char status[PR_STATUS_MAX]; // open/approved/needs_review/changes_requested
    char ci[PR_STATUS_MAX];     // passing/failing/running/unknown
} pull_request_t;

#define STANDUP_TEXT_MAX 128
#define SCREEN3_STANDUP_MAX 8
typedef struct {
    char text[STANDUP_TEXT_MAX];
    bool done;
} standup_item_t;

typedef struct {
    pull_request_t prs[SCREEN3_PR_MAX];
    size_t         pr_count;
    standup_item_t standup[SCREEN3_STANDUP_MAX];
    size_t         standup_count;
} screen3_payload_t;

// ---- screen_4 (Todo) ----
#define TODO_ID_MAX   32
#define TODO_TEXT_MAX 128
#define SCREEN4_ITEM_MAX 16
typedef struct {
    char id[TODO_ID_MAX];
    char text[TODO_TEXT_MAX];
    bool done;
} todo_item_t;

typedef struct {
    todo_item_t items[SCREEN4_ITEM_MAX];
    size_t      count;
} screen4_payload_t;

// ---- pomodoro_fullscreen (host -> esp) ----
typedef struct {
    bool visible;
    char task_key[JIRA_KEY_MAX];
    int  elapsed_sec;
    int  total_sec;
} pomodoro_fullscreen_payload_t;

typedef struct {
    msg_type_t type;
    union {
        toast_payload_t toast;
        ack_payload_t ack;
        top_bar_payload_t top_bar;
        screen1_payload_t screen_1;
        screen2_payload_t screen_2;
        screen3_payload_t screen_3;
        screen4_payload_t screen_4;
        pomodoro_fullscreen_payload_t pomo;
    } data;
} parsed_msg_t;

bool protocol_parse(const char *line, parsed_msg_t *out);
int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version);
int protocol_serialize_heartbeat(char *buf, size_t cap);

// ESP -> host events (M2). Returns bytes written or -1 on overflow.
int protocol_serialize_task_clicked(char *buf, size_t cap, const char *key);
int protocol_serialize_pr_clicked(char *buf, size_t cap, const char *id);
int protocol_serialize_notification_clicked(char *buf, size_t cap, const char *id);
int protocol_serialize_todo_clicked(char *buf, size_t cap, const char *id);
int protocol_serialize_macro_trigger(char *buf, size_t cap, const char *name);
int protocol_serialize_pomodoro_action(char *buf, size_t cap, const char *action);  // start|pause|resume|stop
int protocol_serialize_screen_changed_int(char *buf, size_t cap, int screen, const char *via);  // via: swipe|dot_click|autoscroll
