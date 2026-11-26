# Waveforms are not video

Can digital simulation waveforms be stored smaller, or read faster, as **video** (FFV1, lossless x264), as **tables** (Parquet, DuckDB), or with **plain compression** than in FST? A benchmark on three open-source RISC-V cores, with every file decoded and checked bit for bit against the original.

**Website:** https://enxuantang481-pixel.github.io/waveforms-are-not-video/ (interactive charts, method, limitations)

## Main results

- **Video loses on size everywhere.** On the three original waveforms, the best of 12 video layouts is still 1.8–3.7× the size of default FST, and most are 5–70×.
- **Plain bit-packing plus zstd beats default FST** (0.06–0.66× its size) with no waveform knowledge at all, but beats the smallest FST mode only on SERV. Video does not even beat this.
- **A wide Parquet table (one column per signal) wins one-cycle reads**: reading all signals at one cycle is 7–15× faster than in-process libfst. Reading one signal over time depends on the design (about 2–4× faster on PicoRV32 and SERV, a tie on biRISC-V), and the size gap to the smallest FST grows on long, quiet waveforms.
- **Table orientation decides everything**: the same content stored one column per time point (as in the earlier vcd2df work, arXiv 2505.06470) is about 10× larger than one column per signal.

## Try it on your own waveform

```
source scripts/common.sh
python -m wavebench.cli my_wave.vcd            # 5 key formats
python -m wavebench.cli my_wave.fst --all      # adds VCD, VCD+zstd, Parquet long, DuckDB, x264
```

It writes each format, decodes and verifies it bit for bit, and times both reads. Two-state waveforms with evenly spaced sample times only; it stops with a message otherwise.

## Reproduce

Everything runs in WSL / Ubuntu 24.04. Verilator, GTKWave and a RISC-V cross compiler come from apt (versions in `env/tool-versions.txt`); the Python environment needs no sudo.

```
bash env/setup_wsl.sh        # micromamba environment (~2 GB)
bash scripts/run_all.sh      # fetch the cores, simulate, measure, plot (1–2 hours)
bash scripts/rerun_idle.sh   # the idle-machine re-measurement
bash scripts/check_pq_serv_x10.sh  # follow-up check of one timing (ISSUES.md item 19)
python web/build_data.py     # regenerate the website data from results/
```

To view the site locally, open `web/index.html` or run `python -m http.server 8765 --directory web`.

## Limits

- Three small RISC-V cores (2,381–9,728 bits), at most 2.6 million cycles, two-state only, one clock, one sample per cycle.
- **Timings were measured on one laptop** (Intel Core Ultra 9 185H, WSL2). The site and the results above use an idle re-run with turbo boost off (`results/idle/`); the earlier rounds on a busy machine are kept in `results/`. Use them for ratios, not absolute performance: turning turbo off was enough to change which format reads one signal faster on biRISC-V.
- FST was not tuned (default block size, one way of reading a cycle with libfst).

## Repository

- `web/`: the website (static, no third-party code); design notes in `web/DESIGN_NOTES.md`
- `wavebench/`: measurement code; `wavebench/cli.py` is the command-line tool
- `results/`: raw measurements (CSV, one row per format, with commands and machine load)
- `RESULTS.md`, `PLAN.md`, `ISSUES.md`, `README_zh.md`: detailed notes (in Chinese), including tool licenses
- `writeup/`: short article drafts (Chinese and English)

## License

MIT for this project's code (see `LICENSE`). The RISC-V cores are not included; they are cloned from upstream by `scripts/fetch_designs.sh`: [PicoRV32](https://github.com/YosysHQ/picorv32) (ISC), [SERV](https://github.com/olofk/serv) (ISC), [biRISC-V](https://github.com/ultraembedded/biriscv) (Apache-2.0). Two adapted testbench files keep their original licenses; see `tb/THIRD_PARTY_NOTICES.md`.
