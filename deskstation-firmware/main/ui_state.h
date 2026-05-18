#pragma once

#include <stdbool.h>

typedef struct {
    bool connected;
    char last_toast[256];
} ui_state_t;

ui_state_t *ui_state_get(void);
void ui_state_set_connected(bool connected);
