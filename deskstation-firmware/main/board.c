#include "board.h"

#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_log.h"

static const char *TAG = "board";

// --- Pin definitions (Waveshare ESP32-S3-Touch-LCD-7, verify against datasheet) ---
#define LCD_PIN_HSYNC 46
#define LCD_PIN_VSYNC 3
#define LCD_PIN_DE    5
#define LCD_PIN_PCLK  7
#define LCD_PIN_DISP  -1

#define LCD_PIN_R0 1
#define LCD_PIN_R1 2
#define LCD_PIN_R2 42
#define LCD_PIN_R3 41
#define LCD_PIN_R4 40
#define LCD_PIN_G0 39
#define LCD_PIN_G1 0
#define LCD_PIN_G2 45
#define LCD_PIN_G3 48
#define LCD_PIN_G4 47
#define LCD_PIN_G5 21
#define LCD_PIN_B0 14
#define LCD_PIN_B1 38
#define LCD_PIN_B2 18
#define LCD_PIN_B3 17
#define LCD_PIN_B4 10

#define TOUCH_I2C_PORT  I2C_NUM_0
#define TOUCH_PIN_SDA   8
#define TOUCH_PIN_SCL   9
#define TOUCH_PIN_INT   4
#define TOUCH_PIN_RESET -1

static esp_err_t init_rgb_panel(esp_lcd_panel_handle_t *out_panel)
{
    esp_lcd_rgb_panel_config_t panel_config = {
        .data_width = 16,
        .psram_trans_align = 64,
        .num_fbs = 2,
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .disp_gpio_num = LCD_PIN_DISP,
        .pclk_gpio_num = LCD_PIN_PCLK,
        .vsync_gpio_num = LCD_PIN_VSYNC,
        .hsync_gpio_num = LCD_PIN_HSYNC,
        .de_gpio_num = LCD_PIN_DE,
        .data_gpio_nums = {
            LCD_PIN_B0, LCD_PIN_B1, LCD_PIN_B2, LCD_PIN_B3, LCD_PIN_B4,
            LCD_PIN_G0, LCD_PIN_G1, LCD_PIN_G2, LCD_PIN_G3, LCD_PIN_G4, LCD_PIN_G5,
            LCD_PIN_R0, LCD_PIN_R1, LCD_PIN_R2, LCD_PIN_R3, LCD_PIN_R4,
        },
        .timings = {
            .pclk_hz = 16 * 1000 * 1000,
            .h_res = BOARD_LCD_WIDTH,
            .v_res = BOARD_LCD_HEIGHT,
            .hsync_pulse_width = 4,
            .hsync_back_porch = 8,
            .hsync_front_porch = 8,
            .vsync_pulse_width = 4,
            .vsync_back_porch = 8,
            .vsync_front_porch = 8,
            .flags.pclk_active_neg = 1,
        },
        .flags.fb_in_psram = 1,
    };
    ESP_RETURN_ON_ERROR(
        esp_lcd_new_rgb_panel(&panel_config, out_panel),
        TAG, "create RGB panel"
    );
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(*out_panel), TAG, "init panel");
    ESP_LOGI(TAG, "RGB panel initialized: %dx%d", BOARD_LCD_WIDTH, BOARD_LCD_HEIGHT);
    return ESP_OK;
}

static esp_err_t init_touch(esp_lcd_touch_handle_t *out_touch)
{
    i2c_config_t i2c_conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = TOUCH_PIN_SDA,
        .scl_io_num = TOUCH_PIN_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    ESP_RETURN_ON_ERROR(i2c_param_config(TOUCH_I2C_PORT, &i2c_conf), TAG, "i2c cfg");
    ESP_RETURN_ON_ERROR(i2c_driver_install(TOUCH_I2C_PORT, I2C_MODE_MASTER, 0, 0, 0), TAG, "i2c drv");

    esp_lcd_panel_io_handle_t touch_io = NULL;
    esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    ESP_RETURN_ON_ERROR(
        esp_lcd_new_panel_io_i2c((esp_lcd_i2c_bus_handle_t)TOUCH_I2C_PORT, &tp_io_config, &touch_io),
        TAG, "touch io"
    );

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = BOARD_LCD_WIDTH,
        .y_max = BOARD_LCD_HEIGHT,
        .rst_gpio_num = TOUCH_PIN_RESET,
        .int_gpio_num = TOUCH_PIN_INT,
        .flags = {.swap_xy = 0, .mirror_x = 0, .mirror_y = 0},
    };
    ESP_RETURN_ON_ERROR(esp_lcd_touch_new_i2c_gt911(touch_io, &tp_cfg, out_touch), TAG, "gt911");
    ESP_LOGI(TAG, "GT911 touch initialized");
    return ESP_OK;
}

esp_err_t board_init(esp_lcd_panel_handle_t *out_panel,
                     esp_lcd_touch_handle_t *out_touch)
{
    ESP_RETURN_ON_ERROR(init_rgb_panel(out_panel), TAG, "rgb panel");
    ESP_RETURN_ON_ERROR(init_touch(out_touch), TAG, "touch");
    return ESP_OK;
}
