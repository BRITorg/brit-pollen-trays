"""EXPERIMENT (did not work, kept for comparison): locate slide slots by tray registration.

Not part of the package and not used by the pipeline. This is the last of three
registration attempts (ECC, 2D template matching, then this 1D edge-profile version).
On the 129 images it gave 47 of 249 tray fits below its own reliability cutoff
(MIN_SCORE), and even higher-scoring fits were often 15-30 px off, so grid cropping was
replaced by anchoring on OCR'd sticker IDs. See docs/ocr-process.md. Run from the repo
root, since REFERENCE is a relative path into data/raw.

Original description:

Locate slide slots on a tray image.

The camera is fixed but each tray is placed by hand, so the two trays move
independently by tens of pixels. For each tray we find its left edge and vertical
offset by 1D normalised cross-correlation of edge profiles against a single-tray
reference image, then lay a fixed 2x10 slot grid (tray width and row pitch are
constant) at that position.

Coordinates are in a 1200x800 view of the *upright* image. All images carry EXIF
orientation 3 (stored rotated 180 degrees); OpenCV applies it on load, PIL does
not. A single-tray shot has its tray in the right-hand ("R") position.
"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REFERENCE = Path("data/raw/2019-07-16_cAdams_BRIT_Pollen/BRIT_2019-07-16_S3_01001.JPG")
REF_LEFT = 621                                   # left edge of the tray in REFERENCE

VIEW_W, VIEW_H = 1200, 800
TRAY_W = 470
COLS = {"A": (0.0, 0.5), "B": (0.5, 1.0)}        # fraction of tray width (A: slides 1-10, B: 11-20)
ROW_TOP, ROW_PITCH, N_ROWS = 22, 77, 10
SEARCH_Y = 35                                    # < half the row pitch, so rows cannot alias
L_WINDOW = (30, 230)                             # where the left tray's left edge can be
R_AFTER_L = (430, 650)                           # right tray's left edge, relative to left tray's
R_ALONE = (560, 700)                             # right tray's left edge when it is the only tray
MIN_SCORE = 0.3                                  # below this the fit is unreliable


@dataclass
class TrayFit:
    tray: str      # "L" or "R"
    left: float    # left edge in view pixels
    dy: float      # vertical offset from the reference rows, in view pixels
    score: float


def edge_maps(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """|d/dx| and |d/dy| of the upright image at view size."""
    im = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_2)
    g = cv2.cvtColor(cv2.resize(im, (VIEW_W, VIEW_H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (0, 0), 1.5).astype(np.float32)
    return np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0)), np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))


def _hp(v: np.ndarray) -> np.ndarray:
    """Remove slow trends so frame edges, not lighting, drive the match."""
    return (v - cv2.GaussianBlur(v.reshape(1, -1).astype(np.float32), (0, 0), 25).ravel()).astype(np.float32)


def _match(tmpl: np.ndarray, sig: np.ndarray, lo: int, hi: int) -> tuple[int, float]:
    """Start index in sig[lo:hi+len(tmpl)] where tmpl matches best, and its NCC."""
    lo = max(lo, 0)
    seg = sig[lo: min(hi + len(tmpl), len(sig))]
    res = cv2.matchTemplate(seg.reshape(1, -1), tmpl.reshape(1, -1), cv2.TM_CCOEFF_NORMED)
    _, score, _, (mx, _) = cv2.minMaxLoc(res)
    return lo + mx, float(score)


class Reference:
    def __init__(self, path: Path = REFERENCE):
        ex, ey = edge_maps(path)
        y0, y1 = ROW_TOP, ROW_TOP + N_ROWS * ROW_PITCH
        self.x = _hp(ex[y0:y1].mean(0))[REF_LEFT - 10: REF_LEFT + TRAY_W + 10]
        self.y = _hp(ey[:, REF_LEFT: REF_LEFT + TRAY_W].mean(1))[y0:y1]


def tray_present(path: Path, tray: str, thresh: float = 6.0) -> bool:
    """A tray position is occupied if it has texture; the blank backdrop is near-flat.

    Mean |Laplacian| is ~1-2.5 on blank positions and >=14 on occupied ones.
    """
    x0, x1 = (120, 570) if tray == "L" else (640, 1090)
    im = cv2.imread(str(path), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    k = im.shape[1] / VIEW_W
    roi = im[int(30 * k): int(780 * k), int(x0 * k): int(x1 * k)]
    return float(np.abs(cv2.Laplacian(roi, cv2.CV_32F)).mean()) > thresh


def _fit_y(ey: np.ndarray, left: int, ref: Reference) -> tuple[float, float]:
    prof = _hp(ey[:, left: left + TRAY_W].mean(1))
    start, score = _match(ref.y, prof, ROW_TOP - SEARCH_Y, ROW_TOP + SEARCH_Y)
    return float(start - ROW_TOP), score


def fit_image(path: Path, ref: Reference | None = None) -> list[TrayFit]:
    ref = ref or Reference()
    ex, ey = edge_maps(path)
    sig = _hp(ex[ROW_TOP: ROW_TOP + N_ROWS * ROW_PITCH].mean(0))
    fits = []
    has_l, has_r = tray_present(path, "L"), tray_present(path, "R")
    left_l = None
    if has_l:
        s, sc = _match(ref.x, sig, *L_WINDOW)
        left_l = s + 10
        dy, scy = _fit_y(ey, left_l, ref)
        fits.append(TrayFit("L", left_l, dy, min(sc, scy)))
    if has_r:
        lo, hi = (left_l + R_AFTER_L[0], left_l + R_AFTER_L[1]) if left_l is not None else R_ALONE
        s, sc = _match(ref.x, sig, lo, hi)
        dy, scy = _fit_y(ey, s + 10, ref)
        fits.append(TrayFit("R", s + 10, dy, min(sc, scy)))
    return fits


def slots(fits: list[TrayFit]) -> list[dict]:
    """Slot boxes (x0, y0, x1, y1 in view pixels) for each fitted tray."""
    out = []
    for f in fits:
        for col, (c0, c1) in COLS.items():
            for r in range(N_ROWS):
                out.append({
                    "tray": f.tray, "col": col, "row": r, "score": f.score,
                    "box": (f.left + c0 * TRAY_W, ROW_TOP + r * ROW_PITCH + f.dy,
                            f.left + c1 * TRAY_W, ROW_TOP + (r + 1) * ROW_PITCH + f.dy),
                })
    return out
