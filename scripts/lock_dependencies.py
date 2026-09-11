"""Capture the tested environment's dependency closure and license metadata."""

from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement

roots = [
    "greenlet",
    "fastapi",
    "uvicorn",
    "httpx",
    "typer",
    "sqlalchemy",
    "alembic",
    "fsrs",
    "textual",
    "pydantic",
    "openai",
    "twilio",
    "python-multipart",
]


def closure(names):
    found = {}

    def visit(name, extras=()):
        d = distribution(name)
        key = d.metadata["Name"].lower().replace("_", "-")
        if key in found and not extras:
            return
        found[key] = d
        for raw in d.requires or []:
            r = Requirement(raw)
            if r.marker is None or any(r.marker.evaluate({"extra": ex}) for ex in ["", *extras]):
                visit(r.name, r.extras)

    for name in names:
        visit(name)
    return found


runtime = closure(roots)
dev = closure(roots + ["pytest", "pytest-asyncio", "ruff", "setuptools", "wheel"])
for filename, packages in [("requirements.lock", runtime), ("requirements-dev.lock", dev)]:
    Path(filename).write_text(
        "# Tested on Python 3.12, macOS arm64; exact dependency closure.\n"
        + "".join(f"{n}=={d.version}\n" for n, d in sorted(packages.items()))
    )
lines = [
    "# Third-party notices\n",
    "Versions captured from the tested environment. Original implementation; no Anki code or assets.\n",
    "| Package | Version | Declared license |",
    "|---|---|---|",
]
license_sections = []
for name, d in sorted(dev.items()):
    license = (
        d.metadata.get("License-Expression")
        or d.metadata.get("License")
        or ", ".join(
            x.split(" :: ")[-1]
            for x in d.metadata.get_all("Classifier", [])
            if x.startswith("License ::")
        )
        or "See bundled license below"
    )
    lines.append(f"| {name} | {d.version} | {license.splitlines()[0][:140]} |")
    for f in d.files or []:
        if any(
            part.lower().startswith(("license", "copying", "notice")) for part in f.parts
        ) and "dist-info" in str(f):
            p = Path(d.locate_file(f))
            if p.is_file():
                license_sections.extend(
                    [f"\n## {name}: {p.name}\n", "```text", p.read_text(errors="replace"), "```"]
                )
Path("THIRD_PARTY_NOTICES.md").write_text("\n".join(lines + license_sections) + "\n")
