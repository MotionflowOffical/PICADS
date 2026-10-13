// Top-level for independent ALU / RAM / CONTROL hardened physical macros.
// Macro instances are real blocks with LEF and GDS views in the modular flow.
module tiny8_modular_top (
`ifdef USE_POWER_PINS
    inout VPWR, inout VGND,
`endif
    input clk, input reset, input start,
    input [1:0] command, input [3:0] location, input [7:0] data,
    output [7:0] response, output done, output ready, output fault
);
    wire [3:0] fetch_addr, operand_addr, inspect_addr, alu_op;
    wire [7:0] fetched, operand_data, inspect_data, alu_lhs, alu_rhs, alu_result;
    wire mem_we;
    wire [3:0] mem_wa;
    wire [7:0] mem_wd;
    tiny8_memory u_memory(
`ifdef USE_POWER_PINS
        .VPWR(VPWR), .VGND(VGND),
`endif
        .clk(clk), .reset(reset),
        .write_enable(mem_we), .write_address(mem_wa), .write_data(mem_wd),
        .fetch_address(fetch_addr), .fetch_data(fetched),
        .operand_address(operand_addr), .operand_data(operand_data),
        .inspect_address(inspect_addr), .inspect_data(inspect_data)
    );
    tiny8_alu u_alu(
`ifdef USE_POWER_PINS
        .VPWR(VPWR), .VGND(VGND),
`endif
        .opcode(alu_op), .lhs(alu_lhs), .rhs(alu_rhs), .result(alu_result)
    );
    tiny8_control u_control(
`ifdef USE_POWER_PINS
        .VPWR(VPWR), .VGND(VGND),
`endif
        .clk(clk), .reset(reset), .start(start),
        .command(command), .location(location), .data(data),
        .instruction(fetched), .operand_data(operand_data),
        .inspect_data(inspect_data), .alu_result(alu_result),
        .fetch_address(fetch_addr), .operand_address(operand_addr),
        .inspect_address(inspect_addr), .alu_opcode(alu_op),
        .alu_lhs(alu_lhs), .alu_rhs(alu_rhs),
        .write_enable(mem_we), .write_address(mem_wa), .write_data(mem_wd),
        .response(response), .done(done), .ready(ready), .fault(fault)
    );
endmodule
