// 8 x 16-bit general-purpose register file; R0 reads zero.
module helios16_registers (
    input wire clk,
    input wire reset,
    input wire [2:0] ra_addr,
    input wire [2:0] rb_addr,
    input wire [2:0] wr_addr,
    input wire [15:0] wr_data,
    input wire wr_en,
    output wire [15:0] ra_data,
    output wire [15:0] rb_data,
    output wire [15:0] r1_debug
);
    reg [15:0] regs [0:7];
    integer i;
    always @(posedge clk) begin
        if (reset) begin
            for (i=0;i<8;i=i+1) regs[i] <= 16'd0;
        end else if (wr_en && wr_addr!=3'd0) regs[wr_addr] <= wr_data;
    end
    assign ra_data=(ra_addr==0) ? 16'd0 : regs[ra_addr];
    assign rb_data=(rb_addr==0) ? 16'd0 : regs[rb_addr];
    assign r1_debug=regs[1];
endmodule
