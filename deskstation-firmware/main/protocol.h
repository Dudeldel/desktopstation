#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    MSG_HELLO,
    MSG_HEARTBEAT,
    MSG_TOAST,
    MSG_ACK,
    MSG_SCREEN_CHANGED,
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

typedef struct {
    msg_type_t type;
    union {
        toast_payload_t toast;
        ack_payload_t ack;
    } data;
} parsed_msg_t;

bool protocol_parse(const char *line, parsed_msg_t *out);
int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version);
int protocol_serialize_heartbeat(char *buf, size_t cap);
int protocol_serialize_screen_changed(char *buf, size_t cap, const char *screen);
