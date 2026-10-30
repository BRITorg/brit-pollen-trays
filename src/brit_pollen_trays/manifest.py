"""Build a CSV manifest of downloaded images (path, size, dimensions, checksum)."""
import argparse
import hashlib
from pathlib import Path

import pandas as pd
from PIL import Image
from tqdm import tqdm

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def build_manifest(root: Path) -> pd.DataFrame:
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    rows = []
    for p in tqdm(files, desc="Indexing"):
        row = {
            "path": str(p.relative_to(root)),
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }
        try:
            with Image.open(p) as im:
                row["width"], row["height"] = im.size
        except Exception as e:  # corrupt or unreadable image
            row["error"] = str(e)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/interim/manifest.csv"))
    args = ap.parse_args()
    df = build_manifest(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows to {args.out}")


if __name__ == "__main__":
    main()
