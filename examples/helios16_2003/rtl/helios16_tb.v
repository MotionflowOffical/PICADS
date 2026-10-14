`timescale 1ns/1ps
module helios16_tb;
    reg clk=0;always #50 clk=~clk;
    reg reset=1,run=0,program_load=0;
    reg [6:0] program_addr=0;
    reg [15:0] program_data=0;
    wire uart_tx,halted;
    wire [7:0] gpio_out;
    wire [15:0] pc_debug,r1_debug;
    helios16_top dut(.clk(clk),.reset(reset),.run(run),.program_load(program_load),
         .program_addr(program_addr),.program_data(program_data),
         .uart_tx(uart_tx),.gpio_out(gpio_out),.halted(halted),
         .pc_debug(pc_debug),.r1_debug(r1_debug));
    task load;
        input [6:0] addr;
        input [15:0] data;
        begin
            @(negedge clk);program_addr=addr;program_data=data;program_load=1;
            @(negedge clk);program_load=0;
        end
    endtask
    initial begin
        // MOVI R1,#5; MOVI R2,#3; ADD R3,R1,R2;
        // IO.GPIO R3; HALT.
        load(0,16'h7205);
        load(1,16'h7403);
        load(2,16'h1650);
        load(3,16'he601);
        load(4,16'hf000);
        @(negedge clk);reset=0;run=1;
        repeat(8) @(negedge clk);
        if(gpio_out!==8'd8 || halted!==1'b1) begin
            $display("HELIOS16_FAIL GPIO=%d halted=%b PC=%d",gpio_out,halted,pc_debug);
            $fatal(1);
        end
        $display("HELIOS16_PASS GPIO=8 and HALT reached");
        $finish;
    end
endmodule
