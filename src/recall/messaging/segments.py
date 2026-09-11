"""GSM 03.38 and UTF-16 segment estimates; provider counts retained separately."""

import math

GSM = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
EXT = set("^{}\\[~]|€\f")


def estimate(body, toll_free=False):
    if all(c in GSM or c in EXT for c in body):
        units = sum(2 if c in EXT else 1 for c in body)
        return "GSM-7", 0 if not units else 1 if units <= 160 else math.ceil(
            units / (152 if toll_free else 153)
        )
    units = len(body.encode("utf-16-be")) // 2
    return "UCS-2", 0 if not units else 1 if units <= 70 else math.ceil(
        units / (66 if toll_free else 67)
    )


def split_message(body, max_segments=2, toll_free=False):
    parts = []
    while body:
        end = len(body)
        while end and estimate(body[:end], toll_free)[1] > max_segments:
            end -= 1
        if not end:
            raise ValueError("Cannot fit message")
        if end < len(body):
            space = body.rfind(" ", 0, end)
            if space > end // 2:
                end = space
        parts.append(body[:end].rstrip())
        body = body[end:].lstrip()
    return parts
