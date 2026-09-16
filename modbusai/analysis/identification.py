"""Décodage des réponses d'identification : FC43/14 (Read Device Identification) et FC17."""

from __future__ import annotations

from dataclasses import dataclass, field

DEVICE_ID_OBJECTS = {
    0x00: "Fabricant",
    0x01: "Code produit",
    0x02: "Révision",
    0x03: "URL fabricant",
    0x04: "Nom produit",
    0x05: "Modèle",
    0x06: "Application",
}


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    objects: dict[int, str] = field(default_factory=dict)
    conformity: int | None = None
    more_follows: bool = False
    next_object: int = 0

    @property
    def vendor(self) -> str:
        return self.objects.get(0x00, "")

    @property
    def product(self) -> str:
        return self.objects.get(0x01, "") or self.objects.get(0x04, "")

    @property
    def revision(self) -> str:
        return self.objects.get(0x02, "")

    def summary(self) -> str:
        parts = [p for p in (self.vendor, self.product, self.revision) if p]
        return " / ".join(parts) if parts else "-"


def decode_device_id(body: bytes) -> DeviceIdentity:
    """``body`` = corps de la réponse FC43 à partir du type MEI (0x0E)."""
    if len(body) < 6 or body[0] != 0x0E:
        raise ValueError("Réponse FC43 invalide")
    conformity = body[2]
    more = body[3] == 0xFF
    next_obj = body[4]
    count = body[5]
    objects: dict[int, str] = {}
    pos = 6
    for _ in range(count):
        if pos + 2 > len(body):
            break
        obj_id, length = body[pos], body[pos + 1]
        raw = body[pos + 2 : pos + 2 + length]
        objects[obj_id] = raw.decode("ascii", errors="replace").strip("\x00 ")
        pos += 2 + length
    return DeviceIdentity(objects, conformity, more, next_obj)


def decode_report_slave_id(body: bytes) -> str:
    """FC17 : contenu propre au constructeur. On rend l'identifiant en hexa et,
    s'il est imprimable, en texte, avec l'indicateur de marche (octet 2)."""
    if not body:
        return "-"
    slave_id = body[0]
    run = None
    if len(body) >= 2:
        run = body[1] == 0xFF
    extra = body[2:]
    text = (
        extra.decode("ascii", errors="replace")
        if extra and all(32 <= b < 127 for b in extra)
        else extra.hex(" ").upper()
    )
    parts = [f"ID 0x{slave_id:02X}"]
    if run is not None:
        parts.append("en marche" if run else "arrêté")
    if text:
        parts.append(text)
    return ", ".join(parts)
