// Small single-issue 16-bit RISC execution controller.
// Sequential instruction execution at 10 MHz, simple vectored timer IRQ.
module helios16_control (
    input wire clk,
    input wire reset,
    input wire run,
    input wire irq,
    input wire uart_busy,
    input wire [15:0] instruction,
    input wire [15:0] ra_data,
    input wire [15:0] rb_data,
    input wire [15:0] alu_result,
    input wire [15:0] mem_rd_data,
    output reg [15:0] pc,
    output reg halted,
    output wire [2:0] ra_addr,
    output wire [2:0] rb_addr,
    output wire [2:0] wr_addr,
    output reg [15:0] wr_data,
    output reg wr_en,
    output reg [2:0] alu_op,
    output wire [15:0] alu_a,
    output wire [15:0] alu_b,
    output wire [5:0] mem_addr,
    output wire [15:0] mem_wr_data,
    output reg mem_wr,
    output reg io_we,
    output wire [1:0] io_sel,
    output wire [15:0] io_data
);
    wire [3:0] op=instruction[15:12];
    wire [15:0] signed_imm6={{10{instruction[5]}},instruction[5:0]};
    wire [15:0] signed_imm9={{7{instruction[8]}},instruction[8:0]};
    wire [15:0] signed_imm12={{4{instruction[11]}},instruction[11:0]};
    wire interrupt_now=irq && irq_enable;
    reg irq_enable;
    reg [15:0] irq_return;
    assign ra_addr=(op==4'he) ? instruction[11:9] : instruction[8:6];
    assign rb_addr=(op==4'h9 || op==4'ha) ? instruction[11:9] : instruction[5:3];
    assign wr_addr=instruction[11:9];
    assign alu_a=ra_data;
    assign alu_b=rb_data;
    assign mem_addr=(ra_data+signed_imm6) & 16'h003f;
    assign mem_wr_data= (wr_addr==3'b000) ? 16'd0 : rb_data;
    assign io_sel=instruction[1:0];
    assign io_data=ra_data;
    always @* begin
        wr_data=alu_result;
        wr_en=0;mem_wr=0;io_we=0;alu_op=0;
        if (run && !halted && !interrupt_now) begin
            case(op)
                4'h1: begin alu_op=0;wr_en=1;end
                4'h2: begin alu_op=1;wr_en=1;end
                4'h3: begin alu_op=2;wr_en=1;end
                4'h4: begin alu_op=3;wr_en=1;end
                4'h5: begin alu_op=4;wr_en=1;end
                4'h6: begin alu_op=5;wr_en=1;end
                4'h7: begin wr_data=signed_imm9;wr_en=1;end
                4'h8: begin wr_data=mem_rd_data;wr_en=1;end
                4'h9: begin mem_wr=1;end
                4'hc: begin wr_data={instruction[7:0],8'b0};wr_en=1;end
                4'he: begin io_we=(io_sel!=0 || !uart_busy);end
                default: begin end
            endcase
        end
    end
    always @(posedge clk) begin
        if (reset) begin
            pc<=0;halted<=0;irq_enable<=0;irq_return<=0;
        end else if (run && !halted) begin
            if (interrupt_now) begin
                irq_return<=pc;pc<=16'h0060;irq_enable<=0;
            end else begin
                pc<=pc+1'b1;
                case(op)
                    4'ha: if (ra_data==rb_data) pc<=pc+1'b1+signed_imm6;
                    4'hb: pc<=pc+1'b1+signed_imm12;
                    4'hd: begin
                        if (instruction[1:0]==2'd0) irq_enable<=1;
                        if (instruction[1:0]==2'd1) irq_enable<=0;
                        if (instruction[1:0]==2'd2) begin pc<=irq_return;irq_enable<=1;end
                    end
                    4'hf: halted<=1;
                    default: begin end
                endcase
            end
        end
    end
endmodule
