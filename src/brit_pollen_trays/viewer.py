"""Build a static HTML page for checking slot labels against the images.

For every row of slots.csv this saves a crop of the slide (from the full-resolution
upright image) with the estimated slide window drawn on it, and writes an index.html
that shows each crop beside its sticker ID and OCR label text. Filters pick out the
cases most likely to be wrong, and reviewers can mark rows and type corrections, which
are kept in the browser and can be exported as CSV (a starting point for a validation set).

Everything is written under data/processed/viewer/ (not tracked in git). Open index.html
in a browser; no server is needed.
"""
import argparse
import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageOps
from tqdm import tqdm

from .slots import ROW_BAND

CROP_W = 720          # saved crop width in pixels
MARGIN = 0.25         # extra context on each side of the slide window, as a fraction of its width
BAND_PAD = 0.006      # extra vertical context beyond the row band (normalised)


def crop_slot(im: Image.Image, row: pd.Series) -> Image.Image:
    # TODO: crops use a fixed band and the estimated slide window; see idea 9 in docs/ocr-process.md.
    W, H = im.size
    x0 = (row.id_x + row.slide_offset) * W
    w = row.slide_width * W
    cx0, cx1 = max(x0 - MARGIN * w, 0), min(x0 + w * (1 + MARGIN), W)
    cy0, cy1 = max((row.id_y - ROW_BAND - BAND_PAD) * H, 0), min((row.id_y + ROW_BAND + BAND_PAD) * H, H)
    c = im.crop((int(cx0), int(cy0), int(cx1), int(cy1)))
    s = CROP_W / c.width
    c = c.resize((CROP_W, max(int(c.height * s), 1)), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    for x in (x0, x0 + w):                        # slide window edges
        d.line([((x - cx0) * s, 0), ((x - cx0) * s, c.height)], fill=(0, 200, 255), width=2)
    d.ellipse([(row.id_x * W - cx0) * s - 6, (row.id_y * H - cy0) * s - 6,
               (row.id_x * W - cx0) * s + 6, (row.id_y * H - cy0) * s + 6], outline=(255, 40, 40), width=3)
    return c


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", type=Path, default=Path("data/processed/slots.csv"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/processed/viewer"))
    ap.add_argument("--max-images", type=int, default=None, help="Only process the first N images (for testing)")
    args = ap.parse_args()

    s = pd.read_csv(args.slots)
    s["label_text"] = s["label_text"].fillna("")
    images = sorted(s.image.unique())[: args.max_images]
    s = s[s.image.isin(images)].copy()
    paths = {p.name: p for p in args.raw.rglob("*.JPG")}
    crops = args.out / "crops"
    crops.mkdir(parents=True, exist_ok=True)

    rows = []
    for img in tqdm(images, desc="Cropping"):
        with Image.open(paths[img]) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
        for r in s[s.image == img].itertuples():
            row = pd.Series(r._asdict())
            fn = f"{Path(img).stem}_{r.sticker_id}.jpg"
            crop_slot(im, row).save(crops / fn, quality=78)
            rows.append({
                "image": img, "session": r.session[:10], "tray": str(r.tray), "slot": int(r.slot_number),
                "id": str(r.sticker_id), "idc": float(r.id_conf),
                "hand": None if pd.isna(r.hand_number) else int(r.hand_number),
                "agree": None if pd.isna(r.hand_number_matches_id) else bool(r.hand_number_matches_id),
                "text": r.label_text, "hw": bool(r.label_has_handwriting), "pass": r.label_pass, "crop": f"crops/{fn}",
            })
    template = (Path(__file__).parent / "viewer_template.html").read_text()
    (args.out / "index.html").write_text(template.replace("/*__DATA__*/[]", json.dumps(rows)))
    print(f"Wrote {len(rows)} crops + {args.out / 'index.html'}")


if __name__ == "__main__":
    main()
