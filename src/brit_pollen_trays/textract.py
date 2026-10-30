"""Run AWS Textract on images, caching raw responses as JSON.

Uses the synchronous DetectDocumentText API, which accepts JPEG/PNG up to 10 MB.
Larger or TIFF images are converted to JPEG (and downscaled if needed) first.
Responses are cached per image so each image is billed once.
Credentials come from the standard AWS chain (env vars, ~/.aws, SSO).
"""
import argparse
import io
import json
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import NoCredentialsError, TokenRetrievalError, UnauthorizedSSOTokenError
from PIL import Image, ImageOps
from tqdm import tqdm

MAX_BYTES = 10 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def image_bytes(path: Path, rotate_cw: int = 0) -> bytes:
    """Return upright JPEG/PNG bytes under the Textract size limit.

    Our images are stored rotated 180 degrees with an EXIF orientation tag, and
    Textract does not reliably honour it, so we always bake the rotation in.
    rotate_cw rotates further by 0/90/180/270 degrees clockwise: the sticker IDs are
    printed vertically and read far better after a 90 degree rotation.
    """
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if rotate_cw:
            im = im.rotate(-rotate_cw, expand=True)
        quality = 95
        while True:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
            if buf.tell() <= MAX_BYTES:
                return buf.getvalue()
            if quality > 70:
                quality -= 10
            else:
                im = im.resize((int(im.width * 0.8), int(im.height * 0.8)))


def detect_text(client, path: Path, rotate_cw: int = 0) -> dict:
    return client.detect_document_text(Document={"Bytes": image_bytes(path, rotate_cw)})


def cache_path(out: Path, root: Path, path: Path, rotate_cw: int) -> Path:
    """Upright responses keep the plain name; rotated ones get a .cwNN suffix."""
    name = path.relative_to(root).as_posix().replace("/", "__")
    return out / (name + (f".cw{rotate_cw}" if rotate_cw else "") + ".json")


def lines(response: dict) -> list[dict]:
    """Extract LINE blocks with text, confidence, bounding box, and handwriting flag.

    Textract reports TextType on WORD blocks only, so a line counts as handwriting
    if any of its words does.
    """
    blocks = {b["Id"]: b for b in response["Blocks"]}
    out = []
    for b in response["Blocks"]:
        if b["BlockType"] != "LINE":
            continue
        word_ids = [i for r in b.get("Relationships", []) if r["Type"] == "CHILD" for i in r["Ids"]]
        hw = any(blocks[i].get("TextType") == "HANDWRITING" for i in word_ids)
        out.append({
            "text": b["Text"],
            "confidence": b["Confidence"],
            "bbox": b["Geometry"]["BoundingBox"],
            "handwriting": hw,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/interim/textract"))
    ap.add_argument("--profile", default=None, help="AWS profile (default: from environment)")
    ap.add_argument("--region", default=None, help="AWS region (default: from AWS config)")
    ap.add_argument("--rotations", type=int, nargs="+", default=[0, 90],
                    help="Clockwise rotations to run, one pass each (default: 0 90)")
    ap.add_argument("--limit", type=int, default=None, help="Process at most N new pages")
    args = ap.parse_args()

    cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"})
    session = boto3.Session(profile_name=args.profile)
    client = session.client("textract", region_name=args.region, config=cfg)
    files = sorted(p for p in args.root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    args.out.mkdir(parents=True, exist_ok=True)

    todo = [(p, r) for r in args.rotations for p in files
            if not cache_path(args.out, args.root, p, r).exists()]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(f"{len(todo)} pages to process ({len(files) * len(args.rotations)} total)", flush=True)

    done = 0
    try:
        for p, r in tqdm(todo, desc="Textract"):
            resp = detect_text(client, p, r)
            cache_path(args.out, args.root, p, r).write_text(json.dumps(resp))
            done += 1
    except (TokenRetrievalError, UnauthorizedSSOTokenError, NoCredentialsError) as e:
        print(f"\nAuth failed after {done} pages ({type(e).__name__}); re-login and rerun to resume.")
        raise SystemExit(1)
    print(f"Processed {done} new pages")


if __name__ == "__main__":
    main()
