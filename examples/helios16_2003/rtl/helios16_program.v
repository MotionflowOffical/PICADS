// Synthesis demonstration: 128x16 PROGRAM STORAGE IN FLIP-FLOPS.
// A manufactured 130 nm MCU would normally use flash/ROM/SRAM hard IP.
module helios16_program (
    input wire clk,
    input wire program_load,
    input wire [6:0] host_addr,
    input wire [15:0] host_data,
    input wire [6:0] pc_addr,
    output wire [15:0] instruction
);
    reg [15:0] mem [0:127];
    always @(posedge clk) begin
        if (program_load) mem[host_addr] <= host_data;
    end
    assign instruction=mem[pc_addr];
endmodule
