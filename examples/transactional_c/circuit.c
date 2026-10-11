#include <stdint.h>
#include <stdbool.h>
uint8_t calculate(uint8_t a, uint8_t b, bool choose) {
    uint8_t answer = 0;
    if (choose) {
        answer = a * b;
    } else {
        answer = a + b;
    }
    return answer;
}
