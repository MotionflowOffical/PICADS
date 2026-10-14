// 64 x 16-bit demonstration scratchpad (flop implementation, not SRAM macro).
module helios16_data (
    input wire clk,
    input wire wr_en,
    input wire [5:0] address,
    input wire [15:0] wr_data,
    output wire [15:0] rd_data
);
    reg [15:0] scratch [0:63];
    always @(posedge clk) if (wr_en) scratch[address] <= wr_data;
    assign rd_data=scratch[address];
endmodule
