from pathlib import Path

source = Path("input.txt").read_text()
Path("output.txt").write_text(source.upper())
