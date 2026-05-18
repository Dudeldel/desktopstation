#include "ui_state.h"

#include <string.h>

static ui_state_t s_state = {.connected = true};

ui_state_t *ui_state_get(void) { return &s_state; }

void ui_state_set_connected(bool connected) { s_state.connected = connected; }
