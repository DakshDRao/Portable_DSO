# 📟 Portable Digital Storage Oscilloscope (DSO)
### Raspberry Pi Pico · MicroPython · SSD1306 OLED · LTSpice Front-End · Wokwi Simulation

---

## Overview

A portable, low-cost Digital Storage Oscilloscope built around the **Raspberry Pi Pico (RP2040)** microcontroller. The system captures an analogue input signal through a custom front-end conditioning circuit, digitises it via the Pico's onboard ADC, and renders the waveform in real time on a **128×64 SSD1306 OLED display**.

The project is developed in two parallel stages:

- **Analogue front-end** — designed and simulated in **LTSpice**. Handles input protection, DC biasing to Vref/2 (1.65 V), and anti-aliasing filtering before the ADC pin.
- **Digital firmware** — written in **MicroPython**. Handles ADC capture, edge triggering, timebase control, and OLED rendering.

A Python converter script bridges the two stages, allowing LTSpice simulation output (CSV) to be replayed directly inside a **Wokwi** browser simulation — validating the complete firmware pipeline before committing to hardware.

---

## Table of Contents

- [Features](#features)
- [System Architecture](#system-architecture)
- [Repository Structure](#repository-structure)
- [Front-End Circuit](#front-end-circuit)
- [Simulation Pipeline](#simulation-pipeline)
- [Wokwi Simulation Setup](#wokwi-simulation-setup)
- [Supported Waveforms](#supported-waveforms)
- [Button Reference](#button-reference)
- [Display Layout](#display-layout)
- [Switching to Real Hardware](#switching-to-real-hardware)
- [Dependencies](#dependencies)

---

## Features

- Real-time waveform display on 128×64 OLED (SSD1306 via I2C)
- Adjustable timebase — 12 steps from 1 µs/div to 5 ms/div
- Adjustable trigger level — 16 steps across the full ADC range
- Rising / falling edge trigger selection
- Trigger timeout detection with status indicator
- Single-flag switch between simulation mode and live ADC mode
- LTSpice CSV → MicroPython array converter with:
  - Automatic settling-time skip (`--skip-ms`)
  - Uniform resampling from LTSpice's adaptive timesteps
  - Clip detection to validate front-end bias
  - Signal statistics and frequency estimation

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        PC  (LTSpice)                            │
│                                                                 │
│   V1 (signal source)  →  Front-End Circuit  →  V(adc_out)      │
│      SINE / PULSE             R1, C1                            │
│      SAWTOOTH                 R3-R5, C2-C3   (bias + filter)   │
│      TRIANGLE                 U1, D1, D2     (buffer + clamp)  │
│                                    │                            │
│                              .tran 1u 25m                       │
│                              File → Export as CSV               │
└────────────────────────────────────┬────────────────────────────┘
                                     │  output.csv
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              ltspice_csv_to_samples.py  (PC, Python 3)          │
│                                                                 │
│   1. Parse CSV  (tab-separated, sci-notation, header skip)      │
│   2. Trim settling time  (--skip-ms 12)                         │
│   3. Resample uniformly  (linear interpolation)                 │
│   4. Quantise to uint16  (0 = 0 V, 65535 = 3.3 V)              │
└────────────────────────────────────┬────────────────────────────┘
                                     │  samples.py
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Wokwi Simulation                             │
│                                                                 │
│   diagram.json  →  Pico + SSD1306 + 4 buttons                  │
│   main.py       →  DSO firmware  (SIMULATION_MODE = True)       │
│   samples.py    →  ADC replay buffer                            │
│   ssd1306.py    →  OLED driver                                  │
│                          │                                      │
│              ┌───────────┴────────────┐                         │
│              ▼                        ▼                         │
│         read_adc()             capture_waveform()               │
│     (returns next sample       (trigger hunt →                  │
│      from SAMPLES array)        fill capture_buf[])             │
│              │                        │                         │
│              └───────────┬────────────┘                         │
│                          ▼                                      │
│                    render_frame()                               │
│               (grid + trigger line +                            │
│                waveform + labels → OLED)                        │
└─────────────────────────────────────────────────────────────────┘
                                     │
                    SIMULATION_MODE = False
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Real Hardware                                 │
│                                                                 │
│   Front-end output  →  GP26 (ADC0)  →  machine.ADC.read_u16()  │
│   SSD1306  →  GP4 (SDA) / GP5 (SCL)                            │
│   Buttons  →  GP12 / GP13 / GP14 / GP15                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
portable-dso/
│
├── firmware/
│   ├── main.py                   # DSO firmware (MicroPython)
│   └── ssd1306.py                # SSD1306 OLED driver
│
├── simulation/
│   ├── ltspice/
│   │   └── frontend.asc          # LTSpice front-end schematic
│   ├── ltspice_csv_to_samples.py # CSV → samples.py converter
│   └── output.csv                # Example LTSpice export (sine, 18 kHz)
│
├── wokwi/
│   ├── diagram.json              # Wokwi circuit definition
│   ├── wokwi.toml                # Wokwi project config
│   └── samples.py                # Generated sample array (copy here)
│
└── README.md
```

---

## Front-End Circuit

The analogue front-end conditions the raw input signal before it reaches the Pico ADC pin (GP26). It is designed for a ±1 V input signal at up to 18 kHz.

| Stage | Components | Purpose |
|---|---|---|
| Input resistor | R1 (10 kΩ) | Current limiting and forms high-pass filter with C1 |
| AC coupling | C1 (100 nF) | Blocks DC from the input source; HPF corner ≈ 159 Hz |
| Bias network | V2 (3.3 V), R4 (10 kΩ), R5 (10 kΩ), C2 (1 µF), C3 (100 µF) | Sets DC midpoint at Vref/2 = 1.65 V |
| Buffer | U1 (op-amp, powered by V3 = 3.3 V) | Unity-gain buffer; drives output with low impedance |
| Output resistor | R2 (470 Ω) | Series protection resistor at ADC input |
| Clamp diodes | D1, D2 (with V3 = 3.3 V, V4 = 3.3 V) | Hard-clamp output to [0 V, 3.3 V]; protects ADC |
| Bias resistor | R3 (220 kΩ) | High-impedance bias path to vbias node |

**Simulation parameters (V1):**

```
.op
.tran 1u 25m
.ac dec 100 1 100Meg
```

---

## Simulation Pipeline

### Step 1 — Run LTSpice

Set up V1 for your desired waveform (see [Supported Waveforms](#supported-waveforms)), run the transient simulation, then export:

```
File → Export data as text → save as output.csv
```

The `.tran` stop time must be large enough to cover the settling period plus the capture window:

```
stop_time ≥ settling_ms + (samples / rate_hz × 1000) ms
```

For the default settings (12 ms settle, 1024 samples, 500 kSa/s):
```
stop_time ≥ 12 + 2.048 = 14.05 ms   →   use 25m to be safe
```

### Step 2 — Convert CSV to samples.py

```bash
python ltspice_csv_to_samples.py output.csv --skip-ms 12 --rate 500000 --samples 1024
```

**All options:**

| Flag | Default | Description |
|---|---|---|
| `--skip-ms` | 0 | Discard the first N ms (front-end settling time) |
| `--rate` | 500000 | Output sample rate in Hz |
| `--samples` | 1024 | Maximum number of output samples |
| `--vref` | 3.3 | Pico ADC reference voltage |
| `--out` | samples.py | Output filename |
| `--channel` | 1 | 1-based column index for voltage in CSV |
| `--clip-warn` | off | Warn instead of aborting on clipped samples |

The script prints a full diagnostic summary:

```
──────────────────────────────────────────────────────────────
  LTSpice CSV  →  MicroPython samples  (pre-biased, settled)
──────────────────────────────────────────────────────────────
  [info] .tran stop time must be ≥ 14.05 ms in LTSpice

  Parsed   : 1072 data points
  Time     : 0.0000 ms  →  25.0000 ms

  Skipping : first 12.0 ms  (N points discarded)
  Remaining: M points  (13.000 ms of settled signal)

  ┌─ Settled signal statistics ─────────────────────────────
  │  Capture starts at   : 12.0 ms
  │  Vmin                : 0.6523 V
  │  Vmax                : 2.6437 V
  │  Vpp                 : 1.9914 V  (60.3% of Vref)
  │  Vmean               : 1.6480 V  (ideal = 1.6500 V)
  │  Bias error          : +0.0020 V  ✓ OK
  │  Est. frequency      : 18000.00 Hz
  │  Output samples      : 1024  @  500000 Hz
  │  Capture window      : 2.048 ms
  └─────────────────────────────────────────────────────────
  Clipping : 0 samples  ✓

  Written  → samples.py  (1024 samples, 7.8 KB)
```

---

## Wokwi Simulation Setup

1. Go to [wokwi.com](https://wokwi.com) → **New Project** → **Raspberry Pi Pico** → **MicroPython**

2. In the file sidebar, replace the default files and add new ones:

| File | Action |
|---|---|
| `diagram.json` | Replace with contents of `wokwi/diagram.json` |
| `main.py` | Replace with contents of `firmware/main.py` |
| `samples.py` | Add new file — paste generated `samples.py` |
| `ssd1306.py` | Add new file — paste from [stlehmann/micropython-ssd1306](https://raw.githubusercontent.com/stlehmann/micropython-ssd1306/master/ssd1306.py) |

3. Click **▶ Start Simulation**

The OLED shows a splash screen for 1 second, then begins rendering the waveform from the samples array.

**Pin assignments:**

| Pico Pin | Connected To | Signal |
|---|---|---|
| GP4 | SSD1306 SDA | I2C Data |
| GP5 | SSD1306 SCL | I2C Clock |
| GP12 | EDGE button | Edge toggle (active low) |
| GP13 | TRIG button | Trigger level (active low) |
| GP14 | TB− button | Timebase faster (active low) |
| GP15 | TB+ button | Timebase slower (active low) |
| GP26 | Front-end output | ADC input (real hardware only) |
| 3V3 | SSD1306 VCC | Power |
| GND | SSD1306 GND, button grounds | Ground |

---

## Supported Waveforms

All waveforms use a ±1 V amplitude, centred at 0 V. The front-end bias shifts them to 0.65 V – 2.64 V at the ADC pin.

### Sine — 18 kHz
```
SINE(0 1 18K)
```

### Square — 18 kHz
```
PULSE(-1 1 0 1n 1n 27.78u 55.56u)
```

### Sawtooth — 18 kHz
```
PULSE(-1 1 0 54.56u 1n 1n 55.56u)
```

### Triangle — 18 kHz
```
PULSE(-1 1 0 27.78u 27.78u 1n 55.56u)
```

**Samples per cycle at 500 kSa/s:**

| Frequency | Samples/cycle | Notes |
|---|---|---|
| 500 Hz | 1000 | Excellent resolution |
| 3 kHz | ~167 | Good |
| 18 kHz | ~27 | Acceptable; increase rate to 1 MSa/s for sharper edges |

To change frequency, scale `Trise`, `Tfall`, `Ton`, and `Tperiod` proportionally. Period = 1 / frequency.

---

## Button Reference

All buttons are active-low with internal pull-ups enabled in firmware. Press events are detected on the falling edge — holding a button does not repeat.

| Button | GPIO | Colour | Action |
|---|---|---|---|
| **TB+** | GP15 | Green | Timebase slower — increases µs/div, widens the time window |
| **TB−** | GP14 | Green | Timebase faster — decreases µs/div, narrows the time window |
| **TRIG** | GP13 | Yellow | Trigger level up — cycles through 16 voltage steps (~0.206 V each) |
| **EDGE** | GP12 | Red | Toggle rising ↗ / falling ↘ edge trigger |

**Timebase steps (µs/div):**
```
1 → 2 → 5 → 10 → 20 → 50 → 100 → 200 → 500 → 1000 → 2000 → 5000
```
Total window = µs/div × 10 divisions.

---

## Display Layout

```
┌──────┬──────────────────────────────────────────────────────────┐
│ 20us │  · · · · · · · · · ·                                     │
│      │         /\          /\                                    │
│ 1.6V │ -------/--\--------/--\----  ← trigger line (dashed)    │
│      │       /    \      /    \                                  │
│  R   │  ____/      \____/      \__                              │
│      │  · · · · · · · · · ·                                     │
├──────┴──────────────────────────────────────────────────────────┤
│ TRG SIM                                                         │
└─────────────────────────────────────────────────────────────────┘
  ↑ label column (22 px)     ↑ waveform canvas (106 × 54 px)
```

| Region | Content |
|---|---|
| Top-left | Current timebase (e.g. `20us`) |
| Mid-left | Trigger level in volts (e.g. `1.6V`) |
| Lower-left | Edge polarity — `R` (rising) or `F` (falling) |
| Dashed line | Trigger threshold across waveform canvas |
| Bottom bar | `TRG` / `---` (triggered / timed out) + `SIM` / `ADC` (mode) |

---

## Switching to Real Hardware

Change exactly one line in `main.py`:

```python
SIMULATION_MODE = False   # was True
```

The `read_adc()` function switches from the samples array to `machine.ADC(26).read_u16()`. All trigger, timebase, and display logic is identical.

Physical connections required:

- Front-end `ADC_out` → **GP26**
- SSD1306 SDA → **GP4**, SCL → **GP5**, VCC → **3V3**, GND → **GND**
- Each button: one leg to its GPIO pin, other leg to **GND** (no external resistors needed)

---

## Dependencies

| Dependency | Version | Purpose |
|---|---|---|
| MicroPython | v1.24.1+ | Pico firmware runtime |
| ssd1306.py | — | OLED driver ([source](https://github.com/stlehmann/micropython-ssd1306)) |
| Python 3 | 3.8+ | Running `ltspice_csv_to_samples.py` on PC |
| LTSpice | XVII+ | Front-end circuit simulation |
| Wokwi | — | Browser-based Pico simulation |

No third-party Python packages are required — the converter uses only the standard library (`csv`, `argparse`, `os`, `sys`).

---

## License

MIT License — see `LICENSE` for details.
