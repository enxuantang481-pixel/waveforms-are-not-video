/* 波形不是视频 — 页面脚本。数据来自 data/bench.js（由 web/build_data.py 从 results/ 生成）。无第三方库。 */
(function () {
  "use strict";
  const D = window.BENCH;
  const $ = (s, el = document) => el.querySelector(s);
  const setAll = (s, v) => document.querySelectorAll(s).forEach((n) => { n.textContent = v; });
  const NS = "http://www.w3.org/2000/svg";

  // ---------- 文字 ----------
  // 网站只用英文（2026-11-26 用户要求）。数据里仍带中英两套标签，这里只取英文。
  const lang = () => "en";
  const L = (zh, en) => en;
  const rerenders = [];

  // ---------- 小工具 ----------
  const el = (tag, attrs = {}, parent) => {
    const e = tag.startsWith("svg:") ? document.createElementNS(NS, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") e.textContent = v;
      else if (v !== undefined && v !== null) e.setAttribute(k, v);
    }
    if (parent) parent.appendChild(e);
    return e;
  };
  const sig3 = (x) => {
    if (x == null || !isFinite(x)) return "–";
    const a = Math.abs(x);
    if (a >= 100) return x.toFixed(0);
    if (a >= 10) return x.toFixed(1);
    if (a >= 1) return x.toFixed(2);
    return x.toPrecision(2);
  };
  const ratio = (x) => (x == null ? "–" : sig3(x) + "×");
  const bytes = (b) => {
    if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
    if (b >= 1e6) return (b / 1e6).toFixed(2) + " MB";
    if (b >= 1e3) return (b / 1e3).toFixed(1) + " KB";
    return b + " B";
  };
  const secs = (s) => {
    if (s == null) return "–";
    if (s >= 1) return s.toFixed(s >= 10 ? 1 : 2) + " s";
    return (s * 1000).toFixed(s * 1000 >= 10 ? 0 : 1) + " ms";
  };
  const range = (xs, f = sig3) => {
    const lo = Math.min(...xs), hi = Math.max(...xs);
    return f(lo) === f(hi) ? f(lo) : f(lo) + "–" + f(hi);
  };
  const FAM = {
    base: { zh: "VCD / FST（对照）", en: "VCD / FST (baseline)", color: "var(--base)", shape: "circle" },
    table: { zh: "数据表", en: "Tables", color: "var(--table)", shape: "square" },
    video: { zh: "视频", en: "Video", color: "var(--video)", shape: "triangle" },
    bitpack: { zh: "打包矩阵 + 通用压缩", en: "Bit-pack + general compressor", color: "var(--bitpack)", shape: "diamond" },
  };
  function shape(g, kind, x, y, r, color) {
    let e;
    if (kind === "square") e = el("svg:rect", { x: x - r, y: y - r, width: 2 * r, height: 2 * r, rx: 1.5 }, g);
    else if (kind === "triangle") e = el("svg:path", { d: `M${x},${y - r * 1.25}L${x + r * 1.15},${y + r * 0.8}L${x - r * 1.15},${y + r * 0.8}Z` }, g);
    else if (kind === "diamond") e = el("svg:path", { d: `M${x},${y - r * 1.3}L${x + r * 1.3},${y}L${x},${y + r * 1.3}L${x - r * 1.3},${y}Z` }, g);
    else e = el("svg:circle", { cx: x, cy: y, r }, g);
    e.setAttribute("fill", color);
    e.setAttribute("class", "pt");
    return e;
  }
  function swatchSvg(kind, color) {
    const s = el("svg:svg", { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true" });
    const p = shape(s, kind, 7, 7.5, 4.5, color);
    p.setAttribute("stroke", "none");
    return s;
  }
  const rowsOf = (w) => D.rows.filter((r) => r.w === w);
  const get = (w, fmt) => D.rows.find((r) => r.w === w && r.fmt === fmt);
  const waveById = (id) => D.waves.find((w) => w.id === id);
  const BASE3 = ["picorv32", "serv", "biriscv"];
  const ALL = D.waves.map((w) => w.id);
  const FST_SMALL = (w) => get(w, "fst-zlib-c+inproc") || get(w, "fst-zlib-c");

  // ---------- 首屏：同一批比特，两种看法 ----------
  function hero() {
    const root = $("#twoview");
    if (!root) return;
    const H = D.hero;
    const raw = atob(H.bits_b64);
    const buf = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
    const BPR = H.cycles / 8;
    const bit = (b, c) => (buf[b * BPR + (c >> 3)] >> (7 - (c & 7))) & 1;
    const val = (s, c) => { let v = 0n; for (let i = 0; i < s.width; i++) v = (v << 1n) | BigInt(bit(s.col + i, c)); return v; };

    const cv = $("#pixels canvas");
    cv.width = H.cycles; cv.height = H.rows;
    const ctx = cv.getContext("2d");
    function paint() {
      const cs = getComputedStyle(document.documentElement);
      const on = cs.getPropertyValue("--pixel-on").trim(), off = cs.getPropertyValue("--pixel-off").trim();
      const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
      const [a, b] = [hex(on), hex(off)];
      const img = ctx.createImageData(H.cycles, H.rows);
      for (let r = 0; r < H.rows; r++) for (let c = 0; c < H.cycles; c++) {
        const p = (r * H.cycles + c) * 4, v = bit(r, c) ? a : b;
        img.data[p] = v[0]; img.data[p + 1] = v[1]; img.data[p + 2] = v[2]; img.data[p + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
    }
    paint();
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);

    let start = 96;
    const win = $("#pixels .win");
    const span = () => (root.clientWidth < 560 ? 24 : 40);
    function draw() {
      const W = span();
      start = Math.max(0, Math.min(H.cycles - W, start));
      win.style.left = (start / H.cycles * 100) + "%";
      win.style.width = (W / H.cycles * 100) + "%";
      setAll(".win-from", start);
      setAll(".win-to", start + W - 1);
      viewer(W);
    }
    function viewer(W) {
      const box = $("#viewer");
      box.textContent = "";
      const width = Math.max(300, box.clientWidth);
      const nameW = width < 480 ? 92 : 118, rowH = 26, top = 18;
      const sigs = H.signals;
      const height = top + sigs.length * rowH + 4;
      const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
        "aria-label": L(`PicoRV32 第 ${start} 到 ${start + W - 1} 周期的 ${sigs.length} 根信号`, `${sigs.length} PicoRV32 signals, cycles ${start} to ${start + W - 1}`) }, box);
      const x0 = nameW, cw = (width - nameW - 4) / W;
      const gg = el("svg:g", {}, svg);
      for (let k = 0; k <= W; k += 8) {
        const x = x0 + k * cw;
        el("svg:line", { x1: x, x2: x, y1: top - 4, y2: height, stroke: "var(--grid)" }, gg);
        if (k < W) el("svg:text", { x: x + 3, y: 11, class: "tick", text: String(start + k) }, gg);
      }
      sigs.forEach((s, i) => {
        const y = top + i * rowH, yh = y + 5, yl = y + rowH - 7, ym = (yh + yl) / 2;
        el("svg:text", { x: 0, y: ym + 4, class: "sig", text: s.width > 1 ? `${s.name}[${s.width - 1}:0]` : s.name }, svg);
        if (s.width === 1) {
          let d = "";
          for (let c = 0; c < W; c++) {
            const yy = bit(s.col, start + c) ? yh : yl, xa = x0 + c * cw, xb = xa + cw;
            d += (c === 0 ? `M${xa},${yy}` : `L${xa},${yy}`) + `L${xb},${yy}`;
          }
          el("svg:path", { d, fill: "none", stroke: "var(--trace)", "stroke-width": 1.6, "stroke-linejoin": "round" }, svg);
        } else {
          let c = 0;
          while (c < W) {
            const v = val(s, start + c);
            let e = c + 1;
            while (e < W && val(s, start + e) === v) e++;
            const xa = x0 + c * cw + 1, xb = x0 + e * cw - 1, sl = Math.min(3, (xb - xa) / 3);
            el("svg:path", { d: `M${xa},${ym}L${xa + sl},${yh}L${xb - sl},${yh}L${xb},${ym}L${xb - sl},${yl}L${xa + sl},${yl}Z`,
              fill: "var(--wash)", stroke: "var(--trace)", "stroke-width": 1.2 }, svg);
            const txt = v.toString(16);
            if ((xb - xa) > txt.length * 6.6 + 6) el("svg:text", { x: (xa + xb) / 2, y: ym + 3.6, "text-anchor": "middle", class: "bus", text: txt }, svg);
            c = e;
          }
        }
      });
    }
    function fromPointer(ev) {
      const r = cv.getBoundingClientRect();
      start = Math.round((ev.clientX - r.left) / r.width * H.cycles - span() / 2);
      draw();
    }
    let dragging = false;
    cv.addEventListener("pointerdown", (e) => { dragging = true; cv.setPointerCapture(e.pointerId); fromPointer(e); });
    cv.addEventListener("pointermove", (e) => { if (dragging) fromPointer(e); });
    cv.addEventListener("pointerup", () => { dragging = false; });
    cv.tabIndex = 0;
    cv.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") { start += 8; draw(); e.preventDefault(); }
      if (e.key === "ArrowLeft") { start -= 8; draw(); e.preventDefault(); }
    });
    setAll(".hero-bits", H.rows.toLocaleString());
    setAll(".hero-total", H.total_bits.toLocaleString());
    draw();
    rerenders.push(draw);
    window.addEventListener("resize", draw);
  }

  // ---------- 四条结论（数字从数据里算） ----------
  function findings() {
    const box = $("#findings");
    if (!box) return;
    const fill = (id, zh, en) => { const n = document.getElementById(id); if (n) n.textContent = en; };
    // 1. 视频体积
    const bestVid = (w) => Math.min(...rowsOf(w).filter((r) => r.family === "video").map((r) => r.size_rel));
    const b3 = BASE3.map(bestVid);
    const nVid = new Set(D.rows.filter((r) => r.family === "video").map((r) => r.fmt)).size;
    $("#f1-fig").textContent = range(b3) + "×";
    const longs = ALL.filter((w) => !BASE3.includes(w));
    const lv = longs.map((w) => {
      const r = rowsOf(w).filter((x) => x.family === "video").sort((a, b) => a.size_rel - b.size_rel)[0];
      return { w, r, vsSmall: r.size / FST_SMALL(w).size };
    });
    const below1 = lv.filter((x) => x.r.size_rel < 1);
    fill("f1-text",
      `${nVid} 种视频排法，在三个原始波形上最好的一种也是 FST 默认档的 ${range(b3)} 倍。` +
      (below1.length ? `拉长后唯一的例外是 ${below1.map((x) => waveById(x.w).zh).join("、")}：${below1.map((x) => x.r.zh).join("、")} 降到默认档的 ${below1.map((x) => sig3(x.r.size_rel)).join("、")} 倍，但仍是 FST 最小档的 ${below1.map((x) => sig3(x.vsSmall)).join("、")} 倍。` : "拉长的两个波形上也没有例外。"),
      `Across ${nVid} video layouts, the best one is still ${range(b3)}× the default FST file on the three original waveforms.` +
      (below1.length ? ` The one exception after lengthening is ${below1.map((x) => waveById(x.w).en).join(", ")}: ${below1.map((x) => x.r.en).join(", ")} drops to ${below1.map((x) => sig3(x.r.size_rel)).join(", ")}× of default FST, yet is still ${below1.map((x) => sig3(x.vsSmall)).join(", ")}× the smallest FST.` : " No exception on the two longer waveforms either."));
    // 2. 打包矩阵 + zstd
    const bp = ALL.map((w) => ({ w, r: get(w, "bitpack-sm.zst19") })).filter((x) => x.r);
    $("#f2-fig").textContent = range(bp.map((x) => x.r.size_rel)) + "×";
    const beatSmall = bp.filter((x) => x.r.size < FST_SMALL(x.w).size).map((x) => waveById(x.w));
    fill("f2-text",
      `把 0/1 矩阵按位打包后直接 zstd -19，不带任何波形知识，在全部 ${bp.length} 个波形上都比 FST 默认档小；但只在 ${beatSmall.map((w) => w.zh).join(" 和 ") || "没有一个波形"}上比 FST 最小档小。视频路线连它都赢不了。`,
      `Bit-packing the 0/1 matrix and running zstd -19 over it, with no knowledge of waveforms, beats default FST on all ${bp.length} waveforms, but beats the smallest FST only on ${beatSmall.map((w) => w.en).join(" and ") || "none of them"}. Video does not even beat this.`);
    // 3. Parquet 宽表
    const pq = ALL.map((w) => get(w, "parquet-wide-zstd19-rg65536")).filter(Boolean);
    const sp = pq.map((r) => 1 / r.rtime_rel);
    $("#f3-fig").textContent = range(sp, (x) => x.toFixed(0)) + "×";
    const rs = pq.map((r) => r.rsig_rel);
    // 取一个信号是几毫秒量级，±20% 以内算打平，不说谁快
    const band = (lo, hi) => pq.filter((r) => r.rsig_rel >= lo && r.rsig_rel < hi);
    const parts = [[band(0, 0.8), "faster"], [band(0.8, 1.25), "about the same"], [band(1.25, Infinity), "slower"]]
      .filter(([g]) => g.length)
      .map(([g, word]) => `${word} on ${g.map((r) => waveById(r.w).en.replace(", ", " ").replace(" cycles", "")).join(", ")} (${range(g.map((r) => r.rsig_rel))}×)`);
    const vsSmall = pq.map((r) => r.size / FST_SMALL(r.w).size);
    fill("f3-text", "",
      `One column per signal. Reading all signals at one cycle is ${range(sp, (x) => x.toFixed(0))}× faster than in-process libfst. Reading one signal across all cycles is ` +
      parts.join("; ") + "." +
      ` Size is ${range(pq.map((r) => r.size_rel))}× default FST and ${range(vsSmall)}× the smallest FST; the gap to the smallest grows as the waveform gets longer and quieter.`);
    // 4. 视频唯一赢的一项
    const fv = ALL.map((w) => get(w, "ffv1-strip-8bpp")).filter(Boolean);
    $("#f4-fig").textContent = secs(Math.min(...fv.map((r) => r.rtime_s))) + "–" + secs(Math.max(...fv.map((r) => r.rtime_s)));
    fill("f4-text",
      `FFV1 每帧独立编码，跳到任一时刻只解一帧：是进程内 libfst 的 ${range(fv.map((r) => r.rtime_rel))} 倍耗时，且不随波形变长而变慢。代价是体积为 FST 默认档的 ${range(fv.map((r) => r.size_rel))} 倍。`,
      `FFV1 codes every frame independently, so seeking to any cycle decodes a single frame: ${range(fv.map((r) => r.rtime_rel))}× the in-process libfst time, and it does not grow with waveform length. The price is ${range(fv.map((r) => r.size_rel))}× the size of default FST.`);
  }

  // ---------- 主图：体积对读取耗时 ----------
  const state = { w: "picorv32", read: "rtime", fams: new Set(["base", "table", "video", "bitpack"]), table: false, sort: ["size_rel", 1] };
  const SCATTER_EXCLUDE = /\+libfst$|^fst-(lz4|zlib-c|fastlz|zlib|lz4-c|verilator)$/;   // 同一 FST 文件只画进程内 libfst 那一次
  const LABELED = ["fst-lz4+inproc", "fst-zlib-c+inproc", "bitpack-sm.zst19", "parquet-wide-zstd19-rg65536", "ffv1-strip-8bpp", "vcd", "x264-medium-strip-8bpp"];
  const short = {
    "fst-lz4+inproc": ["FST 默认档", "FST default"], "fst-zlib-c+inproc": ["FST 最小档", "FST smallest"],
    "bitpack-sm.zst19": ["打包 + zstd -19", "bit-pack + zstd -19"], "parquet-wide-zstd19-rg65536": ["Parquet 宽表", "Parquet wide"],
    "ffv1-strip-8bpp": ["FFV1 条带", "FFV1 strip"], "x264-medium-strip-8bpp": ["x264 条带", "x264 strip"], vcd: ["VCD", "VCD"],
  };
  function logTicks(lo, hi) {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)) + 1; e++)
      for (const m of [1, 2, 5]) { const v = m * Math.pow(10, e); if (v >= lo && v <= hi) out.push(v); }
    if (out.length > 9) return out.filter((v) => Math.abs(Math.log10(v) % 1) < 1e-9 || Math.abs(Math.log10(v) % 1) > 1 - 1e-9);
    return out;
  }
  const tickFmt = (v) => (v >= 1 ? String(+v.toPrecision(3)) : String(+v.toPrecision(2))) + "×";

  function scatter() {
    const box = $("#scatter");
    if (!box) return;
    box.textContent = "";
    const tip = $("#tip");
    const w = waveById(state.w);
    const key = state.read === "rtime" ? "rtime_rel" : "rsig_rel";
    const pts = rowsOf(state.w).filter((r) => !SCATTER_EXCLUDE.test(r.fmt) && r[key] != null && state.fams.has(r.family));
    const width = Math.max(320, box.clientWidth);
    const narrow = width < 560;
    const height = narrow ? 380 : 470;
    const m = { l: narrow ? 48 : 60, r: 16, t: 14, b: 46 };
    const all = rowsOf(state.w).filter((r) => !SCATTER_EXCLUDE.test(r.fmt) && r[key] != null);
    const xs = all.map((r) => r.size_rel).concat([1]), ys = all.map((r) => r[key]).concat([1]);
    const pad = 1.6;
    const [xl, xh] = [Math.min(...xs) / pad, Math.max(...xs) * pad], [yl, yh] = [Math.min(...ys) / pad, Math.max(...ys) * pad];
    const X = (v) => m.l + (Math.log(v) - Math.log(xl)) / (Math.log(xh) - Math.log(xl)) * (width - m.l - m.r);
    const Y = (v) => height - m.b - (Math.log(v) - Math.log(yl)) / (Math.log(yh) - Math.log(yl)) * (height - m.t - m.b);
    const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": L(`${w.zh}：各格式的体积和${state.read === "rtime" ? "取一个时刻" : "取一个信号"}的耗时`, `${w.en}: size versus ${state.read === "rtime" ? "one-cycle" : "one-signal"} read time per format`) }, box);
    const grid = el("svg:g", { class: "grid" }, svg), ticks = el("svg:g", { class: "tick" }, svg);
    logTicks(xl, xh).forEach((v) => {
      el("svg:line", { x1: X(v), x2: X(v), y1: m.t, y2: height - m.b }, grid);
      el("svg:text", { x: X(v), y: height - m.b + 16, "text-anchor": "middle", text: tickFmt(v) }, ticks);
    });
    logTicks(yl, yh).forEach((v) => {
      el("svg:line", { x1: m.l, x2: width - m.r, y1: Y(v), y2: Y(v) }, grid);
      el("svg:text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", text: tickFmt(v) }, ticks);
    });
    el("svg:text", { x: (m.l + width - m.r) / 2, y: height - 8, "text-anchor": "middle", class: "axlabel",
      text: narrow ? L("体积，相对 FST 默认档", "Size vs default FST") : L("体积，相对 FST 默认档（越左越小）", "Size relative to default FST (left is smaller)") }, svg);
    el("svg:text", { x: 12, y: (m.t + height - m.b) / 2, transform: `rotate(-90 12 ${(m.t + height - m.b) / 2})`, "text-anchor": "middle", class: "axlabel",
      text: narrow ? (state.read === "rtime" ? L("取时刻耗时，相对 libfst", "One-cycle read vs libfst") : L("取信号耗时，相对 libfst", "One-signal read vs libfst"))
        : state.read === "rtime" ? L("取一个时刻的耗时，相对 libfst（越低越快）", "One-cycle read time vs libfst (lower is faster)") : L("取一个信号的耗时，相对 libfst（越低越快）", "One-signal read time vs libfst (lower is faster)") }, svg);
    el("svg:line", { x1: X(1), x2: X(1), y1: m.t, y2: height - m.b, class: "refline" }, svg);
    el("svg:line", { x1: m.l, x2: width - m.r, y1: Y(1), y2: Y(1), class: "refline" }, svg);
    el("svg:text", { x: m.l + 6, y: height - m.b - 8, class: "reftext", text: L("更小也更快", "smaller and faster") }, svg);

    // 直接标注：选几个关键点，简单避让
    // 障碍物：所有点（各占 14×14）和已放下的标签；依次试右、左、右上、右下、左上、左下，都不行就往下挪并画引线
    const placed = pts.map((r) => ({ x: X(r.size_rel) - 7, y: Y(r[key]) + 7, w: 14, h: 14 }));
    const lab = el("svg:g", {}, svg);
    pts.filter((r) => LABELED.includes(r.fmt)).sort((a, b) => Y(a[key]) - Y(b[key])).forEach((r) => {
      const t = L(...short[r.fmt]), px = X(r.size_rel), py = Y(r[key]);
      const tw = t.length * (lang() === "zh" ? 12.5 : 6.8);
      const hits = (lx, ly) => lx < m.l || lx + tw > width - m.r || ly - 12 < m.t || ly > height - m.b ||
        placed.some((b) => !(lx + tw < b.x || lx > b.x + b.w || ly < b.y - b.h || ly - 12 > b.y));
      const cands = [[px + 10, py + 4], [px - 10 - tw, py + 4], [px + 8, py - 9], [px + 8, py + 18], [px - 8 - tw, py - 9], [px - 8 - tw, py + 18]];
      let [lx, ly] = cands.find(([a, b]) => !hits(a, b)) || cands[0];
      let tries = 0, moved = false;
      while (hits(lx, ly) && tries++ < 10) { ly += 14; moved = true; }
      placed.push({ x: lx, y: ly, w: tw, h: 12 });
      if (moved) el("svg:line", { x1: px, y1: py, x2: lx < px ? lx + tw : lx - 2, y2: ly - 4, class: "dlabel-line" }, lab);
      el("svg:text", { x: lx, y: ly, class: "dlabel", text: t }, lab);
    });

    const gpts = el("svg:g", {}, svg);
    const show = (r, g, ev) => {
      gpts.querySelectorAll("g.on").forEach((x) => x.classList.remove("on"));
      g.classList.add("on");
      tip.textContent = "";
      const nm = el("div", { class: "t-name" }, tip);
      nm.appendChild(swatchSvg(FAM[r.family].shape, FAM[r.family].color));
      el("span", { text: L(r.zh, r.en) }, nm);
      const row = (v, k) => { const d = el("div", { class: "t-row" }, tip); el("b", { text: v }, d); el("span", { text: k }, d); };
      row(`${ratio(r.size_rel)} (${bytes(r.size)})`, L("体积", "size"));
      row(`${ratio(r.rtime_rel)} (${secs(r.rtime_s)})`, L("取一个时刻", "one cycle"));
      row(`${ratio(r.rsig_rel)} (${secs(r.rsig_s)})`, L("取一个信号", "one signal"));
      el("div", { class: "t-foot", text: L(`读取：${r.reader}；中位数，取时刻 ${r.rtime_n} 次、取信号 ${r.rsig_n} 次；负载 ${sig3(r.loadavg)}`, `reader: ${r.reader}; median of ${r.rtime_n} / ${r.rsig_n} runs; load ${sig3(r.loadavg)}`) }, tip);
      const cb = $("#scatter-card").getBoundingClientRect();
      let px, py;
      if (ev && ev.clientX) { px = ev.clientX - cb.left; py = ev.clientY - cb.top; }
      else { const bb = g.getBoundingClientRect(); px = bb.left + bb.width / 2 - cb.left; py = bb.top - cb.top; }
      tip.classList.add("show");
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      tip.style.left = Math.max(4, Math.min(cb.width - tw - 4, px + 14)) + "px";
      tip.style.top = Math.max(4, py - th - 12 < 0 ? py + 16 : py - th - 12) + "px";
    };
    const hide = () => { tip.classList.remove("show"); gpts.querySelectorAll("g.on").forEach((x) => x.classList.remove("on")); };
    pts.sort((a, b) => (a.family === "base") - (b.family === "base")).forEach((r) => {
      const g = el("svg:g", { tabindex: 0, role: "button", "aria-label": `${L(r.zh, r.en)}: ${L("体积", "size")} ${ratio(r.size_rel)}, ${state.read === "rtime" ? L("取时刻", "one cycle") : L("取信号", "one signal")} ${ratio(r[key])}` }, gpts);
      shape(g, FAM[r.family].shape, X(r.size_rel), Y(r[key]), 5, FAM[r.family].color);
      el("svg:circle", { cx: X(r.size_rel), cy: Y(r[key]), r: 12, class: "hit" }, g);
      g.addEventListener("pointerenter", (e) => show(r, g, e));
      g.addEventListener("pointermove", (e) => show(r, g, e));
      g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", () => show(r, g));
      g.addEventListener("blur", hide);
    });

    // 状态和脚注
    const st = $("#scatter-status");
    st.className = "status " + w.source;
    st.textContent = w.source === "idle"
      ? L("空闲机器复测（2026-11-26，睿频关闭）", "Re-measured on an idle machine (2026-11-26, turbo off)")
      : L("测量时机器不空闲，待复测", "Measured while the machine was busy; re-measurement pending");
    $("#scatter-n").textContent = L(`${pts.length} 种格式，全部逐位校验通过。基准：FST 默认档 ${bytes(w.fst_default_bytes)}；libfst 取一个时刻 ${secs(w.ref_rtime_s)}、取一个信号 ${secs(w.ref_rsig_s)}。`,
      `${pts.length} formats, all verified bit for bit. Reference: default FST ${bytes(w.fst_default_bytes)}; libfst one-cycle read ${secs(w.ref_rtime_s)}, one-signal read ${secs(w.ref_rsig_s)}.`);
    fullTable();
  }

  function fullTable() {
    const box = $("#fulltable");
    if (!box) return;
    box.hidden = !state.table;
    $("#table-toggle").textContent = state.table ? L("收起表格", "Hide table") : L("以表格查看全部格式", "Show all formats as a table");
    if (!state.table) return;
    box.textContent = "";
    const cols = [
      ["name", L("格式", "Format"), (r) => L(r.zh, r.en), false],
      ["size", L("体积", "Size"), (r) => bytes(r.size), true],
      ["size_rel", L("相对 FST", "vs FST"), (r) => ratio(r.size_rel), true],
      ["rtime_s", L("取一个时刻", "One cycle"), (r) => secs(r.rtime_s), true],
      ["rtime_rel", L("相对 libfst", "vs libfst"), (r) => ratio(r.rtime_rel), true],
      ["rsig_s", L("取一个信号", "One signal"), (r) => secs(r.rsig_s), true],
      ["rsig_rel", L("相对 libfst", "vs libfst"), (r) => ratio(r.rsig_rel), true],
      ["reader", L("读取方式", "Reader"), (r) => r.reader, false],
      ["loadavg", L("负载", "Load"), (r) => sig3(r.loadavg), true],
    ];
    const t = el("table", {}, box), th = el("thead", {}, t), tr = el("tr", {}, th);
    cols.forEach(([k, name, , num]) => {
      const c = el("th", { class: num ? "num" : "", scope: "col" }, tr);
      const b = el("button", { text: name + (state.sort[0] === k ? (state.sort[1] > 0 ? " ↑" : " ↓") : "") }, c);
      b.addEventListener("click", () => { state.sort = [k, state.sort[0] === k ? -state.sort[1] : 1]; fullTable(); });
    });
    const tb = el("tbody", {}, t);
    const rows = rowsOf(state.w).slice();
    const [k, dir] = state.sort;
    rows.sort((a, b) => {
      const va = k === "name" ? L(a.zh, a.en) : a[k], vb = k === "name" ? L(b.zh, b.en) : b[k];
      if (va == null) return 1; if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });
    rows.forEach((r) => {
      const row = el("tr", {}, tb);
      cols.forEach(([key, , f, num], i) => {
        const td = el("td", { class: num ? "num" : "" }, row);
        if (i === 0) { const s = el("span", { class: "sw" }, td); s.style.background = FAM[r.family].color; }
        td.appendChild(document.createTextNode(f(r)));
      });
    });
  }

  function controls() {
    const ws = $("#ctl-wave");
    if (!ws) return;
    const build = () => {
      ws.textContent = "";
      D.waves.forEach((w) => {
        const b = el("button", { type: "button", "aria-pressed": String(w.id === state.w), text: L(w.zh, w.en) }, ws);
        b.addEventListener("click", () => { state.w = w.id; build(); scatter(); });
      });
      const rd = $("#ctl-read");
      rd.textContent = "";
      [["rtime", L("取一个时刻", "One cycle")], ["rsig", L("取一个信号", "One signal")]].forEach(([k, t]) => {
        const b = el("button", { type: "button", "aria-pressed": String(state.read === k), text: t }, rd);
        b.addEventListener("click", () => { state.read = k; build(); scatter(); });
      });
      const ch = $("#ctl-fam");
      ch.textContent = "";
      Object.entries(FAM).forEach(([k, f]) => {
        const lab = el("label", { class: "chip" }, ch);
        const inp = el("input", { type: "checkbox" }, lab);
        inp.checked = state.fams.has(k);
        inp.addEventListener("change", () => { inp.checked ? state.fams.add(k) : state.fams.delete(k); scatter(); });
        lab.appendChild(swatchSvg(f.shape, f.color));
        el("span", { text: L(f.zh, f.en) }, lab);
      });
      const lg = $("#legend");
      lg.textContent = "";
      Object.values(FAM).forEach((f) => { const s = el("span", {}, lg); s.appendChild(swatchSvg(f.shape, f.color)); el("span", { text: L(f.zh, f.en) }, s); });
    };
    build();
    $("#table-toggle").addEventListener("click", () => { state.table = !state.table; fullTable(); });
    rerenders.push(() => { build(); scatter(); });
    let rt;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(scatter, 120); });
    scatter();
  }

  // ---------- 关键数字表 ----------
  function keyTable() {
    const box = $("#keytable");
    if (!box) return;
    box.textContent = "";
    const t = el("table", { class: "keytable" }, box);
    const h = el("tr", {}, el("thead", {}, t));
    [L("波形", "Waveform"), L("FST 默认档", "Default FST"), L("FST 最小档", "Smallest FST"), L("打包 + zstd -19", "Bit-pack + zstd -19"),
      L("Parquet 宽表：体积", "Parquet wide: size"), L("取信号", "one signal"), L("取时刻", "one cycle"),
      L("FFV1 条带：体积", "FFV1 strip: size"), L("取时刻", "one cycle"), L("耗时测量", "Timings")].forEach((x, i) => el("th", { class: i ? "num" : "", text: x, scope: "col" }, h));
    const tb = el("tbody", {}, t);
    D.waves.forEach((w) => {
      const r = el("tr", {}, tb);
      const pq = get(w.id, "parquet-wide-zstd19-rg65536"), fv = get(w.id, "ffv1-strip-8bpp"), bp = get(w.id, "bitpack-sm.zst19"), sm = FST_SMALL(w.id);
      const cells = [L(w.zh, w.en), bytes(w.fst_default_bytes), ratio(sm && sm.size / w.fst_default_bytes), ratio(bp && bp.size_rel),
        ratio(pq && pq.size_rel), ratio(pq && pq.rsig_rel), ratio(pq && pq.rtime_rel), ratio(fv && fv.size_rel), ratio(fv && fv.rtime_rel),
        w.source === "idle" ? L("空闲复测", "idle re-run") : L("不空闲，待复测", "busy, pending")];
      cells.forEach((c, i) => el("td", { class: i ? "num" : "", text: c }, r));
    });
  }

  // ---------- 表的方向（vcd2df 对照） ----------
  function orientation() {
    const box = $("#orient");
    if (!box) return;
    box.textContent = "";
    const color = { ours: "var(--table)", theirs: "var(--video)", base: "var(--axis)", bitpack: "var(--axis)", pkg: "var(--axis)" };
    D.orientation.forEach((o) => {
      const card = el("div", { class: "chartcard" }, box);
      el("h3", { text: L(`${o.design === "picorv32" ? "PicoRV32" : "SERV"}，${o.T.toLocaleString()} 周期`, `${o.design === "picorv32" ? "PicoRV32" : "SERV"}, ${o.T.toLocaleString()} cycles`), style: "font-size:15px;margin:2px 4px 8px" }, card);
      const width = Math.max(300, card.clientWidth - 24), barH = 18, gap = 30, nameH = 15;
      const items = o.items;
      const height = items.length * (barH + gap) + 4;
      const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": L("同一份内容按不同方式存储的体积", "Size of the same content stored different ways") }, el("div", { class: "chart" }, card));
      const mx = Math.max(...items.map((x) => x.size));
      const sc = (v) => v / mx * (width - 80);
      items.forEach((it, i) => {
        const y = i * (barH + gap) + nameH + 4;
        el("svg:text", { x: 0, y: y - 5, class: "dlabel", text: L(it.zh, it.en) }, svg);
        const w = Math.max(2, sc(it.size));
        el("svg:path", { d: `M0,${y}H${w - 4}a4,4 0 0 1 4,4V${y + barH - 4}a4,4 0 0 1 -4,4H0Z`, fill: color[it.kind] }, svg);
        el("svg:text", { x: w + 6, y: y + barH - 5, class: "tick", text: bytes(it.size), style: "fill:var(--ink-2);font-size:12px" }, svg);
      });
      if (o.pkg_kept) el("p", { class: "caption", text: L(`vcd2df 原包按模块内的短名字去重，VCD 里 ${o.pkg_kept[0]} 个变量只保留了 ${o.pkg_kept[1]} 个，所以它的输出不是无损的，只作参考。`, `The vcd2df package de-duplicates by short name within a module and keeps ${o.pkg_kept[1]} of the ${o.pkg_kept[0]} variables in the VCD, so its output is lossy and shown for reference only.`) }, card);
      if (o.pkg_failed) el("p", { class: "caption", text: L("vcd2df 原包在这个波形上运行失败（超过 63 位的值溢出），所以没有它的那一条。", "The vcd2df package failed on this waveform (values wider than 63 bits overflow), so its bar is missing.") }, card);
      el("p", { class: "caption", text: L("数据：", "Data: ") + o.csv }, card);
    });
    const ratios = D.orientation.map((o) => {
      const a = o.items.find((x) => x.kind === "ours"), b = o.items.find((x) => x.kind === "theirs");
      return b.size / a.size;
    });
    setAll(".orient-ratio", range(ratios, (x) => x.toFixed(1)));
  }

  // ---------- 方法页：测量条件 ----------
  function method() {
    const box = $("#waves-meta");
    if (box) {
      box.textContent = "";
      const t = el("table", {}, box), h = el("tr", {}, el("thead", {}, t));
      [L("波形", "Waveform"), L("周期数", "Cycles"), L("比特数", "Bits"), L("格式数", "Formats"), L("耗时来源", "Timing source"), L("测量时负载", "Load during run"), L("原始数据", "Raw data")].forEach((x, i) => el("th", { text: x, class: i && i < 4 ? "num" : "" }, h));
      const tb = el("tbody", {}, t);
      D.waves.forEach((w) => {
        const r = el("tr", {}, tb);
        [L(w.zh, w.en), w.T.toLocaleString(), w.B.toLocaleString(), String(rowsOf(w.id).length),
          w.source === "idle" ? L("空闲复测", "idle re-run") : L("机器不空闲，待复测", "busy machine, pending"),
          `${sig3(w.loadavg_min)}–${sig3(w.loadavg_max)}`, w.csv].forEach((c, i) => el("td", { text: c, class: i && i < 4 ? "num" : "" }, r));
      });
    }
    const pre = $("#conditions");
    if (pre) pre.textContent = D.idle_conditions || L("（空闲复测还没有结果）", "(no idle re-measurement results yet)");
    const nIdle = D.waves.filter((w) => w.source === "idle").length;
    setAll(".idle-count", `${nIdle} / ${D.waves.length}`);
    const pq = ALL.map((w) => get(w, "parquet-wide-zstd19-rg65536")).filter(Boolean);
    setAll(".pq-speed", range(pq.map((r) => 1 / r.rtime_rel), (x) => x.toFixed(0)) + "×");
    const pv = $("#provisional");
    if (pv) {
      const busy = D.waves.filter((w) => w.source !== "idle");
      pv.hidden = busy.length === 0;
      pv.textContent = `Timings are provisional for ${busy.map((w) => w.en).join("; ")}: they still come from the runs on a busy machine. The idle re-measurement for these waveforms has not finished yet; the site will be updated when it has. Sizes are not affected.`;
    }
  }

  hero(); findings(); controls(); keyTable(); orientation(); method();
  rerenders.push(findings, keyTable, orientation, method);
  let ro;
  window.addEventListener("resize", () => { clearTimeout(ro); ro = setTimeout(orientation, 150); });
})();
