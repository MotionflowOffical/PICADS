// 16-bit timer with interrupt, 8-bit GPIO, and UART TX (8N1).
// UART divider 1041 @10 MHz -> approximately 9600 baud.
module helios16_io (
    input wire clk,
    input wire reset,
    input wire io_we,
    input wire [1:0] io_sel,
    input wire [15:0] io_data,
    output reg [7:0] gpio_out,
    output reg uart_tx,
    output wire uart_busy,
    output reg timer_irq
);
    reg [15:0] timer_count, timer_reload;
    reg timer_enabled;
    reg [9:0] tx_shift;
    reg [3:0] tx_bits;
    reg [10:0] uart_divider;
    assign uart_busy = (tx_bits != 0);
    always @(posedge clk) begin
        if (reset) begin
            gpio_out<=0;uart_tx<=1;
            timer_count<=16'd0;timer_reload<=16'd10000;
            timer_enabled<=0;timer_irq<=0;
            tx_shift<=10'h3ff;tx_bits<=0;uart_divider<=0;
        end else begin
            timer_irq<=0;
            if (timer_enabled) begin
                if (timer_count==0) begin
                    timer_count<=timer_reload;
                    timer_irq<=1;
                end else timer_count<=timer_count-1'b1;
            end
            if (io_we) begin
                case (io_sel)
                    2'd0: if (!uart_busy) begin
                        tx_shift<={1'b1,io_data[7:0],1'b0};
                        tx_bits<=10;uart_divider<=11'd1040;uart_tx<=0;
                    end
                    2'd1: gpio_out<=io_data[7:0];
                    2'd2: timer_reload<=io_data;
                    2'd3: begin timer_enabled<=io_data[0];timer_count<=timer_reload; end
                endcase
            end
            if (tx_bits!=0) begin
                if (uart_divider==0) begin
                    uart_tx<=tx_shift[1];
                    tx_shift<={1'b1,tx_shift[9:1]};
                    tx_bits<=tx_bits-1'b1;
                    uart_divider<=11'd1040;
                end else uart_divider<=uart_divider-1'b1;
            end
        end
    end
endmodule
