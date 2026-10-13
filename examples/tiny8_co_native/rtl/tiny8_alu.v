// SKY130 hard macro: shared arithmetic/logic datapath.
module tiny8_alu (
    input [3:0] opcode,
    input [7:0] lhs,
    input [7:0] rhs,
    output reg [7:0] result
);
    always @* begin
        case (opcode)
          4'h3: result = lhs + rhs;
          4'h4: result = lhs - rhs;
          4'h5: result = lhs & rhs;
          4'h6: result = lhs ^ rhs;
          4'hB: result = lhs | rhs;
          default: result = lhs;
        endcase
    end
endmodule
