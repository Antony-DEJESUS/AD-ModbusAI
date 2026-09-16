"""Conversion registres 16 bits <-> représentation affichée / saisie.

Couvre les modes de Modbus Doctor : champ de bits, octet 8 bits, mot 16 bits,
mot 32 bits, flottant 32 bits ; radix décimal / hexadécimal / binaire ; signé ou
non ; inversion d'octets et de mots (ordres ABCD, CDAB, BADC, DCBA).
"""

from __future__ import annotations

import enum
import struct
from collections.abc import Sequence
from dataclasses import dataclass


class Radix(enum.Enum):
    DEC = "DECIMAL"
    HEX = "HEXADECIMAL"
    BIN = "BINAIRE"


class DisplayMode(enum.Enum):
    BITS = "CHAMP DE BITS"
    BYTE8 = "OCTET 8 bits"
    WORD16 = "MOT 16 bits"
    WORD32 = "MOT 32 bits"
    FLOAT32 = "MOT FLOTTANT"

    @property
    def is_32bit(self) -> bool:
        return self in (DisplayMode.WORD32, DisplayMode.FLOAT32)


class WordOrder(enum.Enum):
    """Ordre des octets d'un 32 bits sur deux registres (A = octet de poids fort)."""

    ABCD = (False, False)  # normal : reg0 = AB, reg1 = CD
    CDAB = (False, True)  # inversion de mots
    BADC = (True, False)  # inversion d'octets
    DCBA = (True, True)  # les deux

    @property
    def byte_swap(self) -> bool:
        return self.value[0]

    @property
    def word_swap(self) -> bool:
        return self.value[1]

    @classmethod
    def from_swaps(cls, byte_swap: bool, word_swap: bool) -> WordOrder:
        return cls((byte_swap, word_swap))


@dataclass(frozen=True, slots=True)
class DisplayOptions:
    mode: DisplayMode = DisplayMode.WORD16
    radix: Radix = Radix.DEC
    signed: bool = True
    byte_swap: bool = False
    word_swap: bool = False

    @property
    def word_order(self) -> WordOrder:
        return WordOrder.from_swaps(self.byte_swap, self.word_swap and self.mode.is_32bit)


@dataclass(frozen=True, slots=True)
class DisplayRow:
    """Une ligne de la grille : libellé (n° registre), texte, et les registres couverts."""

    label: str
    text: str
    address: int  # adresse protocole du premier registre couvert
    span: int  # nombre de registres couverts (1 ou 2 ; 0.5 pour un octet -> on garde 1)


# ------------------------------------------------------------------ helpers
def swap_bytes(reg: int) -> int:
    return ((reg & 0xFF) << 8) | (reg >> 8)


def to_signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= 1 << (bits - 1) else value


def to_unsigned(value: int, bits: int) -> int:
    if not -(1 << (bits - 1)) <= value < (1 << bits):
        raise ValueError(f"Valeur {value} hors plage sur {bits} bits")
    return value & ((1 << bits) - 1)


def regs_to_u32(hi: int, lo: int, order: WordOrder) -> int:
    if order.byte_swap:
        hi, lo = swap_bytes(hi), swap_bytes(lo)
    if order.word_swap:
        hi, lo = lo, hi
    return (hi << 16) | lo


def u32_to_regs(value: int, order: WordOrder) -> tuple[int, int]:
    hi, lo = (value >> 16) & 0xFFFF, value & 0xFFFF
    if order.word_swap:
        hi, lo = lo, hi
    if order.byte_swap:
        hi, lo = swap_bytes(hi), swap_bytes(lo)
    return hi, lo


def format_int(value: int, bits: int, radix: Radix, signed: bool) -> str:
    """``value`` est non signé sur ``bits`` bits."""
    if radix is Radix.HEX:
        return f"{value:0{bits // 4}X}"
    if radix is Radix.BIN:
        raw = f"{value:0{bits}b}"
        return " ".join(raw[i : i + 4] for i in range(0, bits, 4))
    return str(to_signed(value, bits) if signed else value)


def parse_int(text: str, bits: int, radix: Radix, signed: bool) -> int:
    """Inverse de ``format_int`` : renvoie la valeur non signée sur ``bits`` bits."""
    t = text.strip().replace(" ", "").replace("_", "")
    if not t:
        raise ValueError("Valeur vide")
    if radix is Radix.HEX:
        value = int(t[2:] if t.lower().startswith("0x") else t, 16)
    elif radix is Radix.BIN:
        value = int(t[2:] if t.lower().startswith("0b") else t, 2)
    else:
        value = int(t, 10)
        if not signed and value < 0:
            raise ValueError("Valeur négative en mode non signé")
    return to_unsigned(value, bits)


def format_float(value: float) -> str:
    """Représentation la plus courte qui redonne exactement le même float32
    (3.14 s'affiche « 3.14 », pas « 3.1400001 », et la ressaisie est sans perte)."""
    if value != value or value in (float("inf"), float("-inf")):
        return repr(value)
    packed = struct.pack(">f", value)
    for precision in range(1, 10):
        text = f"{value:.{precision}g}"
        if struct.pack(">f", float(text)) == packed:
            return text
    return f"{value:.9g}"


# ------------------------------------------------------------ registres -> grille
def format_registers(regs: Sequence[int], start_address: int, opts: DisplayOptions) -> list[DisplayRow]:
    rows: list[DisplayRow] = []
    mode = opts.mode
    if mode.is_32bit:
        order = opts.word_order
        i = 0
        while i < len(regs):
            addr = start_address + i
            if i + 1 >= len(regs):  # registre orphelin : affiché en 16 bits
                r = swap_bytes(regs[i]) if opts.byte_swap else regs[i]
                rows.append(DisplayRow(str(addr), format_int(r, 16, opts.radix, opts.signed), addr, 1))
                break
            u32 = regs_to_u32(regs[i], regs[i + 1], order)
            if mode is DisplayMode.FLOAT32:
                if opts.radix is Radix.DEC:
                    text = format_float(struct.unpack(">f", u32.to_bytes(4, "big"))[0])
                else:
                    text = format_int(u32, 32, opts.radix, False)
            else:
                text = format_int(u32, 32, opts.radix, opts.signed)
            rows.append(DisplayRow(f"{addr}-{addr + 1}", text, addr, 2))
            i += 2
        return rows

    for i, reg in enumerate(regs):
        addr = start_address + i
        r = swap_bytes(reg) if opts.byte_swap else reg
        if mode is DisplayMode.BITS:
            rows.append(DisplayRow(str(addr), format_int(r, 16, Radix.BIN, False), addr, 1))
        elif mode is DisplayMode.BYTE8:
            rows.append(DisplayRow(f"{addr} H", format_int(r >> 8, 8, opts.radix, opts.signed), addr, 1))
            rows.append(DisplayRow(f"{addr} L", format_int(r & 0xFF, 8, opts.radix, opts.signed), addr, 1))
        else:
            rows.append(DisplayRow(str(addr), format_int(r, 16, opts.radix, opts.signed), addr, 1))
    return rows


def format_bits(bits: Sequence[int], start_address: int) -> list[DisplayRow]:
    """Bobines / entrées TOR : une ligne par bit, valeur 0 ou 1."""
    return [DisplayRow(str(start_address + i), "1" if b else "0", start_address + i, 1) for i, b in enumerate(bits)]


# ------------------------------------------------------------ grille -> registres
def parse_rows(texts: Sequence[str], count: int, opts: DisplayOptions) -> list[int]:
    """Convertit les textes saisis dans la grille en ``count`` registres 16 bits.

    Le nombre de lignes attendu dépend du mode (2 par registre en OCTET 8 bits,
    1 pour 2 registres en 32 bits). Lève ValueError avec un message lisible.
    """
    mode = opts.mode
    regs: list[int] = []
    if mode.is_32bit:
        order = opts.word_order
        expected = (count + 1) // 2
        _check_rows(len(texts), expected)
        for i, text in enumerate(texts):
            if 2 * i + 1 >= count:  # registre orphelin
                r = parse_int(text, 16, opts.radix, opts.signed)
                regs.append(swap_bytes(r) if opts.byte_swap else r)
                break
            if mode is DisplayMode.FLOAT32 and opts.radix is Radix.DEC:
                u32 = int.from_bytes(struct.pack(">f", float(text.strip().replace(",", "."))), "big")
            else:
                u32 = parse_int(text, 32, opts.radix, opts.signed and mode is DisplayMode.WORD32)
            regs.extend(u32_to_regs(u32, order))
        return regs

    if mode is DisplayMode.BYTE8:
        _check_rows(len(texts), 2 * count)
        for i in range(count):
            hi = parse_int(texts[2 * i], 8, opts.radix, opts.signed)
            lo = parse_int(texts[2 * i + 1], 8, opts.radix, opts.signed)
            r = (hi << 8) | lo
            regs.append(swap_bytes(r) if opts.byte_swap else r)
        return regs

    _check_rows(len(texts), count)
    for text in texts:
        if mode is DisplayMode.BITS:
            r = parse_int(text, 16, Radix.BIN, False)
        else:
            r = parse_int(text, 16, opts.radix, opts.signed)
        regs.append(swap_bytes(r) if opts.byte_swap else r)
    return regs


def parse_bits(texts: Sequence[str]) -> list[int]:
    out = []
    for text in texts:
        t = text.strip().lower()
        if t in ("1", "on", "true", "vrai"):
            out.append(1)
        elif t in ("0", "off", "false", "faux", ""):
            out.append(0)
        else:
            raise ValueError(f"Valeur de bobine invalide : {text!r} (0 ou 1)")
    return out


def _check_rows(got: int, expected: int) -> None:
    if got != expected:
        raise ValueError(f"{expected} valeur(s) attendue(s), {got} saisie(s)")
