import re
from dataclasses import dataclass

CONTROLS = {"STOP", "START", "HELP", "PAUSE", "RESUME", "MORE"}


@dataclass
class Parsed:
    code: str | None = None
    command: str | None = None
    ordinal: int | None = None
    rating: int | None = None
    answers: dict | None = None
    bare: str | None = None


def parse(body):
    body = body.strip()
    if body.upper() in CONTROLS:
        return Parsed(command=body.upper())
    if re.match(r"^(add|learn|remember)\b", body, re.I):
        return Parsed(command="ASSISTANT", bare=body)
    match = re.fullmatch(r"([A-Za-z0-9]{2,8})\s*[:,-]?\s+(.+)", body, re.S)
    if not match:
        return Parsed(command="ASSISTANT", bare=body)
    code, rest = match.group(1).upper(), match.group(2).strip()
    if rest.upper() == "DONE":
        return Parsed(code=code, command="DONE")
    cmd = re.fullmatch(
        r"(SKIP|SHOW|EXPLAIN|RATE)\s+(\d+)(?:\s+(AGAIN|HARD|GOOD|EASY))?", rest, re.I
    )
    if cmd:
        command, ordinal, rating = cmd.groups()
        if command.upper() == "RATE" and rating is None:
            raise ValueError("RATE needs AGAIN, HARD, GOOD or EASY")
        return Parsed(
            code=code,
            command=command.upper(),
            ordinal=int(ordinal),
            rating=["AGAIN", "HARD", "GOOD", "EASY"].index(rating.upper()) + 1 if rating else None,
        )
    matches = list(re.finditer(r"(?:^|[;\n]\s*|\s+)(\d+)\s*[).:]\s*", rest))
    if not matches:
        return Parsed(code=code, bare=rest)
    if rest[: matches[0].start()].strip():
        raise ValueError("Use numbered answers after the code")
    answers = {}
    for index, m in enumerate(matches):
        n = int(m.group(1))
        answer = rest[
            m.end() : matches[index + 1].start() if index + 1 < len(matches) else len(rest)
        ].strip(" ;\n")
        if n in answers or not answer:
            raise ValueError("Use each item number once with a nonempty answer")
        answers[n] = answer
    return Parsed(code=code, answers=answers)
