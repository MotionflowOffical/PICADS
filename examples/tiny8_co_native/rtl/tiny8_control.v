// SKY130 hard macro: Tiny8 instruction sequencer, PC, ACC and I/O latch.
// One externally requested instruction retires on each active START edge.
module tiny8_control (
    input clk, input reset, input start,
    input [1:0] command, input [3:0] location, input [7:0] data,
    input [7:0] instruction, input [7:0] operand_data,
    input [7:0] inspect_data, input [7:0] alu_result,
    output [3:0] fetch_address, output [3:0] operand_address,
    output [3:0] inspect_address, output [3:0] alu_opcode,
    output [7:0] alu_lhs, output [7:0] alu_rhs,
    output reg write_enable, output reg [3:0] write_address,
    output reg [7:0] write_data,
    output reg [7:0] response, output reg done,
    output ready, output fault
);
    reg [2:0] pc;
    reg [7:0] acc;
    reg [7:0] out_latch;
    reg zero_flag;
    wire [3:0] opcode = instruction[7:4];
    wire [3:0] operand = instruction[3:0];
    assign ready=1'b1;
    assign fault=1'b0;
    assign fetch_address={1'b0,pc};
    assign operand_address=operand;
    assign inspect_address=location;
    assign alu_opcode=opcode;
    assign alu_lhs=acc;
    assign alu_rhs=operand_data;
    reg [7:0] next_acc;
    reg [2:0] next_pc;
    reg [7:0] inspected;
    always @* begin
        next_acc=acc;
        next_pc=pc+3'd1;
        write_enable=1'b0;
        write_address=4'd0;
        write_data=8'd0;
        case (location)
          4'd12: inspected=out_latch;
          4'd13: inspected={7'b0,zero_flag};
          4'd14: inspected=acc;
          4'd15: inspected={5'b0,pc};
          default: inspected=inspect_data;
        endcase
        if (start && !reset) begin
          if (command==2'd1 && location<4'd12) begin
              write_enable=1'b1;
              write_address=location;
              write_data=data;
          end else if (command==2'd0) begin
              case (opcode)
                4'h1: next_acc={4'b0,operand};
                4'h2: next_acc=operand_data;
                4'h3,4'h4,4'h5,4'h6,4'hB: next_acc=alu_result;
                4'h7: begin
                    if (operand<4'd12) begin
                       write_enable=1'b1;
                       write_address=operand;
                       write_data=acc;
                    end
                end
                4'h8: next_pc=operand[2:0];
                4'h9: if (acc==8'd0) next_pc=operand[2:0];
                default: begin end
              endcase
          end
        end
    end
    always @(posedge clk) begin
        if (reset) begin
            pc<=3'd0;
            acc<=8'd0;
            out_latch<=8'd0;
            zero_flag<=1'b1;
            response<=8'd0;
            done<=1'b0;
        end else begin
            done<=start;
            if (start) begin
              case(command)
                2'd0: begin
                  acc<=next_acc;
                  pc<=next_pc;
                  zero_flag<=next_acc==8'd0;
                  if (opcode==4'hA) out_latch<=acc;
                  response<=next_acc;
                end
                2'd1: begin
                  response<=data;
                  if (location==4'd12) out_latch<=data;
                  if (location==4'd14) begin acc<=data; zero_flag<=data==8'd0; end
                  if (location==4'd15) pc<=data[2:0];
                end
                2'd2: response<=inspected;
                2'd3: response<=acc;
              endcase
            end
        end
    end
endmodule
