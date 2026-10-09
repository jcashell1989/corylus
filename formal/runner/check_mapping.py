"""Check the public design vocabulary and row index against the Lean source."""

import csv
import re
from pathlib import Path


def camel(name: str) -> str:
    first, *rest = re.split(r"[_.]", name)
    return first + "".join(word.capitalize() for word in rest)


def constructors(source: str, name: str) -> set[str]:
    body = source.split(f"inductive {name} where", 1)[1].split("deriving", 1)[0]
    return set(re.findall(r"\|\s*(\w+)", body))


def main() -> None:
    project = Path(__file__).resolve().parent
    design = (project.parent.parent / "docs/runner-design.md").read_text()
    section = design.split("### 5.1 Durable state and recovery", 1)[1].split(
        "### 5.2", 1
    )[0]
    state_table, transitions = section.split(
        "| From-state | Event | Guard | To-state | Effect |", 1
    )
    phases = re.findall(r"^\| `([a-z_]+)` \|", state_table, re.MULTILINE)
    expected_rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in transitions.splitlines()
        if line.startswith("|") and "---" not in line
    ]
    events = {event.strip() for row in expected_rows for event in row[1].split(" / ")}
    source = (project / "Runner/Model.lean").read_text()
    assert constructors(source, "Phase") == {camel(name) for name in phases}
    assert constructors(source, "EventKind") == {camel(name) for name in events}
    with (project / "rows.tsv").open(newline="") as stream:
        actual_rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(actual_rows) == len(expected_rows) == 130
    for index, (actual, expected) in enumerate(zip(actual_rows, expected_rows), 1):
        assert actual["row"] == f"R{index:03}"
        assert [actual[key] for key in ("from", "event", "guard", "to")] == expected[:4]

    # Expand shared branch references; exclude the introductory full-table range.
    implementation = source.split("def rowStep", 1)[1].split("def step", 1)[0]
    referenced = set()
    for first, last in re.findall(r"R(\d{3})(?:[–-]R(\d{3}))?", implementation):
        referenced.update(range(int(first), int(last or first) + 1))
    assert referenced == set(range(1, 131))
    print(
        "PASS: 32 phases, 53 events, 130 exact design rows and implementation references"
    )


if __name__ == "__main__":
    main()
