#include "ui.h"
#include "toast.h"

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_lcd_panel_io.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

static const char *TAG = "ui";

#define LVGL_TICK_PERIOD_MS 5
#define LVGL_TASK_STACK 8192
#define LVGL_TASK_PRIO 2
#define LVGL_TASK_CORE 1

static lv_disp_drv_t s_disp_drv;
static lv_disp_draw_buf_t s_draw_buf;
static esp_lcd_panel_handle_t s_panel;
static esp_lcd_touch_handle_t s_touch;

static void flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    esp_lcd_panel_draw_bitmap(s_panel,
                              area->x1, area->y1,
                              area->x2 + 1, area->y2 + 1,
                              color_map);
    lv_disp_flush_ready(drv);
}

static void touch_read_cb(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    (void)drv;
    uint16_t x[1] = {0};
    uint16_t y[1] = {0};
    uint16_t strength[1] = {0};
    uint8_t count = 0;
    esp_lcd_touch_read_data(s_touch);
    bool pressed = esp_lcd_touch_get_coordinates(s_touch, x, y, strength, &count, 1);
    data->state = (pressed && count > 0) ? LV_INDEV_STATE_PR : LV_INDEV_STATE_REL;
    if (pressed && count > 0) {
        data->point.x = x[0];
        data->point.y = y[0];
    }
}

static void tick_cb(void *arg) { (void)arg; lv_tick_inc(LVGL_TICK_PERIOD_MS); }

static void lvgl_task(void *arg)
{
    (void)arg;
    while (1) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(LVGL_TICK_PERIOD_MS));
    }
}

esp_err_t ui_init(esp_lcd_panel_handle_t panel, esp_lcd_touch_handle_t touch)
{
    s_panel = panel;
    s_touch = touch;

    lv_init();

    const size_t buf_pixels = 800 * 60;
    lv_color_t *buf1 = heap_caps_malloc(buf_pixels * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    lv_color_t *buf2 = heap_caps_malloc(buf_pixels * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    lv_disp_draw_buf_init(&s_draw_buf, buf1, buf2, buf_pixels);

    lv_disp_drv_init(&s_disp_drv);
    s_disp_drv.hor_res = 800;
    s_disp_drv.ver_res = 480;
    s_disp_drv.flush_cb = flush_cb;
    s_disp_drv.draw_buf = &s_draw_buf;
    lv_disp_drv_register(&s_disp_drv);

    static lv_indev_drv_t indev_drv;
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = touch_read_cb;
    lv_indev_drv_register(&indev_drv);

    const esp_timer_create_args_t tick_args = {
        .callback = &tick_cb, .name = "lv_tick",
    };
    esp_timer_handle_t tick_handle;
    esp_timer_create(&tick_args, &tick_handle);
    esp_timer_start_periodic(tick_handle, LVGL_TICK_PERIOD_MS * 1000);

    if (xTaskCreatePinnedToCore(lvgl_task, "lvgl", LVGL_TASK_STACK, NULL,
                                LVGL_TASK_PRIO, NULL, LVGL_TASK_CORE) != pdPASS) {
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "LVGL initialized");
    return ESP_OK;
}

void ui_build_hello_screen(void)
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);

    lv_obj_t *label = lv_label_create(scr);
    lv_label_set_text(label, "Hello, Deskstation. M0+M1.");
    lv_obj_set_style_text_color(label, lv_color_white(), 0);
    lv_obj_align(label, LV_ALIGN_CENTER, 0, 0);

    toast_init(scr);
}
