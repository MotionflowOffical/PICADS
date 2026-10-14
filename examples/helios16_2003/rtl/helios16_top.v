// HELIOS-16: 2003-era, 16-bit embedded CPU architecture demonstration.
// Real blocks hardened separately through native PICADS CO physical_macros.
module helios16_top (
    input wire clk,
    input wire reset,
    input wire run,
    input wire program_load,
    input wire [6:0] program_addr,
    input wire [15:0] program_data,
    output wire uart_tx,
    output wire [7:0] gpio_out,
    output wire halted,
    output wire [15:0] pc_debug,
    output wire [15:0] r1_debug
);
    wire [15:0] pc, instr,ra_data,rb_data,alu_result,alu_a,alu_b,wr_data,mem_rd_data,mem_wr_data,io_data;
    wire [2:0] ra_addr,rb_addr,wr_addr,alu_op;
    wire [5:0] mem_addr;
    wire [1:0] io_sel;
    wire wr_en,mem_wr,io_we,uart_busy,timer_irq,alu_zero;
    helios16_program u_program(
        .clk(clk),.program_load(program_load),.host_addr(program_addr),
        .host_data(program_data),.pc_addr(pc[6:0]),.instruction(instr));
    helios16_registers u_registers(
        .clk(clk),.reset(reset),.ra_addr(ra_addr),.rb_addr(rb_addr),
        .wr_addr(wr_addr),.wr_data(wr_data),.wr_en(wr_en),
        .ra_data(ra_data),.rb_data(rb_data),.r1_debug(r1_debug));
    helios16_alu u_alu(
        .operation(alu_op),.a(alu_a),.b(alu_b),
        .result(alu_result),.zero(alu_zero));
    helios16_data u_data(
        .clk(clk),.wr_en(mem_wr),.address(mem_addr),
        .wr_data(mem_wr_data),.rd_data(mem_rd_data));
    helios16_io u_io(
        .clk(clk),.reset(reset),.io_we(io_we),.io_sel(io_sel),
        .io_data(io_data),.gpio_out(gpio_out),.uart_tx(uart_tx),
        .uart_busy(uart_busy),.timer_irq(timer_irq));
    helios16_control u_control(
        .clk(clk),.reset(reset),.run(run),.irq(timer_irq),.uart_busy(uart_busy),
        .instruction(instr),.ra_data(ra_data),.rb_data(rb_data),
        .alu_result(alu_result),.mem_rd_data(mem_rd_data),
        .pc(pc),.halted(halted),.ra_addr(ra_addr),.rb_addr(rb_addr),
        .wr_addr(wr_addr),.wr_data(wr_data),.wr_en(wr_en),.alu_op(alu_op),
        .alu_a(alu_a),.alu_b(alu_b),.mem_addr(mem_addr),
        .mem_wr_data(mem_wr_data),.mem_wr(mem_wr),
        .io_we(io_we),.io_sel(io_sel),.io_data(io_data));
    assign pc_debug=pc;
endmodule
