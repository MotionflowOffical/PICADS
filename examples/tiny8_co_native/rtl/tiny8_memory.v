// SKY130 hard macro: 16x8 register-file implementation (not SRAM macro).
// Three combinational reads and one synchronous write. Reset clears the bank.
module tiny8_memory (
    input clk, input reset,
    input write_enable, input [3:0] write_address, input [7:0] write_data,
    input [3:0] fetch_address, output [7:0] fetch_data,
    input [3:0] operand_address, output [7:0] operand_data,
    input [3:0] inspect_address, output [7:0] inspect_data
);
    reg [7:0] ram [0:15];
    integer i;
    assign fetch_data = ram[fetch_address];
    assign operand_data = ram[operand_address];
    assign inspect_data = ram[inspect_address];
    always @(posedge clk) begin
        if (reset) begin
            for (i=0; i<16; i=i+1) ram[i] <= 8'h00;
        end else if (write_enable) begin
            ram[write_address] <= write_data;
        end
    end
endmodule
