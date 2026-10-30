"""Build a per-slide table from cached Textract responses.

Two passes per image are combined:
  * upright pass: label text (typed/handwritten)
  * 90-degree CW pass: the printed sticker IDs, which are vertical in the upright image

Sticker IDs are the anchors. An ID is a tray prefix plus a two-digit slot number
01-20 (e.g. 72517 = tray 725, slot 17). Text elements are assigned to the nearest
anchor within the same row, so no tray registration is needed. All coordinates are
normalised to the upright image (0-1).
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROW_BAND = 0.045      # max vertical distance (normalised) from an anchor to a text element
MIN_TRAY_IDS = 8      # a prefix needs this many IDs in an image to count as a tray
ID_RE = re.compile(r"(?<!\d)(\d{5,6})(?!\d)")


def to_upright(bbox: dict, rotate_cw: int) -> tuple[float, float, float, float]:
    """Convert a Textract bbox in a CW-rotated image to (left, top, width, height) upright."""
    l, t, w, h = bbox["Left"], bbox["Top"], bbox["Width"], bbox["Height"]
    if rotate_cw == 0:
        return l, t, w, h
    if rotate_cw == 90:
        return t, 1 - (l + w), h, w
    raise ValueError(f"unsupported rotation {rotate_cw}")


def words(resp: dict, rotate_cw: int) -> list[dict]:
    out = []
    for b in resp["Blocks"]:
        if b["BlockType"] == "WORD":
            l, t, w, h = to_upright(b["Geometry"]["BoundingBox"], rotate_cw)
            out.append({"text": b["Text"], "conf": b["Confidence"], "cx": l + w / 2, "cy": t + h / 2,
                        "hw": b.get("TextType") == "HANDWRITING"})
    return out


def line_blocks(resp: dict, rotate_cw: int) -> list[dict]:
    blocks = {b["Id"]: b for b in resp["Blocks"]}
    out = []
    for b in resp["Blocks"]:
        if b["BlockType"] != "LINE":
            continue
        ids = [i for r in b.get("Relationships", []) if r["Type"] == "CHILD" for i in r["Ids"]]
        l, t, w, h = to_upright(b["Geometry"]["BoundingBox"], rotate_cw)
        out.append({"text": b["Text"], "conf": b["Confidence"], "cx": l + w / 2, "cy": t + h / 2,
                    "l": l, "r": l + w,
                    "hw": any(blocks[i].get("TextType") == "HANDWRITING" for i in ids)})
    return out


def find_anchors(passes: list[tuple[dict, int]]) -> list[dict]:
    """Sticker IDs from all passes; one anchor per distinct ID (highest confidence)."""
    cands = {}
    for resp, rot in passes:
        for w in words(resp, rot):
            m = ID_RE.fullmatch(re.sub(r"^\W+|\W+$", "", w["text"]))
            if not m:
                continue
            sid = m.group(1)
            if not 1 <= int(sid[-2:]) <= 20:
                continue
            # Slides often carry a pencilled copy of the ID beside the sticker; prefer the
            # printed instance, then the more confident read.
            if sid not in cands or (w["hw"], -w["conf"]) < (cands[sid]["hw"], -cands[sid]["conf"]):
                cands[sid] = {"sticker_id": sid, "tray": sid[:-2], "slot": int(sid[-2:]), **w}
    trays = pd.Series([c["tray"] for c in cands.values()]).value_counts()
    keep = set(trays[trays >= MIN_TRAY_IDS].index)
    return [c for c in cands.values() if c["tray"] in keep]


def slide_width(anchors: list[dict]) -> float:
    """Spacing between a row's slide-1-10 sticker and its slide-11-20 sticker, in the same tray."""
    by = {(a["tray"], a["slot"]): a for a in anchors}
    d = [by[(t, s + 10)]["cx"] - by[(t, s)]["cx"] for t, s in by if s <= 10 and (t, s + 10) in by]
    return float(pd.Series(d).median()) if d else 0.2


def slide_offset(anchors: list[dict], lines: list[dict], width: float) -> float:
    """Offset from a sticker's x to its slide's left edge: the one that fewest lines straddle.

    Slides are physically separate, so text almost never crosses a slide edge.
    """
    in_rows = [ln for ln in lines if any(abs(ln["cy"] - a["cy"]) < ROW_BAND for a in anchors)]
    best, best_cost = -width / 2, None
    for k in range(0, 101):
        off = -width + width * k / 100
        edges = {round(a["cx"] + off, 3) for a in anchors} | {round(a["cx"] + off + width, 3) for a in anchors}
        cost = sum(1 for ln in in_rows for e in edges if ln["l"] + 0.003 < e < ln["r"] - 0.003)
        if best_cost is None or cost < best_cost:
            best, best_cost = off, cost
    return best


def build_image(upright: dict, cw90: dict | None) -> list[dict]:
    passes = [(upright, 0)] + ([(cw90, 90)] if cw90 else [])
    anchors = find_anchors(passes)
    if not anchors:
        return []
    lines = {rot: line_blocks(resp, rot) for resp, rot in passes}
    # Slide geometry comes from the pass that read more text, since a pass can silently
    # drop part of an image (seen on one of three test images).
    ref_lines = max(lines.values(), key=len)
    width = slide_width(anchors)
    off = slide_offset(anchors, ref_lines, width)
    word_sets = {rot: words(resp, rot) for resp, rot in passes}

    def in_slide(el: dict, a: dict) -> bool:
        x0 = a["cx"] + off
        return abs(el["cy"] - a["cy"]) < ROW_BAND and x0 <= el["cx"] < x0 + width

    out = []
    for a in anchors:
        per_pass = {}
        for rot, ls in lines.items():
            mine = [ln for ln in ls if in_slide(ln, a) and not ID_RE.fullmatch(ln["text"].strip())]
            per_pass[rot] = mine
        # take the pass with more text for this slide (ties go to the upright pass)
        src = max(per_pass, key=lambda r: (sum(len(ln["text"]) for ln in per_pass[r]), -r))
        chosen = sorted(per_pass[src], key=lambda ln: (round(ln["cy"], 2), ln["cx"]))
        # hand-drawn numeral 1-20 read as its own word, from either pass
        nums = [w for ws in word_sets.values() for w in ws
                if in_slide(w, a) and re.fullmatch(r"\d{1,2}", w["text"]) and 1 <= int(w["text"]) <= 20]
        best = max(nums, key=lambda w: w["conf"]) if nums else None
        out.append({
            "tray": a["tray"], "slot_number": a["slot"], "sticker_id": a["sticker_id"],
            "id_x": round(a["cx"], 4), "id_y": round(a["cy"], 4), "id_conf": round(a["conf"], 1),
            "hand_number": int(best["text"]) if best else None,
            "hand_number_matches_id": (int(best["text"]) == a["slot"]) if best else None,
            "label_text": " | ".join(ln["text"] for ln in chosen),
            "label_has_handwriting": any(ln["hw"] for ln in chosen),
            "label_pass": f"cw{src}" if src else "upright",
            "slide_offset": round(off, 3), "slide_width": round(width, 3),
        })
    return sorted(out, key=lambda r: (r["tray"], r["slot_number"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=Path("data/interim/textract"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()

    slot_rows, img_rows = [], []
    for up in sorted(p for p in args.cache.glob("*.json") if ".cw" not in p.name):
        name = up.name[: -len(".json")]
        cw = args.cache / f"{name}.cw90.json"
        rows = build_image(json.loads(up.read_text()), json.loads(cw.read_text()) if cw.exists() else None)
        for r in rows:
            slot_rows.append({"image": name.split("__")[-1], "session": name.split("__")[0], **r})
        img_rows.append({"image": name.split("__")[-1], "has_cw90": cw.exists(), "n_slots": len(rows),
                         "n_trays": len({r["tray"] for r in rows})})
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(slot_rows).to_csv(args.out / "slots.csv", index=False)
    pd.DataFrame(img_rows).to_csv(args.out / "images_summary.csv", index=False)
    print(f"{len(slot_rows)} slots from {len(img_rows)} images -> {args.out}")


if __name__ == "__main__":
    main()
