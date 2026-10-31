# GTA IV CPU settings: complete 62-item tested baseline

Date: 2026-10-30. Source: valid patch0062 GTA IV NPUB30702 runtime capture,
`results/gta4-spu-coverage-20261030/B-spu-cover0062-run2.log`.
These reproduce a tested baseline; they are not proof of globally optimal settings.

The UI's "62 settings" is the item count, not the executable patch number.
Core has63 runtime keys, but the frontend omits Libraries Control (cfg set),
leaving62 visible CPU settings in this order. Screenshot scope "For all games"
is global; use GTA IV's per-game settings for this baseline. The screenshot's
global scheduler is Operating System, while measured GTA IV runtime is RPCS3
Scheduler; per-game overrides can explain the difference. No settings changed
as part of this documentation.

| # | Setting | Tested value |
| --- | --- | --- |
| 1 | PPU Decoder | Recompiler (LLVM) |
| 2 | PPU Threads | 2 |
| 3 | PPU Debug | Off |
| 4 | PPU Calling History | Off |
| 5 | Save LLVM logs | Off |
| 6 | Use LLVM CPU | Leave blank |
| 7 | Max LLVM Compile Threads | 10 (fixed on PS5) |
| 8 | LLVM Precompilation | On |
| 9 | Thread Scheduler Mode | RPCS3 Scheduler |
| 10 | Set DAZ and FTZ | Off |
| 11 | SPU Decoder | Recompiler (LLVM) |
| 12 | SPU Reservation Busy Waiting Percentage 1 | 100 |
| 13 | SPU Reservation Busy Waiting Enabled | Off |
| 14 | SPU GETLLAR Busy Waiting Percentage | 100 |
| 15 | Disable SPU GETLLAR Spin Optimization | Off |
| 16 | SPU Debug | Off |
| 17 | MFC Debug | Off |
| 18 | Preferred SPU Threads | 0 (Auto) |
| 19 | SPU delay penalty | 3 |
| 20 | SPU loop detection | Off |
| 21 | Max SPURS Threads | 6 |
| 22 | SPU Block Size | Mega |
| 23 | Accurate SPU DMA | Off |
| 24 | Accurate SPU Reservations | On |
| 25 | SPU MMIO Delay Enabled | Off |
| 26 | SPU MMIO Delay | 100 |
| 27 | Accurate Cache Line Stores | Off |
| 28 | Accurate RSX reservation access | Off |
| 29 | PPU Reservation Priority Over SPUs | Off |
| 30 | RSX FIFO Fetch Accuracy | Atomic |
| 31 | SPU Verification | On |
| 32 | SPU Cache | On |
| 33 | SPU Profiler | Off |
| 34 | PPU Profiler | Off |
| 35 | MFC Commands Shuffling Limit | 0 |
| 36 | MFC Shuffle Instructions Decrementer | 30 |
| 37 | MFC Commands Shuffling In Steps | Off |
| 38 | SPU XFloat Accuracy | Approximate |
| 39 | Accurate PPU 128-byte Reservation Op Max Length | 0 |
| 40 | Stub PPU Traps | 0 |
| 41 | Precise SPU Verification | Off |
| 42 | PPU Vector NaN Handling | On |
| 43 | Use Accurate DFMA | On |
| 44 | PPU Set Saturation Bit | Off |
| 45 | PPU Accurate Non-Java Mode | Off |
| 46 | PPU Accurate Vector NaN Values | Off |
| 47 | PPU Set FPCC Bits | Off |
| 48 | PPU Accurate Vector Estimates | Off |
| 49 | Debug Console Mode | Off |
| 50 | Hook static functions | Off |
| 51 | HLE lwmutex | Off |
| 52 | Clocks scale | 100 |
| 53 | SPU Wake-Up Delay | 0 |
| 54 | SPU Wake-Up Delay Thread Mask | 63 |
| 55 | Max CPU Preempt Count | 0 |
| 56 | PPU Event Wake-Up Delay | 0 |
| 57 | Allow RSX CPU Preemptions | On |
| 58 | Sleep Timers Accuracy | Usleep Only |
| 59 | Usleep Time Addend | 0 |
| 60 | Performance Report Threshold | 500 |
| 61 | Enable Performance Report | Off |
| 62 | Assume External Debugger | Off |
