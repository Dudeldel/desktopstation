#include "protocol.h"

#include "cJSON.h"
#include "esp_log.h"
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
    return MSG_UNKNOWN;
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
    }

    ok = true;
done:
    cJSON_Delete(root);
    return ok;
}

int protocol_serialize_hello(char *buf, size_t cap, const char *firmware_version)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"hello\",\"data\":{\"firmware_version\":\"%s\"}}",
        firmware_version);
}

int protocol_serialize_heartbeat(char *buf, size_t cap)
{
    return snprintf(buf, cap, "{\"v\":1,\"type\":\"heartbeat\",\"data\":{}}");
}

int protocol_serialize_screen_changed(char *buf, size_t cap, const char *screen)
{
    return snprintf(buf, cap,
        "{\"v\":1,\"type\":\"screen_changed\",\"data\":{\"screen\":\"%s\"}}",
        screen);
}
