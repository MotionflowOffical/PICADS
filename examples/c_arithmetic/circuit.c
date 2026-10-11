#include <stdint.h>
#include <stdbool.h>
uint8_t calculate(uint8_t a, uint8_t b, uint8_t c, uint8_t d, bool sel) {
    if (sel) { return a + b; }
    return c + d;
}
