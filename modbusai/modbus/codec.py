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
    FLOAT32 = "FLOTTANT 32 bits"
    WORD64 = "MOT 64 bits"
    FLOAT64 = "FLOTTANT 64 bits"

    @property
    def words(self) -> int:
        """Nombre de registres 16 bits par valeur affichée."""
        if self in (DisplayMode.WORD32, DisplayMode.FLOAT32):
            return 2
        if self in (DisplayMode.WORD64, DisplayMode.FLOAT64):
            return 4
        return 1

    @property
    def is_multiword(self) -> bool:
        return self.words > 1

    @property
    def is_float(self) -> bool:
        return self in (DisplayMode.FLOAT32, DisplayMode.FLOAT64)


class WordOrder(enum.Enum):
    """Ordre des octets d'une valeur multi-registres (A = octet de poids fort).

    Les noms sont ceux du cas 32 bits ; en 64 bits la même combinaison donne
    ABCDEFGH, GHEFCDAB, BADCFEHG ou HGFEDCBA (voir ``order_label``).
    """

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


def order_label(words: int, byte_swap: bool, word_swap: bool) -> str:
    """Ordre des octets tel qu'ils apparaissent dans les registres, ex. ``CDAB``.
    ``words`` = nombre de registres (2 -> 4 lettres, 4 -> 8 lettres)."""
    letters = "ABCDEFGH"[: 2 * words]
    pairs = [letters[i : i + 2] for i in range(0, len(letters), 2)]
    if word_swap:
        pairs.reverse()
    if byte_swap:
        pairs = [p[::-1] for p in pairs]
    return "".join(pairs)


@dataclass(frozen=True, slots=True)
class DisplayOptions:
    mode: DisplayMode = DisplayMode.WORD16
    radix: Radix = Radix.DEC
    signed: bool = True
    byte_swap: bool = False
    word_swap: bool = False

    @property
    def word_order(self) -> WordOrder:
        return WordOrder.from_swaps(self.byte_swap, self.word_swap and self.mode.is_multiword)

    @property
    def order_label(self) -> str:
        return order_label(self.mode.words, self.byte_swap, self.word_swap) if self.mode.is_multiword else ""


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


def regs_to_uint(regs: Sequence[int], order: WordOrder) -> int:
    """Assemble N registres en entier non signé de 16·N bits.
    ``word_swap`` inverse l'ordre des registres (poids faible en premier)."""
    rs = [swap_bytes(r) if order.byte_swap else r for r in regs]
    if order.word_swap:
        rs.reverse()
    value = 0
    for r in rs:
        value = (value << 16) | r
    return value


def uint_to_regs(value: int, words: int, order: WordOrder) -> tuple[int, ...]:
    rs = [(value >> (16 * (words - 1 - i))) & 0xFFFF for i in range(words)]
    if order.word_swap:
        rs.reverse()
    if order.byte_swap:
        rs = [swap_bytes(r) for r in rs]
    return tuple(rs)


def regs_to_u32(hi: int, lo: int, order: WordOrder) -> int:
    return regs_to_uint((hi, lo), order)


def u32_to_regs(value: int, order: WordOrder) -> tuple[int, int]:
    hi, lo = uint_to_regs(value, 2, order)
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


def format_float(value: float, fmt: str = ">f") -> str:
    """Représentation la plus courte qui redonne exactement le même flottant
    (3.14 s'affiche « 3.14 », pas « 3.1400001 », et la ressaisie est sans perte).
    ``fmt`` : ``">f"`` pour 32 bits, ``">d"`` pour 64 bits."""
    if value != value or value in (float("inf"), float("-inf")):
        return repr(value)
    packed = struct.pack(fmt, value)
    max_precision = 9 if fmt == ">f" else 17
    for precision in range(1, max_precision + 1):
        text = f"{value:.{precision}g}"
        if struct.pack(fmt, float(text)) == packed:
            return text
    return f"{value:.{max_precision}g}"


def _float_fmt(mode: DisplayMode) -> str:
    return ">d" if mode is DisplayMode.FLOAT64 else ">f"


# ------------------------------------------------------------ registres -> grille
def format_registers(regs: Sequence[int], start_address: int, opts: DisplayOptions) -> list[DisplayRow]:
    rows: list[DisplayRow] = []
    mode = opts.mode
    if mode.is_multiword:
        order = opts.word_order
        words = mode.words
        bits = 16 * words
        i = 0
        while i < len(regs):
            addr = start_address + i
            if i + words > len(regs):  # registres orphelins : affichés en 16 bits
                for j in range(i, len(regs)):
                    r = swap_bytes(regs[j]) if opts.byte_swap else regs[j]
                    a = start_address + j
                    rows.append(DisplayRow(str(a), format_int(r, 16, opts.radix, opts.signed), a, 1))
                break
            value = regs_to_uint(regs[i : i + words], order)
            if mode.is_float:
                if opts.radix is Radix.DEC:
                    fmt = _float_fmt(mode)
                    text = format_float(struct.unpack(fmt, value.to_bytes(bits // 8, "big"))[0], fmt)
                else:
                    text = format_int(value, bits, opts.radix, False)
            else:
                text = format_int(value, bits, opts.radix, opts.signed)
            rows.append(DisplayRow(f"{addr}-{addr + words - 1}", text, addr, words))
            i += words
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
    if mode.is_multiword:
        order = opts.word_order
        words = mode.words
        bits = 16 * words
        full, orphans = divmod(count, words)
        _check_rows(len(texts), full + orphans)
        for i, text in enumerate(texts):
            if i >= full:  # registre orphelin saisi en 16 bits
                r = parse_int(text, 16, opts.radix, opts.signed)
                regs.append(swap_bytes(r) if opts.byte_swap else r)
                continue
            if mode.is_float and opts.radix is Radix.DEC:
                fmt = _float_fmt(mode)
                value = int.from_bytes(struct.pack(fmt, float(text.strip().replace(",", "."))), "big")
            else:
                value = parse_int(text, bits, opts.radix, opts.signed and not mode.is_float)
            regs.extend(uint_to_regs(value, words, order))
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
