#!/usr/bin/env bash
# 编译 tools/fstq（命令行）和 libfstq.so（进程内读取）：链接 Verilator 自带的 GTKWave FST 读取库源码（fstapi.c、lz4.c、fastlz.c）和系统 zlib。
set -euo pipefail
source "$(dirname "$0")/common.sh"
G=/usr/share/verilator/include/gtkwave
mkdir -p "$WAVEBENCH_WORK/bin"
gcc -O2 -w -DFST_CONFIG_INCLUDE=\"fst_config.h\" -I"$G" -o "$WAVEBENCH_WORK/bin/fstq" "$WAVEBENCH_ROOT/tools/fstq.c" "$G/fstapi.c" "$G/lz4.c" "$G/fastlz.c" -lz
gcc -O2 -w -shared -fPIC -DFST_CONFIG_INCLUDE=\"fst_config.h\" -I"$G" -o "$WAVEBENCH_WORK/bin/libfstq.so" "$WAVEBENCH_ROOT/tools/fstlib.c" "$G/fstapi.c" "$G/lz4.c" "$G/fastlz.c" -lz
echo "$WAVEBENCH_WORK/bin/fstq" "$WAVEBENCH_WORK/bin/libfstq.so"
