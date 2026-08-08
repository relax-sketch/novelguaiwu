from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Iterable


def export_txt(work_directories: Iterable[str | Path], destination: str | Path) -> Path:
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as output:
        for directory in work_directories:
            base = Path(directory); paths = [base / "clean.txt"] + [p for p in base.glob("*.txt") if p.name != "clean.txt"]
            path = next((p for p in paths if p.exists()), None)
            if path: output.write(path.read_text(encoding="utf-8")); output.write("\n\n")
    return target


def export_zip(work_directories: Iterable[str | Path], destination: str | Path) -> Path:
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in work_directories:
            base = Path(directory); paths = [base / "clean.txt"] + [p for p in base.glob("*.txt") if p.name != "clean.txt"]
            path = next((p for p in paths if p.exists()), None)
            if path: archive.write(path, arcname=path.parent.name + "/" + path.name)
    return target
