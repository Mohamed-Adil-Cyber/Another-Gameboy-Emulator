from __future__ import annotations

import argparse
import sys
import time

from pathlib import Path


# ============================== CARTRIDGE INFO AND ACTIONS ==============================
 
ROM_SIZES = {0x00: (32*1024,2), 0x01: (64*1024,4), 0x02: (128*1024,8), 0x03: (256*1024,16),
             0x04: (512*1024,32), 0x05: (1024*1024,64), 0x06: (2048*1024,128),
             0x07: (4096*1024,256), 0x08: (8192*1024,512)}
RAM_SIZES = {0x00: (0,0), 0x01: (0,0), 0x02: (8*1024,1), 0x03: (32*1024,4),
             0x04: (128*1024,16), 0x05: (64*1024,8)}
MBC1_TYPES = {0x01,0x02,0x03}
MBC2_TYPES = {0x05,0x06}
MBC3_TYPES = {0x0F,0x10,0x11,0x12,0x13}
MBC5_TYPES = {0x19,0x1A,0x1B,0x1C,0x1D,0x1E}
 
ROM = b""
MBC = 0
ROM_BANKS = 2
ROM_MASK = 1
CART_RAM = bytearray()
RAM_BANKS = 1
 
RAM_ENABLED = False
ROM_BANK = 1
RAM_BANK = 0
LOW_BANK = 1
BANK_HI = 0
MBC1_MODE = 0
 
 
def load_cartridge(rom: bytes):
    global ROM, MBC, ROM_BANKS, ROM_MASK, CART_RAM, RAM_BANKS
    global RAM_ENABLED, ROM_BANK, RAM_BANK, LOW_BANK, BANK_HI, MBC1_MODE
 
    ROM = rom
    cart_type = rom[0x147]
 
    if cart_type in MBC1_TYPES: MBC = 1
    elif cart_type in MBC2_TYPES: MBC = 2
    elif cart_type in MBC3_TYPES: MBC = 3
    elif cart_type in MBC5_TYPES: MBC = 5
    else: MBC = 0
 
    _, rom_banks = ROM_SIZES.get(rom[0x148], (len(rom), max(1, len(rom)//0x4000)))
    ROM_BANKS = max(2, rom_banks)
    ROM_MASK = ROM_BANKS - 1
 
    if MBC == 2:
        ram_bytes, ram_banks = 512, 1
    else:
        ram_bytes, ram_banks = RAM_SIZES.get(rom[0x149], (0, 0))
 
    CART_RAM = bytearray(ram_bytes)
    RAM_BANKS = max(1, ram_banks)
 
    RAM_ENABLED = False
    ROM_BANK = 1
    RAM_BANK = 0
    LOW_BANK = 1
    BANK_HI = 0
    MBC1_MODE = 0
 
 
def cart_read_rom(address):
    if address < 0x4000:
        if MBC == 1 and MBC1_MODE == 1:
            bank = (BANK_HI << 5) & ROM_MASK
            return ROM[bank*0x4000 + address]
        return ROM[address]
    offset = ROM_BANK*0x4000 + (address - 0x4000)
    return ROM[offset] if offset < len(ROM) else 0xFF
 
 
def cart_write_rom(address, value):
    global RAM_ENABLED, ROM_BANK, RAM_BANK, BANK_HI, MBC1_MODE
 
    if MBC == 0:
        return
    if MBC == 2:
        if address < 0x4000:
            if address & 0x0100:
                ROM_BANK = max(1, value & 0x0F) & ROM_MASK
            else:
                RAM_ENABLED = (value & 0x0F) == 0x0A
        return
 
    if address < 0x2000:
        RAM_ENABLED = (value & 0x0F) == 0x0A
    elif address < 0x3000:
        if MBC == 5:
            ROM_BANK = ((ROM_BANK & 0x100) | value) & ROM_MASK
        else:
            set_low_bank(value)
    elif address < 0x4000:
        if MBC == 5:
            ROM_BANK = ((ROM_BANK & 0xFF) | ((value & 1) << 8)) & ROM_MASK
        else:
            set_low_bank(value)
    elif address < 0x6000:
        BANK_HI = value & 0x03 if MBC == 1 else value & 0x0F
        RAM_BANK = BANK_HI % RAM_BANKS
        if MBC == 1:
            update_mbc1_bank()
    else:
        if MBC == 1:
            MBC1_MODE = value & 1
            update_mbc1_bank()
 
 
def set_low_bank(value):
    global LOW_BANK, ROM_BANK
 
    if MBC == 1:
        LOW_BANK = value & 0x1F or 1
        update_mbc1_bank()
    else:
        ROM_BANK = (value & 0x7F or 1) & ROM_MASK
 
 
def update_mbc1_bank():
    global ROM_BANK, RAM_BANK
 
    bank = ((BANK_HI << 5) | LOW_BANK) & ROM_MASK
    ROM_BANK = bank or 1
    RAM_BANK = (BANK_HI if MBC1_MODE else 0) % RAM_BANKS
 
 
def cart_read_ram(address):
    if not (RAM_ENABLED and CART_RAM):
        return 0xFF
    if MBC == 2:
        return CART_RAM[address & 0x01FF] | 0xF0
    offset = RAM_BANK*0x2000 + address
    return CART_RAM[offset] if offset < len(CART_RAM) else 0xFF
 
 
def cart_write_ram(address, value):
    if not (RAM_ENABLED and CART_RAM):
        return
    if MBC == 2:
        CART_RAM[address & 0x01FF] = value & 0x0F
        return
    offset = RAM_BANK*0x2000 + address
    if offset < len(CART_RAM):
        CART_RAM[offset] = value
 
# ================================ TIMER (Placeholder code, very inaccurate) =================================

TAC_SHIFT = [10, 4, 6, 8]

DIV_COUNTER = 0xABCC
TIMA = 0
TMA = 0
TAC = 0xF8


def timer_div():
    return (DIV_COUNTER >> 8) & 0xFF


def timer_tick(cycles):
    global DIV_COUNTER, TIMA

    old = DIV_COUNTER
    DIV_COUNTER = (old + cycles) & 0xFFFF
    if not TAC & 0x04:
        return
    shift = TAC_SHIFT[TAC & 0x03]
    steps = ((old + cycles) >> shift) - (old >> shift)
    for _ in range(steps):
        TIMA += 1
        if TIMA > 0xFF:
            TIMA = TMA
            request_interrupt(2)


# =============================== JOYPAD (Basic controller mappping) =================================

BUTTONS = ["a", "b", "select", "start"]
DPAD = ["right", "left", "up", "down"]

JOY_SELECT = 0x30
JOY_BUTTONS = 0x0F
JOY_DPAD = 0x0F


def joypad_read():
    out = 0x0F
    if not JOY_SELECT & 0x10:
        out &= JOY_DPAD
    if not JOY_SELECT & 0x20:
        out &= JOY_BUTTONS
    return 0xC0 | (JOY_SELECT & 0x30) | out


def joypad_write(value):
    global JOY_SELECT
    JOY_SELECT = value & 0x30


def joypad_set(name, pressed):
    global JOY_BUTTONS, JOY_DPAD

    if name in DPAD:
        bit = DPAD.index(name)
        before = JOY_DPAD
        JOY_DPAD = (before & ~(1 << bit) & 0x0F) if pressed else (before | (1 << bit))
        changed = before != JOY_DPAD
    elif name in BUTTONS:
        bit = BUTTONS.index(name)
        before = JOY_BUTTONS
        JOY_BUTTONS = (before & ~(1 << bit) & 0x0F) if pressed else (before | (1 << bit))
        changed = before != JOY_BUTTONS
    else:
        return

    if pressed and changed:
        request_interrupt(4)


# ================================= PPU (Graphics rendering) ===================================

SCREEN_W, SCREEN_H = 160, 144
OAM_DOTS, DRAW_DOTS, LINE_DOTS = 80, 172, 456
FRAME_CYCLES = LINE_DOTS * 154

VRAM = bytearray(0x2000)
OAM = bytearray(0xA0)

LCDC = 0x91
STAT = 0x85
SCY = SCX = LY = LYC = 0
BGP, OBP0, OBP1 = 0xFC, 0xFF, 0xFF
WY = WX = 0

PPU_MODE = 2
DOTS = 0
WINDOW_LINE = 0
STAT_LINE = False
FRAME_READY = False

FRAMEBUFFER = bytearray(SCREEN_W * SCREEN_H)
BG_LINE = bytearray(SCREEN_W)


def ppu_read_stat():
    return 0x80 | (STAT & 0x78) | (0x04 if LY == LYC else 0x00) | PPU_MODE


def ppu_write_lcdc(value):
    global LCDC, LY, DOTS, PPU_MODE, WINDOW_LINE, STAT_LINE

    was_on = LCDC & 0x80
    LCDC = value
    if was_on and not value & 0x80:
        LY = DOTS = PPU_MODE = WINDOW_LINE = 0
        STAT_LINE = False
    elif not was_on and value & 0x80:
        DOTS, PPU_MODE = 0, 2


def ppu_tick(cycles):
    global DOTS, LY, WINDOW_LINE, PPU_MODE, FRAME_READY

    if not LCDC & 0x80:
        return

    DOTS += cycles
    while DOTS >= LINE_DOTS:
        DOTS -= LINE_DOTS
        LY += 1
        if LY > 153:
            LY = 0
            WINDOW_LINE = 0

    if LY >= SCREEN_H: mode = 1
    elif DOTS < OAM_DOTS: mode = 2
    elif DOTS < OAM_DOTS + DRAW_DOTS: mode = 3
    else: mode = 0

    if mode != PPU_MODE:
        PPU_MODE = mode
        if mode == 0:
            render_line()
        elif mode == 1:
            request_interrupt(0)
            FRAME_READY = True

    update_stat_line()


def update_stat_line():
    global STAT_LINE

    line = ((STAT & 0x40 and LY == LYC)
            or (STAT & 0x20 and PPU_MODE == 2)
            or (STAT & 0x10 and PPU_MODE == 1)
            or (STAT & 0x08 and PPU_MODE == 0))
    if line and not STAT_LINE:
        request_interrupt(1)
    STAT_LINE = bool(line)


def render_line():
    base = LY * SCREEN_W

    if LCDC & 0x01:
        render_background(base, LY)
    else:
        shade = BGP & 0x03
        for x in range(SCREEN_W):
            FRAMEBUFFER[base + x] = shade
            BG_LINE[x] = 0

    if LCDC & 0x20 and WY <= LY and WX <= 166:
        render_window(base, LY)

    if LCDC & 0x02:
        render_sprites(base, LY)


def render_background(base, ly):
    vram, fb, bg_line, bgp = VRAM, FRAMEBUFFER, BG_LINE, BGP
    signed = not LCDC & 0x10
    map_base = 0x1C00 if LCDC & 0x08 else 0x1800
    y = (ly + SCY) & 0xFF
    row = (y >> 3) << 5
    fine_y = (y & 7) << 1
    x, scx = 0, SCX

    while x < SCREEN_W:
        xx = (x + scx) & 0xFF
        tile = vram[map_base + row + (xx >> 3)]
        addr = 0x1000 + (((tile ^ 0x80) - 0x80) << 4) + fine_y if signed else (tile << 4) + fine_y
        lo, hi = vram[addr], vram[addr + 1]
        for bit in range(7 - (xx & 7), -1, -1):
            ci = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
            bg_line[x] = ci
            fb[base + x] = (bgp >> (ci << 1)) & 3
            x += 1
            if x >= SCREEN_W:
                break


def render_window(base, ly):
    global WINDOW_LINE

    vram, fb, bg_line, bgp = VRAM, FRAMEBUFFER, BG_LINE, BGP
    signed = not LCDC & 0x10
    map_base = 0x1C00 if LCDC & 0x40 else 0x1800
    wx = WX - 7
    row = (WINDOW_LINE >> 3) << 5
    fine_y = (WINDOW_LINE & 7) << 1
    x = max(0, wx)
    drawn = False

    while x < SCREEN_W:
        wxx = x - wx
        tile = vram[map_base + row + (wxx >> 3)]
        addr = 0x1000 + (((tile ^ 0x80) - 0x80) << 4) + fine_y if signed else (tile << 4) + fine_y
        lo, hi = vram[addr], vram[addr + 1]
        for bit in range(7 - (wxx & 7), -1, -1):
            ci = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
            bg_line[x] = ci
            fb[base + x] = (bgp >> (ci << 1)) & 3
            x += 1
            drawn = True
            if x >= SCREEN_W:
                break

    if drawn:
        WINDOW_LINE += 1


def render_sprites(base, ly):
    vram, oam, fb, bg_line = VRAM, OAM, FRAMEBUFFER, BG_LINE
    height = 16 if LCDC & 0x04 else 8

    visible = []
    for i in range(40):
        o = i << 2
        sy = oam[o] - 16
        if sy <= ly < sy + height:
            visible.append((oam[o + 1], i))
            if len(visible) == 10:
                break
    visible.sort(reverse=True)

    for sx_raw, i in visible:
        o = i << 2
        sy = oam[o] - 16
        sx = sx_raw - 8
        tile = oam[o + 2]
        attr = oam[o + 3]
        if height == 16:
            tile &= 0xFE
        row = ly - sy
        if attr & 0x40:
            row = height - 1 - row
        addr = (tile << 4) + (row << 1)
        lo, hi = vram[addr], vram[addr + 1]
        pal = OBP1 if attr & 0x10 else OBP0
        behind, flip = attr & 0x80, attr & 0x20

        for px in range(8):
            x = sx + px
            if x < 0 or x >= SCREEN_W:
                continue
            bit = px if flip else 7 - px
            ci = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
            if not ci or (behind and bg_line[x]):
                continue
            fb[base + x] = (pal >> (ci << 1)) & 3


# ================================= MMU ===================================

WRAM = bytearray(0x2000)
HRAM = bytearray(0x7F)
AUDIO = bytearray(0x30) #There is no APU implemented yet

IF = 0xE1
IE = 0x00
SB = 0x00
SC = 0x7E
SERIAL = bytearray()


def request_interrupt(bit):
    global IF
    IF |= 1 << bit


def read8(address):
    if address < 0x8000: return cart_read_rom(address)
    if address < 0xA000: return VRAM[address - 0x8000]
    if address < 0xC000: return cart_read_ram(address - 0xA000)
    if address < 0xE000: return WRAM[address - 0xC000]
    if address < 0xFE00: return WRAM[address - 0xE000]
    if address < 0xFEA0: return OAM[address - 0xFE00]
    if address < 0xFF00: return 0xFF
    if address < 0xFF80: return read_io(address)
    if address < 0xFFFF: return HRAM[address - 0xFF80]
    return IE


def write8(address, value):
    global IE

    if address < 0x8000: cart_write_rom(address, value)
    elif address < 0xA000: VRAM[address - 0x8000] = value
    elif address < 0xC000: cart_write_ram(address - 0xA000, value)
    elif address < 0xE000: WRAM[address - 0xC000] = value
    elif address < 0xFE00: WRAM[address - 0xE000] = value
    elif address < 0xFEA0: OAM[address - 0xFE00] = value
    elif address < 0xFF00: pass
    elif address < 0xFF80: write_io(address, value)
    elif address < 0xFFFF: HRAM[address - 0xFF80] = value
    else: IE = value


def read_io(address):
    if address == 0xFF00: return joypad_read()
    if address == 0xFF01: return SB
    if address == 0xFF02: return SC | 0x7E
    if address == 0xFF04: return timer_div()
    if address == 0xFF05: return TIMA
    if address == 0xFF06: return TMA
    if address == 0xFF07: return TAC | 0xF8
    if address == 0xFF0F: return IF | 0xE0
    if address == 0xFF26: return (AUDIO[0x16] & 0x80) | 0x70
    if 0xFF10 <= address <= 0xFF3F: return AUDIO[address - 0xFF10]
    if address == 0xFF40: return LCDC
    if address == 0xFF41: return ppu_read_stat()
    if address == 0xFF42: return SCY
    if address == 0xFF43: return SCX
    if address == 0xFF44: return LY
    if address == 0xFF45: return LYC
    if address == 0xFF47: return BGP
    if address == 0xFF48: return OBP0
    if address == 0xFF49: return OBP1
    if address == 0xFF4A: return WY
    if address == 0xFF4B: return WX
    return 0xFF


def write_io(address, value):
    global SB, SC, DIV_COUNTER, TIMA, TMA, TAC, IF
    global STAT, SCY, SCX, LYC, BGP, OBP0, OBP1, WY, WX

    if address == 0xFF00: joypad_write(value)
    elif address == 0xFF01: SB = value
    elif address == 0xFF02:
        SC = value
        if value & 0x80:
            SERIAL.append(SB)
            SC &= 0x7F
            request_interrupt(3)
    elif address == 0xFF04: DIV_COUNTER = 0
    elif address == 0xFF05: TIMA = value
    elif address == 0xFF06: TMA = value
    elif address == 0xFF07: TAC = value
    elif address == 0xFF0F: IF = value & 0x1F
    elif 0xFF10 <= address <= 0xFF3F: AUDIO[address - 0xFF10] = value
    elif address == 0xFF40: ppu_write_lcdc(value)
    elif address == 0xFF41: STAT = value & 0x78
    elif address == 0xFF42: SCY = value
    elif address == 0xFF43: SCX = value
    elif address == 0xFF45: LYC = value
    elif address == 0xFF46: oam_dma(value)
    elif address == 0xFF47: BGP = value
    elif address == 0xFF48: OBP0 = value
    elif address == 0xFF49: OBP1 = value
    elif address == 0xFF4A: WY = value
    elif address == 0xFF4B: WX = value

#Placeholder DMA
def oam_dma(value):
    source = value << 8
    for i in range(0xA0):
        OAM[i] = read8(source + i)


# ================================= CPU and OPCODES ===================================

FLAG_Z, FLAG_N, FLAG_H, FLAG_C = 0x80, 0x40, 0x20, 0x10

OPCODE_CYCLES = [
    4,12,8,8,4,4,8,4,20,8,8,8,4,4,8,4, 4,12,8,8,4,4,8,4,12,8,8,8,4,4,8,4,
    8,12,8,8,4,4,8,4,8,8,8,8,4,4,8,4, 8,12,8,8,12,12,12,4,8,8,8,8,4,4,8,4,
    4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4,
    4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4, 8,8,8,8,8,8,4,8,4,4,4,4,4,4,8,4,
    4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4,
    4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,4,4,4,4,4,4,8,4,
    8,12,12,16,12,16,8,16,8,16,12,4,12,24,8,16, 8,12,12,4,12,16,8,16,8,16,12,4,12,4,8,16,
    12,12,8,4,4,16,8,16,16,4,16,4,4,4,8,16, 12,12,8,4,4,16,8,16,12,8,16,4,4,4,8,16,
]

REG = bytearray([0x00, 0x13, 0x00, 0xD8, 0x01, 0x4D, 0x00, 0x01])

F = 0xB0
SP = 0xFFFE
PC = 0x0100

IME = False
IME_PENDING = False
HALTED = False
HALT_BUG = False

OPCODE = 0
EXTRA = 0


def hl():
    return (REG[4] << 8) | REG[5]


def set_hl(v):
    REG[4], REG[5] = (v >> 8) & 0xFF, v & 0xFF


def read_rp(p):
    return SP if p == 3 else (REG[p << 1] << 8) | REG[(p << 1) + 1]


def write_rp(p, value):
    global SP
    if p == 3:
        SP = value & 0xFFFF
        return
    REG[p << 1] = (value >> 8) & 0xFF
    REG[(p << 1) + 1] = value & 0xFF


def read_rp2(p):
    return ((REG[7] << 8) | F) if p == 3 else read_rp(p)


def write_rp2(p, value):
    global F
    if p == 3:
        REG[7], F = (value >> 8) & 0xFF, value & 0xF0
        return
    write_rp(p, value)


def get_r(i):
    return read8(hl()) if i == 6 else REG[i]


def set_r(i, value):
    if i == 6: write8(hl(), value & 0xFF)
    else: REG[i] = value & 0xFF


def fetch8():
    global PC
    v = read8(PC)
    PC = (PC + 1) & 0xFFFF
    return v


def fetch16():
    lo = fetch8()
    hi = fetch8()
    return (hi << 8) | lo


def push16(value):
    global SP
    SP = (SP - 1) & 0xFFFF
    write8(SP, (value >> 8) & 0xFF)
    SP = (SP - 1) & 0xFFFF
    write8(SP, value & 0xFF)


def pop16():
    global SP
    lo = read8(SP)
    SP = (SP + 1) & 0xFFFF
    hi = read8(SP)
    SP = (SP + 1) & 0xFFFF
    return (hi << 8) | lo


def condition(y):
    if y == 0: return not F & FLAG_Z
    if y == 1: return bool(F & FLAG_Z)
    if y == 2: return not F & FLAG_C
    return bool(F & FLAG_C)


def cpu_step():
    global IME, IME_PENDING, PC, OPCODE, EXTRA, HALT_BUG

    if IME_PENDING:
        IME = True
        IME_PENDING = False

    cycles = service_interrupts()
    if cycles:
        return cycles
    if HALTED:
        return 4

    opcode = read8(PC)
    if HALT_BUG:
        HALT_BUG = False
    else:
        PC = (PC + 1) & 0xFFFF

    OPCODE, EXTRA = opcode, 0
    TABLE[opcode]()
    return OPCODE_CYCLES[opcode] + EXTRA


def service_interrupts():
    global HALTED, IME, IF, PC

    pending = IE & IF & 0x1F
    if not pending:
        return 0
    HALTED = False
    if not IME:
        return 0
    IME = False
    for i in range(5):
        bit = 1 << i
        if pending & bit:
            IF &= ~bit & 0xFF
            push16(PC)
            PC = 0x40 + (i << 3)
            return 20
    return 0


def op_x0_z0():
    global PC, EXTRA

    y = (OPCODE >> 3) & 7
    if y == 0: return
    if y == 1:
        address = fetch16()
        write8(address, SP & 0xFF)
        write8((address + 1) & 0xFFFF, (SP >> 8) & 0xFF)
        return
    if y == 2:
        fetch8()
        return
    offset = fetch8()
    if offset > 127: offset -= 256
    if y == 3 or condition(y - 4):
        PC = (PC + offset) & 0xFFFF
        if y != 3: EXTRA = 4


def op_x0_z1():
    global F

    y = (OPCODE >> 3) & 7
    p = y >> 1
    if not y & 1:
        write_rp(p, fetch16())
        return
    left, value = hl(), read_rp(p)
    result = left + value
    half = (left & 0x0FFF) + (value & 0x0FFF) > 0x0FFF
    F = (F & FLAG_Z) | (FLAG_H if half else 0) | (FLAG_C if result > 0xFFFF else 0)
    set_hl(result & 0xFFFF)


def op_x0_z2():
    y = (OPCODE >> 3) & 7
    p = y >> 1
    store = not y & 1
    if p == 0: address = (REG[0] << 8) | REG[1]
    elif p == 1: address = (REG[2] << 8) | REG[3]
    else: address = hl()
    if store: write8(address, REG[7])
    else: REG[7] = read8(address)
    if p == 2: set_hl((address + 1) & 0xFFFF)
    elif p == 3: set_hl((address - 1) & 0xFFFF)


def op_x0_z3():
    y = (OPCODE >> 3) & 7
    p = y >> 1
    delta = -1 if y & 1 else 1
    write_rp(p, (read_rp(p) + delta) & 0xFFFF)


def op_inc_r():
    global F

    i = (OPCODE >> 3) & 7
    value = (get_r(i) + 1) & 0xFF
    F = (F & FLAG_C) | (FLAG_Z if not value else 0) | (FLAG_H if not value & 0x0F else 0)
    set_r(i, value)


def op_dec_r():
    global F

    i = (OPCODE >> 3) & 7
    value = (get_r(i) - 1) & 0xFF
    F = (F & FLAG_C) | FLAG_N | (FLAG_Z if not value else 0) | (FLAG_H if value & 0x0F == 0x0F else 0)
    set_r(i, value)


def op_ld_r_n():
    set_r((OPCODE >> 3) & 7, fetch8())


def op_x0_z7():
    global F

    y = (OPCODE >> 3) & 7
    a = REG[7]
    carry = (F >> 4) & 1

    if y == 0:
        c = a >> 7
        a = ((a << 1) | c) & 0xFF
        F = FLAG_C if c else 0
    elif y == 1:
        c = a & 1
        a = (a >> 1) | (c << 7)
        F = FLAG_C if c else 0
    elif y == 2:
        c = a >> 7
        a = ((a << 1) | carry) & 0xFF
        F = FLAG_C if c else 0
    elif y == 3:
        c = a & 1
        a = (a >> 1) | (carry << 7)
        F = FLAG_C if c else 0
    elif y == 4:
        f = F
        if not f & FLAG_N:
            if f & FLAG_C or a > 0x99:
                a = (a + 0x60) & 0xFF
                carry = 1
            else:
                carry = 0
            if f & FLAG_H or a & 0x0F > 0x09:
                a = (a + 0x06) & 0xFF
        else:
            if f & FLAG_C: a = (a - 0x60) & 0xFF
            if f & FLAG_H: a = (a - 0x06) & 0xFF
            carry = 1 if f & FLAG_C else 0
        F = (f & FLAG_N) | (FLAG_Z if not a else 0) | (FLAG_C if carry else 0)
    elif y == 5:
        a = ~a & 0xFF
        F = (F & (FLAG_Z | FLAG_C)) | FLAG_N | FLAG_H
    elif y == 6:
        F = (F & FLAG_Z) | FLAG_C
    else:
        F = (F & FLAG_Z) | (0 if F & FLAG_C else FLAG_C)

    REG[7] = a


def op_ld_r_r():
    set_r((OPCODE >> 3) & 7, get_r(OPCODE & 7))


def op_halt():
    global HALTED, HALT_BUG

    if IME: HALTED = True
    elif IE & IF & 0x1F: HALT_BUG = True
    else: HALTED = True


def op_alu_r():
    alu((OPCODE >> 3) & 7, get_r(OPCODE & 7))


def op_alu_n():
    alu((OPCODE >> 3) & 7, fetch8())


def alu(kind, value):
    global F

    a = REG[7]
    carry = (F >> 4) & 1

    if kind == 0:
        result = a + value
        half = (a & 0x0F) + (value & 0x0F) > 0x0F
        F = (FLAG_Z if not result & 0xFF else 0) | (FLAG_H if half else 0) | (FLAG_C if result > 0xFF else 0)
        REG[7] = result & 0xFF
    elif kind == 1:
        result = a + value + carry
        half = (a & 0x0F) + (value & 0x0F) + carry > 0x0F
        F = (FLAG_Z if not result & 0xFF else 0) | (FLAG_H if half else 0) | (FLAG_C if result > 0xFF else 0)
        REG[7] = result & 0xFF
    elif kind == 2:
        result = a - value
        F = FLAG_N | (FLAG_Z if not result & 0xFF else 0) | (FLAG_H if (a & 0x0F) < (value & 0x0F) else 0) | (FLAG_C if result < 0 else 0)
        REG[7] = result & 0xFF
    elif kind == 3:
        result = a - value - carry
        F = FLAG_N | (FLAG_Z if not result & 0xFF else 0) | (FLAG_H if (a & 0x0F) < (value & 0x0F) + carry else 0) | (FLAG_C if result < 0 else 0)
        REG[7] = result & 0xFF
    elif kind == 4:
        a &= value
        F = FLAG_H | (FLAG_Z if not a else 0)
        REG[7] = a
    elif kind == 5:
        a ^= value
        F = FLAG_Z if not a else 0
        REG[7] = a
    elif kind == 6:
        a |= value
        F = FLAG_Z if not a else 0
        REG[7] = a
    else:
        result = a - value
        F = FLAG_N | (FLAG_Z if not result & 0xFF else 0) | (FLAG_H if (a & 0x0F) < (value & 0x0F) else 0) | (FLAG_C if result < 0 else 0)


def op_x3_z0():
    global PC, EXTRA, F, SP

    y = (OPCODE >> 3) & 7
    if y < 4:
        if condition(y):
            PC = pop16()
            EXTRA = 12
        return
    if y == 4:
        write8(0xFF00 + fetch8(), REG[7])
    elif y == 6:
        REG[7] = read8(0xFF00 + fetch8())
    else:
        offset = fetch8()
        signed = offset - 256 if offset > 127 else offset
        sp = SP
        result = (sp + signed) & 0xFFFF
        F = (FLAG_H if (sp & 0x0F) + (offset & 0x0F) > 0x0F else 0) | (FLAG_C if (sp & 0xFF) + offset > 0xFF else 0)
        if y == 5: SP = result
        else: set_hl(result)


def op_x3_z1():
    global PC, IME, SP

    y = (OPCODE >> 3) & 7
    p = y >> 1
    if not y & 1:
        write_rp2(p, pop16())
        return
    if p == 0: PC = pop16()
    elif p == 1:
        PC = pop16()
        IME = True
    elif p == 2: PC = hl()
    else: SP = hl()


def op_x3_z2():
    global PC, EXTRA

    y = (OPCODE >> 3) & 7
    if y < 4:
        address = fetch16()
        if condition(y):
            PC = address
            EXTRA = 4
        return
    if y == 4: write8(0xFF00 + REG[1], REG[7])
    elif y == 5: write8(fetch16(), REG[7])
    elif y == 6: REG[7] = read8(0xFF00 + REG[1])
    else: REG[7] = read8(fetch16())


def op_x3_z3():
    global PC, IME, IME_PENDING

    y = (OPCODE >> 3) & 7
    if y == 0: PC = fetch16()
    elif y == 1: execute_cb()
    elif y == 6: IME = IME_PENDING = False
    elif y == 7: IME_PENDING = True
    else: op_illegal()


def op_call_cc():
    global PC, EXTRA

    y = (OPCODE >> 3) & 7
    if y >= 4:
        op_illegal()
        return
    address = fetch16()
    if condition(y):
        push16(PC)
        PC = address
        EXTRA = 12


def op_x3_z5():
    global PC

    y = (OPCODE >> 3) & 7
    p = y >> 1
    if not y & 1:
        push16(read_rp2(p))
        return
    if p:
        op_illegal()
        return
    address = fetch16()
    push16(PC)
    PC = address


def op_rst():
    global PC
    push16(PC)
    PC = OPCODE & 0x38


def op_illegal():
    raise RuntimeError(f"illegal opcode ${OPCODE:02X} at ${(PC - 1) & 0xFFFF:04X}")


def execute_cb():
    global F, EXTRA

    opcode = fetch8()
    x, y, z = opcode >> 6, (opcode >> 3) & 7, opcode & 7
    value = get_r(z)

    if x == 1:
        F = (F & FLAG_C) | FLAG_H | (FLAG_Z if not value & (1 << y) else 0)
        EXTRA = 8 if z == 6 else 4
        return
    if x == 2:
        set_r(z, value & ~(1 << y) & 0xFF)
        EXTRA = 12 if z == 6 else 4
        return
    if x == 3:
        set_r(z, value | (1 << y))
        EXTRA = 12 if z == 6 else 4
        return

    carry = (F >> 4) & 1

    if y == 0:
        c = value >> 7
        value = ((value << 1) | c) & 0xFF
    elif y == 1:
        c = value & 1
        value = (value >> 1) | (c << 7)
    elif y == 2:
        c = value >> 7
        value = ((value << 1) | carry) & 0xFF
    elif y == 3:
        c = value & 1
        value = (value >> 1) | (carry << 7)
    elif y == 4:
        c = value >> 7
        value = (value << 1) & 0xFF
    elif y == 5:
        c = value & 1
        value = (value >> 1) | (value & 0x80)
    elif y == 6:
        c = 0
        value = ((value << 4) | (value >> 4)) & 0xFF
    else:
        c = value & 1
        value >>= 1

    F = (FLAG_Z if not value else 0) | (FLAG_C if c else 0)
    set_r(z, value)
    EXTRA = 12 if z == 6 else 4


def build_table():
    table = [op_illegal] * 256
    x0 = [op_x0_z0, op_x0_z1, op_x0_z2, op_x0_z3,
          op_inc_r, op_dec_r, op_ld_r_n, op_x0_z7]
    x3 = [op_x3_z0, op_x3_z1, op_x3_z2, op_x3_z3,
          op_call_cc, op_x3_z5, op_alu_n, op_rst]
    for op in range(256):
        x, z = op >> 6, op & 7
        if x == 0: table[op] = x0[z]
        elif x == 1: table[op] = op_halt if op == 0x76 else op_ld_r_r
        elif x == 2: table[op] = op_alu_r
        else: table[op] = x3[z]
    return table


TABLE = build_table()


# ============================== FRAME LOOP ===============================

def run_frame():
    global FRAME_READY

    FRAME_READY = False
    budget = FRAME_CYCLES
    while not FRAME_READY and budget > 0:
        cycles = cpu_step()
        timer_tick(cycles)
        ppu_tick(cycles)
        budget -= cycles


def take_serial():
    out = bytes(SERIAL)
    SERIAL.clear()
    return out


# =============================== GAME SCREEN =================================

PALETTE = [(0x9B,0xBC,0x0F), (0x8B,0xAC,0x0F), (0x30,0x62,0x30), (0x0F,0x38,0x0F)]
RGB_LUT = [bytes(c) for c in PALETTE] + [bytes(PALETTE[0])] * 252


def framebuffer_rgb():
    return b"".join(map(RGB_LUT.__getitem__, FRAMEBUFFER))

 
KEYMAP = {"up": "up", "down": "down", "left": "left", "right": "right",
          "z": "a", "x": "b", "return": "start", "backspace": "select"}
 
 
def run_windowed(scale: int = 4):
    try:
        import pygame
    except ImportError:
        print("pygame is required to run a cartridge:\n    pip install pygame")
        raise SystemExit(1)
 
    pygame.init()
    title = ROM[0x134:0x143].decode(errors="ignore").rstrip("\x00").strip()
    screen = pygame.display.set_mode((SCREEN_W * scale, SCREEN_H * scale))
    pygame.display.set_caption(f"Another Gameboy Emulator - {title or 'no title'}")
    clock = pygame.time.Clock()
    size = (SCREEN_W, SCREEN_H)
 
    keys = {getattr(pygame, f"K_{n.upper()}" if len(n) > 1 else f"K_{n}"): b for n, b in KEYMAP.items()}
 
    running = True
 
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in keys:
                    joypad_set(keys[event.key], event.type == pygame.KEYDOWN)
 
        run_frame()
 
        frame = pygame.image.frombuffer(framebuffer_rgb(), size, "RGB")
        screen.blit(pygame.transform.scale(frame, screen.get_size()), (0, 0))
        pygame.display.flip()
 
        serial = take_serial()
        if serial:
            sys.stdout.write(serial.decode(errors="replace"))
            sys.stdout.flush()
 
        clock.tick(60)
 
    pygame.quit()
 
 
# ================================= MAIN ===================================
 
def main():
    parser = argparse.ArgumentParser(description="Game Boy emulator - run a cartridge")
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
 
    load_cartridge(args.rom.read_bytes())
    run_windowed()
 
 
if __name__ == "__main__":
    main()
 
