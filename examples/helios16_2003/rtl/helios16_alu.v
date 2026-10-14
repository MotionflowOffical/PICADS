// HELIOS-16 demonstration datapath, 2003-inspired 16-bit embedded RISC.
module helios16_alu (
    input wire [2:0] operation,
    input wire [15:0] a,
    input wire [15:0] b,
    output reg [15:0] result,
    output wire zero
);
    always @* begin
        case (operation)
            3'd0: result = a + b;
            3'd1: result = a - b;
            3'd2: result = a & b;
            3'd3: result = a | b;
            3'd4: result = a ^ b;
            3'd5: result = a << b[3:0];
            3'd6: result = a >> b[3:0];
            default: result = (a == b) ? 16'h0001 : 16'h0000;
        endcase
    end
    assign zero = (result == 16'h0000);
endmodule
