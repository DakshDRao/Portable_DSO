# main.py  –  Portable DSO Firmware  (Raspberry Pi Pico / MicroPython)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Wokwi simulation layout:
#
#  ┌─ SSD1306 128×64 OLED ─────────────────────────────────┐
#  │ TB   │                                                 │
#  │ 20us │  . . . . . . . . . . .                          │
#  │      │                     /\                          │
#  │ T    │  ___/\___/\___/\___/  \___/\___                 │
#  │ 1.6V │                                                 │
#  │  /   │  · · · · · · · · · · · · · ·                   │
#  │      │                                                 │
#  │ TRG  └─────────────────────────────────────────────────┤
#  └────────────────────────────────────────────────────────┘
#
#  Pins:
#    GP4  / GP5   →  I2C SDA / SCL  (SSD1306)
#    GP26          →  ADC0  (analog input — bypassed in SIMULATION_MODE)
#    GP15          →  BTN_TB_UP    (timebase slower)
#    GP14          →  BTN_TB_DN    (timebase faster)
#    GP13          →  BTN_TRIG_UP  (trigger level up)
#    GP12          →  BTN_EDGE     (toggle rising/falling edge)
#
#  Toggle SIMULATION_MODE below to switch between live ADC and CSV replay.
# ─────────────────────────────────────────────────────────────────────────────

import machine
import utime
from machine import I2C, Pin
import ssd1306

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION  –  edit these to match your hardware
# ══════════════════════════════════════════════════════════════════════════════

SIMULATION_MODE = True   # True  = replay samples.py array
                          # False = read live ADC on GP26

RUN_MODE = True   # True = running, False = stopped

VREF          = 3.3      # ADC reference voltage  (V)
ADC_BITS      = 16       # read_u16() returns 0–65535
ADC_MAX       = (1 << ADC_BITS) - 1   # 65535

# Display
SCREEN_W  = 128
SCREEN_H  = 64

# Waveform canvas (leaves left column for labels)
WAVE_X0   = 22    # left edge of waveform area (pixels)
WAVE_Y0   = 0     # top  edge
WAVE_W    = SCREEN_W - WAVE_X0   # 106 pixels  = 10 divisions
WAVE_H    = SCREEN_H - 10        # 54  pixels  = 4 divisions
WAVE_DIVS_X = 10
WAVE_DIVS_Y = 4

N_SAMPLES = WAVE_W    # one sample per pixel column

# Timebase: µs per division (10 divisions across WAVE_W)
# Actual sample interval = timebase_us × WAVE_DIVS_X / N_SAMPLES
TIMEBASES_US = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
tb_idx       = 4   # default index (20 µs/div)

# Trigger level: steps across full ADC range
TRIG_STEPS = 16
trig_idx   = TRIG_STEPS // 2    # mid-scale (≈ 1.65 V)
trig_rising = True               # True = rising edge, False = falling

TRIG_TIMEOUT_ITERS = 100_000     # give up hunting trigger after N ADC reads

effective_step = 1.0
# ══════════════════════════════════════════════════════════════════════════════
#  ADC LAYER  –  real hardware  or  CSV simulation
# ══════════════════════════════════════════════════════════════════════════════

if SIMULATION_MODE:
    # ── Import the array produced by ltspice_csv_to_samples.py ───────────────
    try:
        from samples import SAMPLES, SAMPLE_RATE_HZ, N_SAMPLES as SIM_N
    except ImportError:
        # Fallback: synthesise a simple 1 kHz sine so the UI still works
        import math
        _SR     = 500_000
        _F0     = 1_000
        _N      = 1024
        SAMPLE_RATE_HZ = _SR
        SIM_N          = _N
        SAMPLES = [
            int(32767 + 30000 * math.sin(2 * math.pi * _F0 * i / _SR))
            for i in range(_N)
        ]
        print("[warn] samples.py not found – using built-in 1 kHz sine wave")

    _sim_idx = 0

    def read_adc():
        """Return next sample from the pre-loaded CSV replay buffer."""
        global _sim_idx
        val = SAMPLES[_sim_idx % len(SAMPLES)]
        _sim_idx += 1
        return val

    def adc_sample_rate():
        return SAMPLE_RATE_HZ

else:
    # ── Live ADC on GP26 ──────────────────────────────────────────────────────
    _adc = machine.ADC(26)

    def read_adc():
        return _adc.read_u16()

    def adc_sample_rate():
        # Pico ADC max safe rate in MicroPython ≈ 500 kSa/s
        return 500_000

# ══════════════════════════════════════════════════════════════════════════════
#  DISPLAY SETUP
# ══════════════════════════════════════════════════════════════════════════════

i2c     = I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)
display = ssd1306.SSD1306_I2C(SCREEN_W, SCREEN_H, i2c)

# ══════════════════════════════════════════════════════════════════════════════
#  BUTTONS  (active-low, internal pull-up)
# ══════════════════════════════════════════════════════════════════════════════

BTN_TB_UP   = Pin(15, Pin.IN, Pin.PULL_UP)  # timebase slower  (longer window)
BTN_TB_DN   = Pin(14, Pin.IN, Pin.PULL_UP)  # timebase faster  (shorter window)
BTN_TRIG_UP = Pin(13, Pin.IN, Pin.PULL_UP)  # trigger level up
BTN_EDGE    = Pin(12, Pin.IN, Pin.PULL_UP)  # toggle edge polarity
BTN_RUN_STOP = Pin(11, Pin.IN, Pin.PULL_UP)  # NEW: run/stop toggle
BTN_AUTO = Pin(10, Pin.IN, Pin.PULL_UP)

# Store last button states for edge detection (no debounce timer needed in sim)
# _btn_prev = [True, True, True, True]
_btn_prev = [True, True, True, True, True, True]

# def poll_buttons():
#     """
#     Returns a tuple of booleans (tb_up, tb_dn, trig_up, edge)
#     – each True for exactly the one frame the button was pressed.
#     """
#     global _btn_prev, tb_idx, trig_idx, trig_rising
#     curr = [BTN_TB_UP.value(), BTN_TB_DN.value(),
#             BTN_TRIG_UP.value(), BTN_EDGE.value()]

#     pressed = [not curr[i] and _btn_prev[i] for i in range(4)]
#     _btn_prev = curr

#     if pressed[0]:   # TB slower
#         tb_idx = min(tb_idx + 1, len(TIMEBASES_US) - 1)
#     if pressed[1]:   # TB faster
#         tb_idx = max(tb_idx - 1, 0)
#     if pressed[2]:   # trigger level up
#         trig_idx = (trig_idx + 1) % (TRIG_STEPS + 1)
#     if pressed[3]:   # edge toggle
#         trig_rising = not trig_rising

#     return pressed

def poll_buttons():
    global _btn_prev, tb_idx, trig_idx, trig_rising, RUN_MODE

    curr = [
        BTN_TB_UP.value(),
        BTN_TB_DN.value(),
        BTN_TRIG_UP.value(),
        BTN_EDGE.value(),
        BTN_RUN_STOP.value(),
        BTN_AUTO.value()
    ]

    # ✅ correct length = 6
    pressed = [not curr[i] and _btn_prev[i] for i in range(6)]
    _btn_prev = curr

    if pressed[0]:
        tb_idx = min(tb_idx + 1, len(TIMEBASES_US) - 1)
    if pressed[1]:
        tb_idx = max(tb_idx - 1, 0)
    if pressed[2]:
        trig_idx = (trig_idx + 1) % (TRIG_STEPS + 1)
    if pressed[3]:
        trig_rising = not trig_rising
    if pressed[4]:
        RUN_MODE = not RUN_MODE
    if pressed[5]:
        auto_setup()

    return pressed

# ══════════════════════════════════════════════════════════════════════════════
#  CAPTURE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

capture_buf = [0] * N_SAMPLES    # circular waveform buffer
last_vpp = 0.0
last_freq = 0.0

def trig_level_adc():
    """Current trigger threshold as a 16-bit ADC value."""
    return int(trig_idx / TRIG_STEPS * ADC_MAX)


def compute_inter_sample_delay_us():
    """
    Delay between ADC reads (µs) so that the captured window matches
    the selected timebase.

    window_duration = TIMEBASES_US[tb_idx] × WAVE_DIVS_X  (µs)
    inter_sample_us = window_duration / N_SAMPLES
    Subtract ~2 µs for Python overhead.
    """
    window_us       = TIMEBASES_US[tb_idx] * WAVE_DIVS_X
    ideal_us        = window_us / N_SAMPLES
    overhead_us     = 2.0   # empirical MicroPython read_adc overhead
    delay_us        = max(0, ideal_us - overhead_us)

    # In simulation mode ignore delay (array is already correctly sampled)
    if SIMULATION_MODE:
    # simulate timebase effect by skipping samples
        window_us = TIMEBASES_US[tb_idx] * WAVE_DIVS_X
        sample_rate = adc_sample_rate()
        samples_per_window = sample_rate * (window_us / 1_000_000)

        step = samples_per_window / N_SAMPLES   # float (IMPORTANT)
        return step   # 👈 return "step" instead of delay

    return int(delay_us)

def capture_waveform():
    """
    Trigger + capture with proper timebase behavior
    """

    level = trig_level_adc()
    triggered = False

    # ── Determine sampling behavior ──────────────────────
    if SIMULATION_MODE:
        window_us = TIMEBASES_US[tb_idx] * WAVE_DIVS_X
        base_sample_rate = adc_sample_rate()

        samples_per_window = base_sample_rate * (window_us / 1_000_000)

        # 🔥 FLOAT step (fix dead zone)
        step = samples_per_window / N_SAMPLES

        delay_us = 0

    else:
        step = 1.0
        delay_us = compute_inter_sample_delay_us()

    # ── Trigger hunt ─────────────────────────────────────
    prev = read_adc()

    for _ in range(TRIG_TIMEOUT_ITERS):
        curr = read_adc()

        poll_buttons()

        if trig_rising and prev < level <= curr:
            triggered = True
            break

        if not trig_rising and prev > level >= curr:
            triggered = True
            break

        prev = curr

    # ── Sample acquisition ───────────────────────────────
    acc = 0.0   # 🔥 fractional accumulator

    for i in range(N_SAMPLES):

        capture_buf[i] = read_adc()

        if SIMULATION_MODE:
            acc += step
            skip = int(acc)

            for _ in range(skip):
                read_adc()

            acc -= skip

        poll_buttons()

        if not SIMULATION_MODE and delay_us:
            utime.sleep_us(delay_us)

    # 🔥 Store effective step globally for frequency calc
    global effective_step
    effective_step = step
    # Calculate exactly how many seconds pass between each point in capture_buf
    global seconds_per_sample
    if SIMULATION_MODE:
        # In sim, we skip 'step' samples of the original CSV rate
        seconds_per_sample = step / adc_sample_rate()
    else:
        # In live mode, it's (delay + overhead)
        seconds_per_sample = (delay_us + 2.0) / 1_000_000

    return triggered

def measure_signal():
    """
    Calculates frequency based on the UI Timebase (the 'Master Clock').
    """
    if len(capture_buf) < 10: 
        return 0.0, 0.0

    # 1. Voltage Peak-to-Peak (stays the same)
    v_max = max(capture_buf)
    v_min = min(capture_buf)
    vpp = ((v_max - v_min) / ADC_MAX) * VREF

    return vpp

# ══════════════════════════════════════════════════════════════════════════════
#  DISPLAY RENDERING
# ══════════════════════════════════════════════════════════════════════════════

def adc_to_y(adc_val):
    """Map a 16-bit ADC value to a pixel Y coordinate within the waveform area."""
    y = WAVE_Y0 + WAVE_H - int(adc_val / ADC_MAX * WAVE_H)
    return max(WAVE_Y0, min(WAVE_Y0 + WAVE_H - 1, y))


def fmt_timebase(us):
    if us < 1000:
        return f"{us}us"
    ms = us // 1000
    return f"{ms}ms"


def fmt_voltage(adc_val):
    v = adc_val / ADC_MAX * VREF
    return f"{v:.2f}V"


def draw_grid():
    """Dot-grid: 10 columns × 4 rows."""
    x_step = WAVE_W // WAVE_DIVS_X
    y_step = WAVE_H // WAVE_DIVS_Y
    for col in range(WAVE_DIVS_X + 1):
        for row in range(WAVE_DIVS_Y + 1):
            x = WAVE_X0 + col * x_step
            y = WAVE_Y0 + row * y_step
            if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
                display.pixel(x, y, 1)


def draw_trigger_line():
    """Dashed horizontal line at trigger level."""
    ty = adc_to_y(trig_level_adc())
    for x in range(WAVE_X0, WAVE_X0 + WAVE_W, 3):
        display.pixel(x, ty, 1)


def draw_waveform():
    """Draw the captured waveform as connected line segments."""
    for i in range(1, N_SAMPLES):
        x0 = WAVE_X0 + i - 1
        x1 = WAVE_X0 + i
        y0 = adc_to_y(capture_buf[i - 1])
        y1 = adc_to_y(capture_buf[i])
        display.line(x0, y0, x1, y1, 1)


def draw_labels(triggered):
    """Left-column labels + bottom status bar."""
    # Timebase
    tb_str = fmt_timebase(TIMEBASES_US[tb_idx])
    display.text(tb_str[:4], 0, 0, 1)

    # Trigger level
    trig_str = fmt_voltage(trig_level_adc())
    display.text(trig_str[:4], 0, 10, 1)

    # Edge symbol
    edge_ch = "R" if trig_rising else "F"
    display.text(edge_ch, 0, 20, 1)

    # Status bar (bottom row)
    status = "TRG " if triggered else "--- "
    # mode   = "SIM" if SIMULATION_MODE else "ADC"
    run    = "RUN" if RUN_MODE else "STP"
    # display.text(status + mode, 0, SCREEN_H - 8, 1)
    display.text(status + run, 0, SCREEN_H - 8, 1)

    # Vpp
    vpp_str = f"{last_vpp:.2f}V"
    display.text(vpp_str[:6], 0, 40, 1)
    


def render_frame(triggered):
    display.fill(0)
    draw_grid()
    draw_trigger_line()
    draw_waveform()
    draw_labels(triggered)
    display.show()

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("DSO firmware starting …")
    print(f"  Mode     : {'SIMULATION' if SIMULATION_MODE else 'LIVE ADC'}")
    print(f"  Display  : SSD1306 128×64 on I2C0 (GP4/GP5)")
    print(f"  Buttons  : GP12–GP15")

    # Splash screen
    display.fill(0)
    display.text("Portable DSO", 10, 10, 1)
    display.text("Pico + SSD1306", 7, 22, 1)
    display.text("Starting...", 20, 40, 1)
    display.show()
    utime.sleep_ms(1000)

    # while True:
    #     poll_buttons()
    #     triggered = capture_waveform()
    #     render_frame(triggered)
    global last_vpp, last_freq 
    
    last_triggered = False

    while True:
        poll_buttons()

        if RUN_MODE:
            last_triggered = capture_waveform()
            last_vpp = measure_signal()

        render_frame(last_triggered)


main()