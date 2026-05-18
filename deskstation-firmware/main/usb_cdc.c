#include "usb_cdc.h"

#include "esp_log.h"
#include "freertos/task.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"

#include <string.h>

static const char *TAG = "usb_cdc";

#define USB_QUEUE_LEN 16

static QueueHandle_t s_rx_queue;
static QueueHandle_t s_tx_queue;
static char s_rx_buf[USB_LINE_MAX_LEN];
static size_t s_rx_len;

static void on_cdc_rx(int itf, cdcacm_event_t *event)
{
    (void)itf;
    (void)event;
    uint8_t chunk[64];
    size_t got = 0;
    while (tinyusb_cdcacm_read(TINYUSB_CDC_ACM_0, chunk, sizeof(chunk), &got) == ESP_OK && got > 0) {
        for (size_t i = 0; i < got; ++i) {
            char c = (char)chunk[i];
            if (c == '\n') {
                if (s_rx_len > 0 && s_rx_buf[s_rx_len - 1] == '\r') s_rx_len--;
                usb_line_t line;
                memcpy(line.data, s_rx_buf, s_rx_len);
                line.data[s_rx_len] = '\0';
                line.len = s_rx_len;
                if (xQueueSend(s_rx_queue, &line, 0) != pdTRUE) {
                    ESP_LOGW(TAG, "rx queue full, dropped line");
                }
                s_rx_len = 0;
            } else if (s_rx_len < USB_LINE_MAX_LEN - 1) {
                s_rx_buf[s_rx_len++] = c;
            } else {
                ESP_LOGW(TAG, "rx line overflow, dropping buffer");
                s_rx_len = 0;
            }
        }
    }
}

static void tx_task(void *arg)
{
    (void)arg;
    usb_line_t line;
    while (1) {
        if (xQueueReceive(s_tx_queue, &line, portMAX_DELAY) == pdTRUE) {
            tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)line.data, line.len);
            const char nl = '\n';
            tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)&nl, 1);
            tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
        }
    }
}

esp_err_t usb_cdc_init(void)
{
    s_rx_queue = xQueueCreate(USB_QUEUE_LEN, sizeof(usb_line_t));
    s_tx_queue = xQueueCreate(USB_QUEUE_LEN, sizeof(usb_line_t));
    if (!s_rx_queue || !s_tx_queue) return ESP_ERR_NO_MEM;

    const tinyusb_config_t tusb_cfg = {0};
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));

    tinyusb_config_cdcacm_t acm_cfg = {
        .usb_dev = TINYUSB_USBDEV_0,
        .cdc_port = TINYUSB_CDC_ACM_0,
        .rx_unread_buf_sz = 1024,
        .callback_rx = &on_cdc_rx,
        .callback_rx_wanted_char = NULL,
        .callback_line_state_changed = NULL,
        .callback_line_coding_changed = NULL,
    };
    ESP_ERROR_CHECK(tusb_cdc_acm_init(&acm_cfg));

    ESP_LOGI(TAG, "USB CDC initialized");
    return ESP_OK;
}

QueueHandle_t usb_cdc_rx_queue(void) { return s_rx_queue; }
QueueHandle_t usb_cdc_tx_queue(void) { return s_tx_queue; }

esp_err_t usb_cdc_start_tasks(void)
{
    if (xTaskCreatePinnedToCore(tx_task, "usb_tx", 4096, NULL, 5, NULL, 0) != pdPASS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
