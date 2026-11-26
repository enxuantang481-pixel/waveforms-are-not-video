// 统一的 Verilator 主程序：单时钟，每个周期只转储一次（上升沿求值之后）。
// 用法：Vwb_top <最大周期数> <输出波形文件>
// 编译时定义 TRACE_FST 则写 FST，否则写 VCD。
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "Vwb_top.h"
#include "verilated.h"
#ifdef TRACE_FST
#include "verilated_fst_c.h"
typedef VerilatedFstC Tracer;
#else
#include "verilated_vcd_c.h"
typedef VerilatedVcdC Tracer;
#endif

#ifndef RESET_CYCLES
#define RESET_CYCLES 16
#endif

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <max_cycles> <out>\n", argv[0]); return 2; }
    Verilated::commandArgs(argc, argv);
    Verilated::traceEverOn(true);
    const uint64_t max_cycles = strtoull(argv[1], nullptr, 10);
    Vwb_top* top = new Vwb_top;
    Tracer* tfp = new Tracer;
    top->trace(tfp, 99);
    tfp->open(argv[2]);
    top->clk = 0; top->rst = 1; top->eval();
    uint64_t c = 0;
    for (; c < max_cycles && !Verilated::gotFinish(); c++) {
        top->rst = (c < RESET_CYCLES);
        top->clk = 1; top->eval();
        tfp->dump(c);            // 时间戳就是周期号
        top->clk = 0; top->eval();
        if (top->done) { c++; break; }
    }
    tfp->close();
    top->final();
    fprintf(stderr, "\n[sim_main] cycles=%llu\n", (unsigned long long)c);
    delete tfp; delete top;
    return 0;
}
