#include "board.h"
#include "protocol.h"
#include "ui.h"
#include "ui_state.h"
#include "toast.h"
#include "top_bar.h"
#include "carousel.h"
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

static void ui_dispatch_task(void *arg)
{
    (void)arg;
    usb_line_t line;
    while (1) {
        if (xQueueReceive(usb_cdc_rx_queue(), &line, portMAX_DELAY) != pdTRUE) continue;

        parsed_msg_t msg;
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
            case MSG_POMODORO_STATE:
                pomodoro_overlay_update(&msg.data.pomo_state);
                if (msg.data.pomo_state.state == POMO_ACTIVE
                        || msg.data.pomo_state.state == POMO_PAUSED) {
                    carousel_autoscroll_pause();
                } else {
                    carousel_autoscroll_resume();
                }
                break;
            case MSG_FULLSCREEN:
                // M3.6 will wire fullscreen_overlay_update here; for now log.
                ESP_LOGD(TAG, "fullscreen kind=%d title=%s",
                    (int)msg.data.fullscreen.kind, msg.data.fullscreen.title);
                carousel_autoscroll_pause();
                break;
            case MSG_HELLO:
            case MSG_SCREEN_CHANGED:
            case MSG_UNKNOWN:
            default:
                ESP_LOGW(TAG, "ignored type=%d", msg.type);
                break;
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

    ui_build_main_screen();

    ESP_ERROR_CHECK(usb_cdc_init());
    ESP_ERROR_CHECK(usb_cdc_start_tasks());

    xTaskCreatePinnedToCore(ui_dispatch_task, "ui_dispatch", 8192, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat", 8192, NULL, 4, NULL, 0);

    s_last_rx_ms = now_ms();

    char buf[128];
    int n = protocol_serialize_hello(buf, sizeof(buf), FIRMWARE_VERSION);
    if (n > 0) send_line(buf);

    ESP_LOGI(TAG, "boot complete");
}
