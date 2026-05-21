#include "board.h"
#include "protocol.h"
#include "ui.h"
#include "ui_state.h"
#include "toast.h"
#include "top_bar.h"
#include "carousel.h"
#include "fullscreen_overlay.h"
#include "lock_overlay.h"
#include "macro_overlay.h"
#include "pomodoro_overlay.h"
#include "screen_1.h"
#include "screen_2.h"
#include "screen_3.h"
#include "screen_4.h"
#include "usb_cdc.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"

#include <string.h>

static const char *TAG = "main";

#define FIRMWARE_VERSION "0.1.0"
#define HEARTBEAT_INTERVAL_MS 5000
#define HEARTBEAT_TIMEOUT_MS  15000

static int64_t s_last_rx_ms = 0;

static int64_t now_ms(void)
{
    return (int64_t)xTaskGetTickCount() * portTICK_PERIOD_MS;
}

static void send_line(const char *line)
{
    usb_line_t out;
    size_t len = strlen(line);
    if (len >= sizeof(out.data)) {
        ESP_LOGE(TAG, "outgoing line too long");
        return;
    }
    memcpy(out.data, line, len);
    out.len = len;
    xQueueSend(usb_cdc_tx_queue(), &out, portMAX_DELAY);
}

// Registered as macro_overlay's trigger callback: a tap inside a grid cell
// forwards the cell's macro id here, which we serialize as macro_trigger.name
// for the host to dispatch to its config-defined macro map.
static void macro_send_trigger(const char *id)
{
    if (!id || !id[0]) return;
    usb_line_t line;
    int n = protocol_serialize_macro_trigger(line.data, sizeof(line.data), id);
    if (n > 0 && (size_t)n < sizeof(line.data)) {
        line.len = (size_t)n;
        xQueueSend(usb_cdc_tx_queue(), &line, 0);
    }
}

// Top-bar MAKRO button → open the grid overlay (which carries the current
// macro_list from the host). The argument is the button's current label,
// which we discard: the overlay decides which macros to show, not the label.
static void top_bar_macro_clicked(const char *label)
{
    (void)label;
    macro_overlay_show();
}

static void ui_dispatch_task(void *arg)
{
    (void)arg;
    // Off-stack: usb_line_t (~4 KB) + parsed_msg_t (~4.5 KB; union sized for
    // screen2_payload_t = 16 notifications) overflow the 8 KB task stack.
    // The task is single-threaded so plain static storage is safe.
    static usb_line_t line;
    static parsed_msg_t msg;
    while (1) {
        if (xQueueReceive(usb_cdc_rx_queue(), &line, portMAX_DELAY) != pdTRUE) continue;

        if (!protocol_parse(line.data, &msg)) continue;

        s_last_rx_ms = now_ms();
        if (!ui_state_get()->connected) {
            ESP_LOGI(TAG, "reconnected — sending hello");
            char buf[128];
            int n = protocol_serialize_hello(buf, sizeof(buf), FIRMWARE_VERSION);
            if (n > 0) send_line(buf);
            ui_state_set_connected(true);
        }

        switch (msg.type) {
            case MSG_TOAST:
                toast_show(msg.data.toast.text, msg.data.toast.level);
                break;
            case MSG_ACK:
                ESP_LOGI(TAG, "ack ref=%s", msg.data.ack.ref);
                break;
            case MSG_HEARTBEAT:
                ESP_LOGD(TAG, "heartbeat from host");
                break;
            case MSG_TOP_BAR:
                top_bar_update(&msg.data.top_bar);
                break;
            case MSG_SCREEN_1:
                screen_1_update(&msg.data.screen_1);
                break;
            case MSG_SCREEN_2:
                screen_2_update(&msg.data.screen_2);
                break;
            case MSG_SCREEN_3:
                screen_3_update(&msg.data.screen_3);
                break;
            case MSG_SCREEN_4:
                screen_4_update(&msg.data.screen_4);
                break;
            case MSG_POMODORO_STATE: {
                pomo_state_t st = msg.data.pomo_state.state;
                pomodoro_overlay_update(&msg.data.pomo_state);
                // If we left a break (or never were in one), hide the break
                // overlay. Break overlay only stays up while state is in a
                // break or while the engine is silent between transitions.
                if (st != POMO_SHORT_BREAK && st != POMO_LONG_BREAK) {
                    fullscreen_overlay_hide();
                }
                if (st == POMO_ACTIVE || st == POMO_PAUSED
                        || st == POMO_SHORT_BREAK || st == POMO_LONG_BREAK) {
                    carousel_autoscroll_pause();
                } else {
                    carousel_autoscroll_resume();
                }
                break;
            }
            case MSG_FULLSCREEN:
                fullscreen_overlay_show(&msg.data.fullscreen);
                carousel_autoscroll_pause();
                break;
            case MSG_MACRO_LIST:
                macro_overlay_set_list(&msg.data.macro_list);
                break;
            case MSG_LOCK_STATE:
                if (msg.data.lock_state.locked) {
                    lock_overlay_show();
                    carousel_autoscroll_pause();
                } else {
                    lock_overlay_hide();
                    // Only resume autoscroll if nothing else is keeping it
                    // paused. A pomodoro that was active when we locked is
                    // still active when we unlock, and the break overlay
                    // can survive the lock-→-unlock cycle too.
                    if (!fullscreen_overlay_visible() && !pomodoro_overlay_visible()) {
                        carousel_autoscroll_resume();
                    }
                }
                break;
            case MSG_HELLO:
            case MSG_SCREEN_CHANGED:
            case MSG_UNKNOWN:
            default:
                ESP_LOGW(TAG, "ignored type=%d", msg.type);
                break;
        }

        // Security guard: if the host is locked, the lock overlay must stay
        // on top no matter what. Pomodoro and fullscreen overlays both call
        // lv_obj_move_foreground on themselves when they re-render, which
        // would otherwise pop them above the lock screen within ~1s.
        if (lock_overlay_visible()) {
            lock_overlay_show();
        }
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    char buf[64];
    while (1) {
        int n = protocol_serialize_heartbeat(buf, sizeof(buf));
        if (n > 0) send_line(buf);

        int64_t elapsed = now_ms() - s_last_rx_ms;
        if (elapsed > HEARTBEAT_TIMEOUT_MS && ui_state_get()->connected) {
            ESP_LOGW(TAG, "disconnected — no heartbeat for %lld ms", elapsed);
            ui_state_set_connected(false);
            toast_show("Disconnected", "error");
        }

        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "boot, firmware v%s", FIRMWARE_VERSION);

    esp_lcd_panel_handle_t panel = NULL;
    esp_lcd_touch_handle_t touch = NULL;
    ESP_ERROR_CHECK(board_init(&panel, &touch));
    ESP_ERROR_CHECK(ui_init(panel, touch));

    // Build all widgets BEFORE the LVGL renderer task starts — otherwise
    // widget construction on core 0 races lvgl_task on core 1 and corrupts
    // LVGL's internal TLSF heap (intermittent StoreProhibited panics).
    ui_build_main_screen();
    macro_overlay_init();
    macro_overlay_set_trigger_cb(macro_send_trigger);
    top_bar_set_macro_handler(top_bar_macro_clicked);
    ESP_ERROR_CHECK(ui_start_lvgl_task());

    ESP_ERROR_CHECK(usb_cdc_init());
    ESP_ERROR_CHECK(usb_cdc_start_tasks());

    // ui_dispatch_task mutates LVGL widgets when handling MSG_TOP_BAR etc.
    // Pin it to core 1 (same as lvgl_task) so those mutations serialize
    // naturally with rendering — no mutex needed.
    xTaskCreatePinnedToCore(ui_dispatch_task, "ui_dispatch", 8192, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat", 8192, NULL, 4, NULL, 0);

    s_last_rx_ms = now_ms();

    char buf[128];
    int n = protocol_serialize_hello(buf, sizeof(buf), FIRMWARE_VERSION);
    if (n > 0) send_line(buf);

    ESP_LOGI(TAG, "boot complete");
}
