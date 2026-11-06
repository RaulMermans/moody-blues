# Timeline performance

Sprint 12 raised the Timeline's HTML from 317 KB to 712 KB, because folded records stay in the page. Sprint 13 measured
what that costs before changing anything. **Result: no code change.** The reasons are below.

## Method

Production build, local backend, the real `inv_d0bc87de6010` bundle (127 records, 23 milestones, 103 folded in the
default view). Playwright Chromium. 20 loads per figure after one warm-up, median. "Phone" is a 390 px viewport with 4×
CPU throttling through CDP. These are local numbers. They do not predict hosted latency, and a CPU throttle is not a phone.

An earlier pass ran while the backend suite was using the machine. It showed the long task falling from 143 ms to 96 ms.
That was noise, and it is not used here. Every figure below comes from an interleaved run on a quiet machine.

## Measured

| | Value |
|---|---|
| HTML, raw | 712,333 B: 271,502 B markup, 440,831 B inline React payload |
| HTML, gzip | 39,018 B. Production compresses it: `content-encoding: gzip` read from the live site |
| Elements after load | 4,051 |
| DOM nodes, CDP | 8,213 |
| JS heap | 5.7 MB |
| LCP, desktop / phone | 380 ms / 460 ms, the same range as the Investigator (380 / 488) |
| Opening a row, desktop / phone | 8 ms / 20 ms |
| Long tasks, desktop / phone | 0 ms / about 154 ms |
| Scroll | Not measured as a frame rate. No scroll handlers or sticky work run per row |
| Real phone | NOT_RUN |

## What was tried

| Variant | HTML | gzip | Phone long task | Phone task time | Decision |
|---|---|---|---|---|---|
| Current (`next/link` in every record) | 712,290 B | 39,121 B | 153–155 ms | 448–454 ms | **Kept** |
| Plain `<a>` in folded records | 711,947 B | 39,080 B | 152–154 ms | 435 ms | Rejected: about 3% less work, and client navigation lost |
| Best case for lazy mounting: folded records deleted | 209,660 B | 21,725 B | 158 ms | 358 ms | Not built |

The third row is an upper bound, not an implementation. No lazy design can beat a page that has no folded records at all.

## Why lazy mounting was not built

- **It does not touch the long task.** With every folded record gone it stays at about 155 ms, so the cost is JavaScript
  start-up, not records.
- **It saves 17 KB on the wire** and about 20% of CPU on a throttled load.
- **It costs a new public route and a client renderer.** Moving `journey.ts` and its labels to the browser adds JavaScript,
  and a folded record would stop working without it. Today every record is in the page, so find-in-page and no-JS reading work.

## When to revisit

Fetch folded records on demand if a bundle holds several times more records. On this case each folded record
costs about 4.9 KB raw and 170 B gzipped. Measure the new bundle first rather than rely on that figure.
