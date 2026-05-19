#!/usr/bin/env bash
# Regenerate the four Deskstation font C arrays (Montserrat + Polish + LVGL symbols).
#
# Output: deskstation-firmware/main/ui/fonts/lv_font_pl_{14,16,20,28}.c
#
# Range:
#   0x20-0x7F        ASCII printable
#   0xB0             ° degree
#   0x2022           • bullet
#   0xC0-0x17F       Latin-1 Supplement + Latin Extended-A
#                    (covers Polish: ąĄćĆęĘłŁńŃóÓśŚźŹżŻ + accented chars used in fallback)
#   plus the 61 FontAwesome 5 codepoints LVGL maps to LV_SYMBOL_* macros, taken
#   verbatim from LVGL's own scripts/built_in_font/built_in_font_gen.py.
#
# Requires Node + npx (npx -y lv_font_conv runs without installing globally).

set -euo pipefail
cd "$(dirname "$0")"

OUT_DIR=../../main/ui/fonts
mkdir -p "$OUT_DIR"

LATIN_RANGE='0x20-0x7F,0xB0,0x2022,0xC0-0x17F'
SYMBOLS='61441,61448,61451,61452,61452,61453,61457,61459,61461,61465,61468,61473,61478,61479,61480,61502,61507,61512,61515,61516,61517,61521,61522,61523,61524,61543,61544,61550,61552,61553,61556,61559,61560,61561,61563,61587,61589,61636,61637,61639,61641,61664,61671,61674,61683,61724,61732,61787,61931,62016,62017,62018,62019,62020,62087,62099,62212,62189,62810,63426,63650'

for SIZE in 14 16 20 28; do
    OUT="$OUT_DIR/lv_font_pl_${SIZE}.c"
    echo ">> generating $OUT"
    npx -y lv_font_conv \
        --no-compress --no-prefilter \
        --bpp 4 \
        --size "$SIZE" \
        --font Montserrat-Medium.ttf -r "$LATIN_RANGE" \
        --font FontAwesome5-Solid+Brands+Regular.woff -r "$SYMBOLS" \
        --format lvgl \
        -o "$OUT" \
        --force-fast-kern-format
    # The generated header includes "lvgl/lvgl.h" by default but our managed
    # component installs it at the top level. Force the simple include.
    sed -i 's|#include "lvgl/lvgl.h"|#include "lvgl.h"|' "$OUT"
done

echo ""
echo "Done. Generated files:"
ls -lh "$OUT_DIR"/lv_font_pl_*.c
