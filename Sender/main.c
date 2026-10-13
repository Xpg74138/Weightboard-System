#include "gd32e23x.h"
#include <stdint.h>
#include "gd32e23x_adc.h"

#define SENSOR_COUNT        4U
#define SAMPLE_COUNT        5U
#define SAMPLE_INTERVAL_MS  200U
#define VBAT_ADC_CHANNEL    ADC_CHANNEL_9
#define ADC_REF_MV          3300U
#define ADC_MAX             4095U

#define VBAT_R_HIGH_KOHM    1000U
#define VBAT_R_LOW_KOHM     470U

#define BAT_EMPTY_MV        3300U
#define BAT_FULL_MV         4200U

// ???????????,???? 0x00?
// ???1?:0x01
// ??1/2?:0x03
// ????:0x0F
#define USE_HX711_CH_MASK   0x0FU

/* ============================================================
   板号配置：每块板子必须改成不同的值（1 ~ 42）
   改完重新编译烧写即可；板号会作为帧的第一个数据字段发出，
   接收端据此区分是哪个板子发来的。
   ============================================================ */
#define BOARD_ID            1U

/* 采样间隔随机抖动幅度（毫秒）：各板周期略有差异，避免长期同步撞包 */
#define SAMPLE_JITTER_MS    6U

static const uint32_t hx_dout_pin[SENSOR_COUNT] = {
    GPIO_PIN_0, GPIO_PIN_2, GPIO_PIN_4, GPIO_PIN_6
};

static const uint32_t hx_sck_pin[SENSOR_COUNT] = {
    GPIO_PIN_1, GPIO_PIN_3, GPIO_PIN_5, GPIO_PIN_7
};

static int32_t hx_zero[SENSOR_COUNT] = {0, 0, 0, 0};
static int32_t hx_counts_per_gram[SENSOR_COUNT] = {1, 1, 1, 1};

static volatile uint32_t g_ms = 0;

/* ============================================================
   极简伪随机数（xorshift32）：给采样间隔加抖动用
   用板号做种子，所以每块板子的抖动序列不同，周期不会完全一致
   ============================================================ */
static uint32_t g_rand_state = 1U;

static void rand_seed(uint32_t seed)
{
    if (seed == 0U) {
        seed = 1U;
    }
    g_rand_state = seed;
}

static uint32_t rand_next(void)
{
    uint32_t x = g_rand_state;

    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    g_rand_state = x;

    return x;
}

void SysTick_Handler(void)
{
    g_ms++;
}

static uint32_t millis(void)
{
    return g_ms;
}

static void timebase_init(void)
{
    // ??????????? IRC8M,? 8MHz?
    // 8000 ? CPU tick = 1ms?
    SysTick_Config(8000U);
}

static void delay_ms(uint32_t ms)
{
    uint32_t start = millis();

    while ((uint32_t)(millis() - start) < ms) {
    }
}

static void delay_us(volatile uint32_t us)
{
    while (us--) {
        for (volatile uint32_t i = 0; i < 8; i++) {
            __NOP();
        }
    }
}

static void lora_uart_init(void)
{
    rcu_periph_clock_enable(RCU_GPIOA);
    rcu_periph_clock_enable(RCU_USART0);

    gpio_af_set(GPIOA, GPIO_AF_1, GPIO_PIN_9 | GPIO_PIN_10);
    gpio_mode_set(GPIOA, GPIO_MODE_AF, GPIO_PUPD_PULLUP, GPIO_PIN_9 | GPIO_PIN_10);
    gpio_output_options_set(GPIOA, GPIO_OTYPE_PP, GPIO_OSPEED_50MHZ, GPIO_PIN_9 | GPIO_PIN_10);

    usart_deinit(USART0);
    usart_baudrate_set(USART0, 9600U);
    usart_word_length_set(USART0, USART_WL_8BIT);
    usart_stop_bit_set(USART0, USART_STB_1BIT);
    usart_parity_config(USART0, USART_PM_NONE);
    usart_transmit_config(USART0, USART_TRANSMIT_ENABLE);
    usart_enable(USART0);
}

static void lora_send_char(char ch)
{
    while (RESET == usart_flag_get(USART0, USART_FLAG_TBE)) {
    }

    usart_data_transmit(USART0, (uint8_t)ch);
}

static void lora_send_string(const char *s)
{
    while (*s) {
        lora_send_char(*s++);
    }

    while (RESET == usart_flag_get(USART0, USART_FLAG_TC)) {
    }
}

static void lora_send_uint32(uint32_t value)
{
    char buf[10];
    uint8_t i = 0;

    if (value == 0U) {
        lora_send_char('0');
        return;
    }

    while (value > 0U) {
        buf[i++] = (char)('0' + (value % 10U));
        value /= 10U;
    }

    while (i > 0U) {
        lora_send_char(buf[--i]);
    }
}

static void lora_send_int32(int32_t value)
{
    uint32_t u;

    if (value < 0) {
        lora_send_char('-');
        u = (uint32_t)(-(value + 1)) + 1U;
    } else {
        u = (uint32_t)value;
    }

    lora_send_uint32(u);
}

static void lora_send_hex2(uint8_t value)
{
    const char hex[] = "0123456789ABCDEF";

    lora_send_char(hex[(value >> 4) & 0x0F]);
    lora_send_char(hex[value & 0x0F]);
}

static void hx711_gpio_init(void)
{
    rcu_periph_clock_enable(RCU_GPIOA);

    gpio_mode_set(GPIOA, GPIO_MODE_INPUT, GPIO_PUPD_PULLUP,
                  GPIO_PIN_0 | GPIO_PIN_2 | GPIO_PIN_4 | GPIO_PIN_6);

    gpio_mode_set(GPIOA, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE,
                  GPIO_PIN_1 | GPIO_PIN_3 | GPIO_PIN_5 | GPIO_PIN_7);

    gpio_output_options_set(GPIOA, GPIO_OTYPE_PP, GPIO_OSPEED_50MHZ,
                            GPIO_PIN_1 | GPIO_PIN_3 | GPIO_PIN_5 | GPIO_PIN_7);

    gpio_bit_reset(GPIOA, GPIO_PIN_1 | GPIO_PIN_3 | GPIO_PIN_5 | GPIO_PIN_7);
}

static uint8_t hx711_read(uint8_t ch, int32_t *value)
{
    uint32_t data = 0;
    uint32_t start = millis();

    while (SET == gpio_input_bit_get(GPIOA, hx_dout_pin[ch])) {
        if ((uint32_t)(millis() - start) > 30U) {
            return 0;
        }
    }

    for (uint8_t i = 0; i < 24U; i++) {
        gpio_bit_set(GPIOA, hx_sck_pin[ch]);
        delay_us(1);

        data <<= 1;

        gpio_bit_reset(GPIOA, hx_sck_pin[ch]);
        delay_us(1);

        if (SET == gpio_input_bit_get(GPIOA, hx_dout_pin[ch])) {
            data++;
        }
    }

    gpio_bit_set(GPIOA, hx_sck_pin[ch]);
    delay_us(1);
    gpio_bit_reset(GPIOA, hx_sck_pin[ch]);
    delay_us(1);

    if (data & 0x800000U) {
        data |= 0xFF000000U;
    }

    *value = (int32_t)data;
    return 1;
}

static int32_t hx711_to_gram(uint8_t ch, int32_t raw)
{
    int32_t scale = hx_counts_per_gram[ch];

    if (scale == 0) {
        scale = 1;
    }

    return (raw - hx_zero[ch]) / scale;
}

static void battery_adc_init(void)
{
    rcu_periph_clock_enable(RCU_GPIOB);
    rcu_periph_clock_enable(RCU_ADC);

    gpio_mode_set(GPIOB, GPIO_MODE_ANALOG, GPIO_PUPD_NONE, GPIO_PIN_1);

    // ?? IRC28M,?? APB2 ??,?? ADC ??????????
    rcu_adc_clock_config(RCU_ADCCK_APB2_DIV6);

    adc_deinit();
    adc_data_alignment_config(ADC_DATAALIGN_RIGHT);
    adc_channel_length_config(ADC_REGULAR_CHANNEL, 1U);
    adc_external_trigger_source_config(ADC_REGULAR_CHANNEL, ADC_EXTTRIG_REGULAR_NONE);
    adc_external_trigger_config(ADC_REGULAR_CHANNEL, ENABLE);

    adc_enable();
    delay_ms(2);

    // ????,?? ADC ??????????
    // adc_calibration_enable();
}

static uint8_t adc_read_channel(uint8_t channel, uint16_t *value)
{
    uint32_t start = millis();

    adc_regular_channel_config(0U, channel, ADC_SAMPLETIME_239POINT5);
    adc_flag_clear(ADC_FLAG_EOC);
    adc_software_trigger_enable(ADC_REGULAR_CHANNEL);

    while (RESET == adc_flag_get(ADC_FLAG_EOC)) {
        if ((uint32_t)(millis() - start) > 10U) {
            return 0;
        }
    }

    *value = adc_regular_data_read();
    return 1;
}

static uint32_t battery_mv_read(void)
{
    uint32_t raw_sum = 0;
    uint8_t ok_count = 0;
    uint16_t raw;
    uint32_t adc_mv;

    for (uint8_t i = 0; i < 8U; i++) {
        if (adc_read_channel(VBAT_ADC_CHANNEL, &raw)) {
            raw_sum += raw;
            ok_count++;
        }
    }

    if (ok_count == 0U) {
        return 0U;
    }

    adc_mv = ((raw_sum / ok_count) * ADC_REF_MV) / ADC_MAX;

    return (adc_mv * (VBAT_R_HIGH_KOHM + VBAT_R_LOW_KOHM)) / VBAT_R_LOW_KOHM;
}

static uint8_t battery_percent(uint32_t mv)
{
    if (mv <= BAT_EMPTY_MV) {
        return 0U;
    }

    if (mv >= BAT_FULL_MV) {
        return 100U;
    }

    return (uint8_t)(((mv - BAT_EMPTY_MV) * 100U) / (BAT_FULL_MV - BAT_EMPTY_MV));
}

static void send_packet(uint32_t seq, int32_t weight_g[4], uint8_t ok_mask, uint32_t bat_mv)
{
    lora_send_string("WB,");
    lora_send_uint32(BOARD_ID);      /* 板号：成为字段1 */
    lora_send_char(',');
    lora_send_uint32(seq);
    lora_send_char(',');
    lora_send_uint32(millis());
    lora_send_char(',');
    lora_send_hex2(ok_mask);
    lora_send_char(',');

    lora_send_int32(weight_g[0]);
    lora_send_char(',');
    lora_send_int32(weight_g[1]);
    lora_send_char(',');
    lora_send_int32(weight_g[2]);
    lora_send_char(',');
    lora_send_int32(weight_g[3]);

    lora_send_char(',');
		lora_send_uint32(bat_mv);
		lora_send_char(',');
		lora_send_uint32(battery_percent(bat_mv));
		lora_send_string("\r\n");
}



int main(void)
{
    uint32_t seq = 0;

    timebase_init();
    lora_uart_init();
    hx711_gpio_init();

    /* ============================================================
       错峰启动：42 块板子各推迟 (板号-1)×100ms 开始发送，
       把发送时刻均匀摊在一个发送周期内，大幅降低空中撞包概率。
       以 42 块为例，最晚的一块推迟 41×100ms = 4.1 秒。
       ============================================================ */
    rand_seed(BOARD_ID * 2654435761U + 12345U);
    delay_ms((uint32_t)(BOARD_ID - 1U) * 100U);
		

    delay_ms(1000);
    lora_send_string("BOOT_SYSTICK\r\n");
	
		battery_adc_init();
		lora_send_string("ADC_INIT_OK\r\n");

    while (1) {
        int64_t sum_g[SENSOR_COUNT] = {0, 0, 0, 0};
        uint8_t ok_count[SENSOR_COUNT] = {0, 0, 0, 0};
        int32_t weight_g[SENSOR_COUNT] = {0, 0, 0, 0};
        uint8_t ok_mask = 0;

        for (uint8_t sample = 0; sample < SAMPLE_COUNT; sample++) {
            for (uint8_t ch = 0; ch < SENSOR_COUNT; ch++) {
                int32_t raw;

                if ((USE_HX711_CH_MASK & (1U << ch)) == 0U) {
                    continue;
                }

                if (hx711_read(ch, &raw)) {
                    sum_g[ch] += hx711_to_gram(ch, raw);
                    ok_count[ch]++;
                }
            }

            /* 采样间隔加一点随机抖动：各板周期不会完全一致，
               相位缓慢滑动，避免"周期相同→长期持续撞包" */
            delay_ms(SAMPLE_INTERVAL_MS + (rand_next() % SAMPLE_JITTER_MS));
        }

        for (uint8_t ch = 0; ch < SENSOR_COUNT; ch++) {
            if (ok_count[ch] > 0U) {
                weight_g[ch] = (int32_t)(sum_g[ch] / ok_count[ch]);
                ok_mask |= (uint8_t)(1U << ch);
            } else {
                weight_g[ch] = 0;
            }
        }
				uint32_t bat_mv = battery_mv_read();
        send_packet(seq++, weight_g, ok_mask, bat_mv);
    }
}