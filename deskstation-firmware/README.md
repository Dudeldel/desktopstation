# deskstation-firmware

ESP32-S3 firmware for the Deskstation hardware (Waveshare ESP32-S3-Touch-LCD-7). LVGL UI, USB CDC transport. Behaves as a dumb terminal — all state lives on the host daemon.

## One-time setup

### 1. Install ESP-IDF v5.3

```bash
bash tools/install_esp_idf.sh
```

This clones ESP-IDF v5.3 into `~/esp/esp-idf/` and runs the official installer. Takes ~10–20 min.

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
alias get_idf='. $HOME/esp/esp-idf/export.sh'
```

Then source it in each terminal:

```bash
get_idf
idf.py --version    # should print v5.3.x
```

### 2. Verify the target

```bash
cd deskstation-firmware
idf.py set-target esp32s3
```

### 3. Plug in the board

```bash
ls /dev/ttyACM*       # find your device (typically /dev/ttyACM0)
dmesg | tail -10      # confirms it shows up after plug
```

## Build, flash, run

```bash
get_idf
bash tools/flash.sh /dev/ttyACM0
# or manually:
idf.py -p /dev/ttyACM0 build flash monitor
```

The serial monitor is on a different channel than the USB CDC protocol used by the daemon — the latter is `/dev/ttyACM0`, the former is over JTAG/UART.

## Hardware reference

This firmware targets the Waveshare ESP32-S3-Touch-LCD-7. Pin assignments and timings live in `main/board.c`. See [waveshareteam/Waveshare-ESP32-S3-Touch-LCD-7](https://github.com/waveshareteam/Waveshare-ESP32-S3-Touch-LCD-7) for the datasheet and reference designs.

## Layout

- `main/main.c` — app_main: init board → LVGL → USB CDC → spawn 4 FreeRTOS tasks
- `main/board.{h,c}` — RGB LCD + GT911 touch init using stock ESP-IDF drivers
- `main/usb_cdc.{h,c}` — TinyUSB CDC + RX/TX queues
- `main/protocol.{h,c}` — cJSON envelope parser + outgoing message serializers
- `main/ui/` — LVGL screen + toast widget

## Status

M0 + M1 complete: scaffold + USB transport with heartbeat and reconnect. UI is a placeholder screen ("Hello, Deskstation. M0+M1.") + toast widget. The full UI (top bar, 4 carousel screens) starts in M2.
