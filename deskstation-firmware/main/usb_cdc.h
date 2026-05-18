#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdbool.h>
#include <stddef.h>

#define USB_LINE_MAX_LEN 4096

typedef struct {
    char data[USB_LINE_MAX_LEN];
    size_t len;
} usb_line_t;

esp_err_t usb_cdc_init(void);
QueueHandle_t usb_cdc_rx_queue(void);
QueueHandle_t usb_cdc_tx_queue(void);
esp_err_t usb_cdc_start_tasks(void);
