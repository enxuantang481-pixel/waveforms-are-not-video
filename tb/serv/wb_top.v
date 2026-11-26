// SERV 的参考 SoC（servant）跑仓库自带的 zephyr_hello.hex。
// servant 本体来自 olofk/serv（ISC 许可），这里只是薄封装。
`default_nettype none
module wb_top(input wire clk, input wire rst, output wire done);
   wire q;
   servant
     #(.memfile  ("zephyr_hello.hex"),
       .memsize  (8192),
       .width    (1),
       .debug    (1'b0),
       .sim      (1),
       .with_csr (1),
       .compress (1'b0),
       .align    (1'b0))
   dut(clk, rst, q);
   assign done = 1'b0;
endmodule
`default_nettype wire
