"""Install the synthetic inspector demo without replacing local captures."""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/demo"


def prepare(destination: Path) -> bool:
    """Return False if a catalog exists; refuse any other nonempty destination."""
    if (destination / "catalog.json").exists():
        return False
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("Data directory is not empty; local files were left unchanged")
    # Exclusive writes protect existing files, including if another process starts
    # preparing data after the directory check. Write the catalog last.
    for name in ("synthetic-library.json", "catalog.json"):
        with (destination / name).open("xb") as output:
            output.write((SOURCE / name).read_bytes())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "inspector/data")
    args = parser.parse_args()
    try:
        installed = prepare(args.destination)
    except FileExistsError as error:
        parser.exit(1, f"{error}\n")
    print("Synthetic demo installed." if installed else "Existing catalog retained; no files changed.")


if __name__ == "__main__":
    main()
