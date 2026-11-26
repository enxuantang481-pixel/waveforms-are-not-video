# Third-party notices

The three RISC-V cores themselves are **not** included in this repository; `scripts/fetch_designs.sh` clones them from their upstream repositories at fixed commits. Two small testbench wrappers here are adapted from files in those repositories, and are distributed under the original licenses below.

## tb/picorv32/wb_top.v

Adapted from `dhrystone/testbench.v` in https://github.com/YosysHQ/picorv32 (commit ef203c2b). Modified for this project: the built-in clock and `$dumpvars` were removed; clock and reset are driven from the C++ harness.

```
ISC License

Copyright (C) 2015 - 2021  Claire Xenia Wolf <claire@yosyshq.com>

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## tb/biriscv/wb_top.v

Adapted from `tb/tb_core_icarus/tb_top.v` in https://github.com/ultraembedded/biriscv (commit 6af9c4be), licensed under the Apache License, Version 2.0 (full text in `tb/biriscv/LICENSE-Apache-2.0.txt`). Modified for this project: the built-in clock and `$dumpvars` were removed and memory is preloaded with `$readmemh`.

## tb/serv/wb_top.v

A thin wrapper written for this project that instantiates `servant` from https://github.com/olofk/serv (ISC License, Copyright 2019, Olof Kindgren). No SERV source is included here.

## Everything else

`tb/biriscv/prog/`, `tb/common/`, `analog/netlists/`, `tools/`, `wavebench/`, `scripts/` and `web/` were written for this project and are covered by the repository's MIT `LICENSE`. `sample/` holds simulation output (a bit matrix) of PicoRV32 running its bundled Dhrystone benchmark.
