#include "ui.h"
#include "carousel.h"
#include "dots.h"
#include "screen_1.h"
#include "screen_2.h"
#include "screen_3.h"
#include "screen_4.h"
#include "theme.h"
#include "toast.h"
#include "top_bar.h"

#include "esp_log.h"
#include "esp_lcd_panel_rgb.h"
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
static esp_lcd_touch_handle_t s_touch;

static void flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    (void)area;
    (void)color_map;
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
    s_touch = touch;

    lv_init();

    // Use the panel's own framebuffers directly (direct mode). LVGL renders
    // straight into the hardware back-buffer; the panel's continuous RGB scan
    // displays it without an intermediate draw_bitmap copy. No tearing, no
    // partial-flush white-bar artifacts.
    void *fb0 = NULL;
    void *fb1 = NULL;
    esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &fb0, &fb1);
    lv_disp_draw_buf_init(&s_draw_buf, fb0, fb1, 800 * 480);

    lv_disp_drv_init(&s_disp_drv);
    s_disp_drv.hor_res = 800;
    s_disp_drv.ver_res = 480;
    s_disp_drv.flush_cb = flush_cb;
    s_disp_drv.draw_buf = &s_draw_buf;
    s_disp_drv.direct_mode = 1;
    s_disp_drv.full_refresh = 1;
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

    ESP_LOGI(TAG, "LVGL initialized");
    return ESP_OK;
}

esp_err_t ui_start_lvgl_task(void)
{
    if (xTaskCreatePinnedToCore(lvgl_task, "lvgl", LVGL_TASK_STACK, NULL,
                                LVGL_TASK_PRIO, NULL, LVGL_TASK_CORE) != pdPASS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

void ui_build_main_screen(void)
{
    lv_obj_t *scr = lv_scr_act();
    theme_apply_to_screen(scr);
    top_bar_init(scr);
    dots_init(scr);
    carousel_init(scr);

    // Phase C: per-screen content modules attach to their carousel tiles.
    screen_1_init(carousel_tile(0));
    screen_2_init(carousel_tile(1));
    screen_3_init(carousel_tile(2));
    screen_4_init(carousel_tile(3));

    toast_init(scr);  // existing M1 overlay, lazy-built on show
}
