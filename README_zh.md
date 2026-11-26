# waveform-codec-bench（中文说明）

把单时钟、周期级的数字仿真波形当成“周期 × 比特”的 0/1 矩阵，用视频编码器（FFV1、x264 无损）和列式数据表（Parquet、DuckDB）去存，和 VCD、VCD 加 zstd、FST 比体积、编码时间和两种读法的耗时。每个文件解码后都和原矩阵逐位比对。

结论和全部数字在 `RESULTS.md`，最上面是一屏以内的汇总。

另有一个英文的本地网站（`web/`）把结论做成了可交互的图表，以及一个命令行小工具（`wavebench/cli.py`），可以在你自己的 VCD/FST 上跑同样的比较。都没有公开发布。

## 本地打开网站

网站是纯静态文件，不需要构建，也不联网。两种打开方式：

- 直接双击 `web/index.html`（浏览器用 `file://` 打开即可，脚本不需要服务器）；
- 或者在仓库根目录起一个本地服务器，再打开 <http://127.0.0.1:8765/>：

```
python -m http.server 8765 --bind 127.0.0.1 --directory web
```

页面上的数字全部由 `web/build_data.py` 从 `results/` 的 CSV 生成到 `web/data/bench.js`，改了数据后重新运行 `python web/build_data.py` 即可。某个波形如果在 `results/idle/` 里有空闲复测的结果，就用复测的；否则用第一、二轮的，并在页面上标成“机器不空闲，待复测”。设计调研和取舍见 `web/DESIGN_NOTES.md`。

## 命令行小工具

在 WSL / Linux 里，装好环境（见下面“复现”）后：

```
source scripts/common.sh
python -m wavebench.cli my_wave.vcd                 # 默认 5 种关键存法
python -m wavebench.cli my_wave.fst --all           # 再加 VCD、VCD+zstd、Parquet 长表、DuckDB、x264
python -m wavebench.cli my_wave.vcd --json out.json
```

它读入波形，检查是两态、采样时刻等间隔，然后对每种存法写出、完整解码逐位核对、测“取一个信号”和“取一个时刻”的耗时，打印绝对值和相对“FST 默认档 + 进程内 libfst”的倍数。限制：有 x/z 直接报错；采样时刻不等间隔、展开后矩阵超过 2 GB（`--max-gb` 可调）时报错；实数信号跳过并列出。需要先运行 `bash scripts/build_tools.sh` 编出 `libfstq.so`。

## 文件

- `RESULTS.md`：结论、数字、每个数字的命令和规模、没验证的事项
- `PLAN.md`：计划、核心问题、进度清单、修订方案
- `ISSUES.md`：过程中遇到的问题（现象、原因、解决、对结论的影响）
- `LATER.md`：主线外的想法，没做
- `results/*.csv`：原始测量数据（每行一个格式，含命令行、次数、当时的系统负载）
- `results/summary.md`：由 CSV 生成的结果表；`results/*_size_vs_read.png`：体积对读取耗时的图
- `results/analog.csv`：第二种数据（SPICE 模拟波形）的结果
- `results/serv_x10.csv`、`results/biriscv_x4.csv`：拉长波形的结果；`results/vcd2df_*.csv`：和已有工作 vcd2df 的对照
- `tools/`：`fstq.c` 和 `fstlib.c`（调 libfst 的命令行和共享库），`check_biriscv_workload.py`（核对 biRISC-V 负载的计算结果）
- `writeup/`：面向工程师的短文草稿（中文、英文各一份），没有发布
- `web/`：本地网站（`index.html`、`method.html`、`assets/`、`data/bench.js`、`build_data.py`、`DESIGN_NOTES.md`）
- `wavebench/cli.py`：命令行小工具
- `results/idle/`：空闲机器复测的原始数据和测量条件日志；`scripts/rerun_idle.sh` 是复测脚本
- `sample/`：PicoRV32 前 4096 个周期的比特矩阵和信号表，供不重跑仿真时试脚本

## 复现

全部在 WSL Ubuntu 24.04 里做。建 Python 环境不需要 sudo；Verilator、Icarus、GTKWave、RISC-V 交叉编译器是系统里 apt 装好的（版本见 `env/tool-versions.txt`）。

```
bash env/setup_wsl.sh        # 建 micromamba 环境（约 2 GB，装在 ~/.local/opt/wavebench）
bash scripts/run_all.sh      # 克隆三个核、仿真、测量、出图。顺序跑，约一到两小时
bash scripts/run_analog.sh   # 第二种数据：三个自写 SPICE 网表
```

第二轮（拉长波形、进程内 libfst、vcd2df 对照）的命令写在 `RESULTS.md` 对应小节里，没有并进 `run_all.sh`。vcd2df 对照另需 `pip install vcd2df pandas`。

大文件（波形、编码结果、克隆的核）放在 `~/.cache/wavebench`，可用环境变量 `WAVEBENCH_WORK` 改位置。运行中峰值占用约 6 GB，跑完可以整个删掉。

## 数字来源

`RESULTS.md` 里的每个数字都来自 `results/*.csv` 的某一行，由 `wavebench/bench.py` 或 `wavebench/analog.py` 实测写入；CSV 的 `command` 列是实际执行的编码命令。耗时都在一台笔记本上测：第一、二轮机器不空闲；空闲复测（关睿频）的结果在 `results/idle/`，网站和 `RESULTS.md` 汇总用的是复测数字。只能比较倍数，不能当绝对性能引用。

## 没验证的事项

见 `RESULTS.md` 的“没验证的事项”一节。最要紧的三条：耗时没有在空闲机器上测过；波形最长 262 万周期，而且那个长波形后段变闲；FST 取一个时刻只试了 libfst 的一种用法，没有调数据块大小。

## 第三方设计和工具的许可证

被仿真的三个核不在本仓库里，由 `scripts/fetch_designs.sh` 从各自的官方仓库按固定提交克隆：

| 设计 | 来源 | 许可证 |
|---|---|---|
| PicoRV32 | https://github.com/YosysHQ/picorv32 | ISC |
| SERV | https://github.com/olofk/serv | ISC |
| biRISC-V | https://github.com/ultraembedded/biriscv | Apache-2.0 |

`tb/` 下的顶层封装改自这些仓库自带的测试平台，文件头注明了来源。`tb/biriscv/prog/` 和 `analog/netlists/` 是本项目自己写的。

用到的工具（都不随本仓库分发）：Verilator（LGPL-3.0 或 Artistic-2.0）、GTKWave 及其 `fstapi.c`（`tools/fstq.c` 编译时链接；GTKWave 为 GPL-2.0，`fstapi.c` 文件头为 MIT 式许可）、FFmpeg 及 libx264（conda-forge 的构建，GPL）、Apache Arrow / Parquet（Apache-2.0）、DuckDB（MIT）、wellen / pywellen（BSD-3-Clause）、zstd（BSD）、ngspice（BSD-3-Clause）、PyAV（BSD-3-Clause）、vcd2df（许可证没查）、pandas（BSD-3-Clause）。许可证名称是按我的了解写的，没有逐个核对各项目当前的许可证文件，对外使用前请核对。

本项目的代码按 MIT 许可证发布（见 `LICENSE`）；改编自第三方的两个测试平台文件保留原许可证，见 `tb/THIRD_PARTY_NOTICES.md`。
