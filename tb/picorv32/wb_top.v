// PicoRV32 + 行为级存储器。改自 picorv32/dhrystone/testbench.v（ISC 许可），
// 去掉了自带的时钟和 $dumpvars，时钟复位由 C++ 主程序驱动。
`timescale 1 ns / 1 ps
module wb_top(input clk, input rst, output done);
	wire resetn = !rst;
	wire trap;
	wire mem_valid, mem_instr, mem_ready;
	wire [31:0] mem_addr, mem_wdata;
	wire [3:0] mem_wstrb;
	reg  [31:0] mem_rdata;
	wire mem_la_read, mem_la_write;
	wire [31:0] mem_la_addr, mem_la_wdata;
	wire [3:0] mem_la_wstrb;

	picorv32 #(
		.BARREL_SHIFTER(1),
		.ENABLE_FAST_MUL(1),
		.ENABLE_DIV(1),
		.PROGADDR_RESET('h10000),
		.STACKADDR('h10000)
	) uut (
		.clk(clk), .resetn(resetn), .trap(trap),
		.mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
		.mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb), .mem_rdata(mem_rdata),
		.mem_la_read(mem_la_read), .mem_la_write(mem_la_write),
		.mem_la_addr(mem_la_addr), .mem_la_wdata(mem_la_wdata), .mem_la_wstrb(mem_la_wstrb),
		.pcpi_wr(1'b0), .pcpi_rd(32'b0), .pcpi_wait(1'b0), .pcpi_ready(1'b0), .irq(32'b0)
	);

	reg [7:0] memory [0:256*1024-1];
	initial $readmemh("dhry.hex", memory);

	assign mem_ready = 1;
	assign done = resetn && trap;

	always @(posedge clk) begin
		mem_rdata[ 7: 0] <= mem_la_read ? memory[mem_la_addr[17:0] + 0] : 8'b0;
		mem_rdata[15: 8] <= mem_la_read ? memory[mem_la_addr[17:0] + 1] : 8'b0;
		mem_rdata[23:16] <= mem_la_read ? memory[mem_la_addr[17:0] + 2] : 8'b0;
		mem_rdata[31:24] <= mem_la_read ? memory[mem_la_addr[17:0] + 3] : 8'b0;
		if (mem_la_write) begin
			if (mem_la_addr == 32'h1000_0000) begin
				$write("%c", mem_la_wdata[7:0]);
			end else begin
				if (mem_la_wstrb[0]) memory[mem_la_addr[17:0] + 0] <= mem_la_wdata[ 7: 0];
				if (mem_la_wstrb[1]) memory[mem_la_addr[17:0] + 1] <= mem_la_wdata[15: 8];
				if (mem_la_wstrb[2]) memory[mem_la_addr[17:0] + 2] <= mem_la_wdata[23:16];
				if (mem_la_wstrb[3]) memory[mem_la_addr[17:0] + 3] <= mem_la_wdata[31:24];
			end
		end
	end
endmodule
