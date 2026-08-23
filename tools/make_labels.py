#!/usr/bin/env python3
"""Create print-ready, privacy-safe QR labels for Cordyceps Lab v2.

QR payloads contain only the opaque scan token in the Contract-defined
``<base_url>/lab-scan?t=<token>`` URL.  Lab metadata is printed beside, never
encoded into, the QR code.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2
import qrcode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# Labels point at the Lab Data Service, NOT at Home Assistant directly.
# The LDS /s/<token> endpoint 302-redirects to whatever HA URL is currently
# configured. Printed QR codes are permanent, so they must not embed Home
# Assistant's own port -- HA 2026.8 makes that port user-editable, and any
# change would otherwise invalidate every label already stuck to a jar.
#
# PORT 8189, not 8099: 8099 is the default `ingress_port` for Home Assistant
# apps, so publishing it on the host collides with Zigbee2MQTT, SSH/Terminal and
# others. The container still listens on 8099; 8189 is the host mapping.
#
# THIS VALUE IS PERMANENT ONCE YOU PRINT. It is encoded in every QR code. If it
# has to change later, existing labels stop resolving and must be reprinted.
DEFAULT_BASE_URL = "http://homeassistant.local:8189"
# Set to "direct" to embed the HA dashboard URL instead (legacy, not advised).
DEFAULT_LINK_MODE = "redirect"
DEFAULT_DPI = 300
BATCH_RE = re.compile(r"^AC-\d{8}-\d{2}$")
JAR_RE = re.compile(r"^AC-\d{8}-\d{2}-J\d{3}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
PRESETS = {
    "a4_24up": {"cols": 3, "rows": 8, "label_w_mm": 63.5, "label_h_mm": 33.9},
    # Compact labels. The generator automatically increases QR size when
    # needed for decoding verification.
    "a4_65up_small": {"cols": 5, "rows": 13, "label_w_mm": 38.0, "label_h_mm": 21.2},
}


@dataclass(frozen=True)
class Layout:
    cols: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    padding_mm: float
    dpi: int = DEFAULT_DPI

    @property
    def page_w_px(self) -> int:
        return round(210 / 25.4 * self.dpi)

    @property
    def page_h_px(self) -> int:
        return round(297 / 25.4 * self.dpi)

    @property
    def label_w_px(self) -> int:
        return round(self.label_w_mm / 210 * self.page_w_px)

    @property
    def label_h_px(self) -> int:
        return round(self.label_h_mm / 297 * self.page_h_px)

    @property
    def padding_px(self) -> int:
        return max(1, round(self.padding_mm / 210 * self.page_w_px))

    @property
    def margin_x_px(self) -> int:
        used = self.cols * self.label_w_px
        if used > self.page_w_px:
            raise ValueError("Configured label columns are wider than A4.")
        return (self.page_w_px - used) // 2

    @property
    def margin_y_px(self) -> int:
        used = self.rows * self.label_h_px
        if used > self.page_h_px:
            raise ValueError("Configured label rows are taller than A4.")
        return (self.page_h_px - used) // 2

    @property
    def labels_per_sheet(self) -> int:
        return self.cols * self.rows


@dataclass
class LabelRecord:
    kind: str  # batch or jar
    batch_id: str
    scan_token: str
    jar_id: str | None = None
    strain: str = ""
    inoculation_date: str | None = None
    transfer_date: str | None = None


def _font_candidates(name: str) -> list[str]:
    base = "/usr/share/fonts/truetype/dejavu"
    return [
        f"{base}/{name}.ttf",
        f"{base}/{name.replace('-Bold', 'Bold')}.ttf",
        name + ".ttf",
    ]


def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in _font_candidates(name):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return int(draw.textbbox((0, 0), text, font=font)[2])


def text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(1, int(bbox[3] - bbox[1]))


def draw_text_top(
    draw: ImageDraw.ImageDraw,
    x: int,
    top_y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: Any = "black",
) -> None:
    """Draw text from a true top edge rather than Pillow's ascender baseline."""
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((x, top_y - bbox[1]), text, font=font, fill=fill)


def fitted_font(
    draw: ImageDraw.ImageDraw, text: str, font_name: str, max_size: int, max_width: int
) -> ImageFont.ImageFont:
    """Return the largest single-line font that fits; never wraps or overflows."""
    for size in range(max(4, max_size), 3, -1):
        font = get_font(font_name, size)
        if text_width(draw, text, font) <= max_width:
            return font
    return get_font(font_name, 4)


def date_or_blank(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "____________"
    return str(value).strip()[:10]


def clean_base_url(value: str) -> str:
    value = value.rstrip("/")
    for suffix in ("/lab-scan", "/s"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    if not value.startswith(("http://", "https://")):
        raise ValueError("--base-url must start with http:// or https://")
    return value


# Set once from the CLI in main(); read by payload_for.
LINK_MODE = DEFAULT_LINK_MODE


def payload_for(record: LabelRecord, base_url: str, link_mode: str | None = None) -> str:
    link_mode = link_mode or LINK_MODE
    if not TOKEN_RE.fullmatch(record.scan_token):
        raise ValueError(
            f"Invalid opaque scan token for {record.jar_id or record.batch_id}; "
            "Contract §1 requires a 22-character URL-safe base64 token."
        )
    base = clean_base_url(base_url)
    if link_mode == "redirect":
        # Stable indirection through the Lab Data Service.
        return f"{base}/s/{record.scan_token}"
    # Legacy direct-to-HA form. Breaks if the HA web server port ever changes.
    return f"{base}/lab-scan?t={record.scan_token}"


def make_qr(payload: str, box_size: int) -> Image.Image:
    # Q gives robust label-scanning margins while keeping compact payloads readable.
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((box_size, box_size), Image.Resampling.NEAREST)


def draw_cut_guides(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    """Thin perimeter lines serve as print cut guides without consuming label area."""
    draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(150, 150, 150), width=1)


def draw_label(
    page: Image.Image,
    layout: Layout,
    record: LabelRecord,
    x: int,
    y: int,
    qr_fraction: float,
    base_url: str,
) -> tuple[tuple[int, int, int, int], str]:
    draw = ImageDraw.Draw(page)
    w, h, pad = layout.label_w_px, layout.label_h_px, layout.padding_px
    draw_cut_guides(draw, x, y, w, h)
    payload = payload_for(record, base_url)

    # The batch banner remains a distinct marker but deliberately stays shallow
    # so the QR and information column retain nearly the entire label height.
    header_h = max(18, round(h * 0.060)) if record.kind == "batch" else 0
    if record.kind == "batch":
        draw.rectangle((x + 1, y + 1, x + w - 2, y + header_h), fill=(0, 77, 84))
        head_font = fitted_font(
            draw, "BATCH LABEL", "DejaVuSans-Bold", max(9, round(h * 0.055)), w - 2 * pad
        )
        draw.text((x + pad, y + 2), "BATCH LABEL", font=head_font, fill="white")

    usable_top = y + header_h + pad
    usable_bottom = y + h - pad
    usable_h = usable_bottom - usable_top

    # QR occupies 90% of its usable vertical track by default, while the
    # remaining 10% deliberately creates symmetrical white breathing room.
    qr_size = max(1, round(usable_h * qr_fraction))
    qr_x = x + pad
    qr_y = usable_top + (usable_h - qr_size) // 2
    qr = make_qr(payload, qr_size)
    page.paste(qr, (qr_x, qr_y))

    # The gutter is exactly the configured internal padding (2 mm by default).
    # This keeps the large QR visually separate from the full-height text column.
    text_x = qr_x + qr_size + pad
    text_w = x + w - pad - text_x
    if text_w < 50:
        raise RuntimeError("QR layout leaves too little room for the required text column.")

    # Sizes scale from the usable vertical track. At the default 24-up size,
    # the primary ID is ~7 pt rather than the former ~5 pt rendering.
    scale = usable_h / 352
    primary_size = max(10, round(32 * scale))
    secondary_size = max(8, round(22 * scale))
    body_size = max(8, round(21 * scale))
    detail_size = max(7, round(20 * scale))

    if record.kind == "jar" and record.jar_id:
        first_text = record.jar_id
        second_text = f"Batch: {record.batch_id}"
    else:
        first_text = record.batch_id
        second_text = "Master batch"

    lines = [
        (first_text, fitted_font(draw, first_text, "DejaVuSansMono-Bold", primary_size, text_w), "black"),
        (second_text, fitted_font(draw, second_text, "DejaVuSansMono-Bold", secondary_size, text_w), (45, 45, 45)),
    ]
    strain_text = f"Strain: {record.strain or '____________'}"
    inoc_text = f"Inoc: {date_or_blank(record.inoculation_date)}"
    transfer_text = f"Transfer: {date_or_blank(record.transfer_date)}"
    lines.extend(
        [
            (strain_text, fitted_font(draw, strain_text, "DejaVuSans", body_size, text_w), "black"),
            (inoc_text, fitted_font(draw, inoc_text, "DejaVuSans", detail_size, text_w), "black"),
            (transfer_text, fitted_font(draw, transfer_text, "DejaVuSans", detail_size, text_w), "black"),
        ]
    )

    # The writable box is anchored flush to the bottom of the text column.
    box_h = max(24, round(usable_h * 0.20))
    box_y = usable_bottom - box_h
    text_bottom = box_y - max(7, round(usable_h * 0.035))
    line_heights = [text_height(draw, line, font) for line, font, _fill in lines]
    available_line_space = text_bottom - usable_top
    if available_line_space < sum(line_heights):
        raise RuntimeError("Text lines cannot fit in the configured label geometry.")
    # Equal distributed whitespace makes the text block fill (rather than
    # cling to the top of) the full column above the operator field.
    line_gap = (available_line_space - sum(line_heights)) // max(1, len(lines) - 1)
    cursor_y = usable_top
    for index, (line, font, fill) in enumerate(lines):
        draw_text_top(draw, text_x, cursor_y, line, font, fill)
        cursor_y += line_heights[index]
        if index < len(lines) - 1:
            cursor_y += line_gap

    op_font = fitted_font(draw, "Op. initials", "DejaVuSans", detail_size, text_w - 6)
    draw.rectangle((text_x, box_y, x + w - pad, usable_bottom), outline=(50, 50, 50), width=1)
    draw_text_top(draw, text_x + 3, box_y + 3, "Op. initials", op_font, (35, 35, 35))
    # Ruled writing line: the label remains deliberately blank for the operator.
    rule_y = usable_bottom - max(5, round(box_h * 0.22))
    draw.line((text_x + 3, rule_y, x + w - pad - 3, rule_y), fill=(90, 90, 90), width=1)
    return (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), payload


def verify_rendered_qrs(page: Image.Image, checks: Iterable[tuple[tuple[int, int, int, int], str]]) -> None:
    detector = cv2.QRCodeDetector()
    for rect, expected in checks:
        crop = page.crop(rect)
        array = cv2.cvtColor(__import__("numpy").array(crop), cv2.COLOR_RGB2BGR)
        decoded, _points, _straight = detector.detectAndDecode(array)
        if decoded != expected:
            raise RuntimeError(
                f"QR verification failed (expected {expected!r}, decoded {decoded!r})."
            )


def render_sheet(
    records: list[LabelRecord], layout: Layout, base_url: str, qr_fraction: float
) -> Image.Image:
    page = Image.new("RGB", (layout.page_w_px, layout.page_h_px), "white")
    # Draw the full preset grid, including intentionally unused labels on a
    # partial final sheet, so each physical label position has a cut guide.
    guide_draw = ImageDraw.Draw(page)
    for index in range(layout.labels_per_sheet):
        col, row = index % layout.cols, index // layout.cols
        x = layout.margin_x_px + col * layout.label_w_px
        y = layout.margin_y_px + row * layout.label_h_px
        draw_cut_guides(guide_draw, x, y, layout.label_w_px, layout.label_h_px)
    checks: list[tuple[tuple[int, int, int, int], str]] = []
    for index, record in enumerate(records):
        col, row = index % layout.cols, index // layout.cols
        x = layout.margin_x_px + col * layout.label_w_px
        y = layout.margin_y_px + row * layout.label_h_px
        checks.append(draw_label(page, layout, record, x, y, qr_fraction, base_url))
    verify_rendered_qrs(page, checks)
    return page


def safe_key(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) not in (None, ""):
            return item[key]
    return None


def records_from_data(data: Any) -> tuple[LabelRecord, list[LabelRecord]]:
    """Accept a list of jar records or a {batch:..., jars:[...]} JSON structure."""
    if isinstance(data, dict):
        batch = data.get("batch", data)
        jars = data.get("jars", batch.get("jars", []))
        if not isinstance(batch, dict):
            raise ValueError("The JSON 'batch' value must be an object.")
    elif isinstance(data, list):
        jars = data
        if not jars:
            raise ValueError("Input contains no jar records.")
        batch = jars[0]
    else:
        raise ValueError("Input must be a JSON object or a list of jar records.")
    if not isinstance(jars, list):
        raise ValueError("The JSON 'jars' value must be a list.")

    batch_id = safe_key(batch, "batch_id", "Batch ID")
    if not batch_id and jars:
        batch_id = safe_key(jars[0], "batch_id", "Batch ID")
    if not batch_id or not BATCH_RE.fullmatch(str(batch_id)):
        raise ValueError("Contract §1 requires a valid Batch ID (AC-YYYYMMDD-NN).")
    batch_token = safe_key(batch, "batch_scan_token", "scan_token", "token")
    if not batch_token and jars:
        batch_token = safe_key(jars[0], "batch_scan_token", "batch_token")
    if not batch_token:
        raise ValueError("Offline input must include a batch scan_token or batch_scan_token.")

    shared = {
        "batch_id": str(batch_id),
        "strain": str(safe_key(batch, "strain", "Strain") or ""),
        "inoculation_date": safe_key(batch, "inoculation_date", "inoculation_ts", "inoc_date"),
        "transfer_date": safe_key(batch, "transfer_date", "transfer_ts", "transfer_date"),
    }
    batch_record = LabelRecord(kind="batch", scan_token=str(batch_token), **shared)
    jar_records: list[LabelRecord] = []
    for raw in jars:
        if not isinstance(raw, dict):
            raise ValueError("Every jar record must be a JSON object.")
        jar_id = safe_key(raw, "jar_id", "Jar ID")
        if not jar_id or not JAR_RE.fullmatch(str(jar_id)):
            raise ValueError(f"Contract §1 requires a valid Jar ID; received {jar_id!r}.")
        if not str(jar_id).startswith(str(batch_id) + "-"):
            raise ValueError(f"Jar {jar_id} does not belong to batch {batch_id}.")
        token = safe_key(raw, "scan_token", "jar_scan_token", "token")
        if not token:
            raise ValueError(f"Jar {jar_id} has no scan_token.")
        jar_records.append(
            LabelRecord(
                kind="jar",
                batch_id=str(batch_id),
                jar_id=str(jar_id),
                scan_token=str(token),
                strain=str(safe_key(raw, "strain", "Strain") or shared["strain"]),
                inoculation_date=safe_key(raw, "inoculation_date", "inoculation_ts", "inoc_date")
                or shared["inoculation_date"],
                transfer_date=safe_key(raw, "transfer_date", "transfer_ts") or shared["transfer_date"],
            )
        )
    return batch_record, sorted(jar_records, key=lambda r: r.jar_id or "")


def read_offline_input(path: Path) -> tuple[LabelRecord, list[LabelRecord]]:
    if path.suffix.lower() == ".json":
        return records_from_data(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return records_from_data(list(csv.DictReader(handle)))
    raise ValueError("--input must be a .json or .csv file.")


def event_date(events: list[dict[str, Any]], wanted_stages: set[str], wanted_actions: set[str]) -> str | None:
    candidates = [
        str(e.get("ts"))[:10]
        for e in events
        if e.get("to_stage") in wanted_stages or e.get("action") in wanted_actions
    ]
    return min(candidates) if candidates else None


def fetch_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LDS request failed: HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LDS request failed: {exc.reason}") from exc


def read_lds(lds_url: str, token: str, batch_id: str) -> tuple[LabelRecord, list[LabelRecord]]:
    if not BATCH_RE.fullmatch(batch_id):
        raise ValueError("Contract §1 requires --batch AC-YYYYMMDD-NN.")
    root = lds_url.rstrip("/")
    detail = fetch_json(f"{root}/batches/{batch_id}", token)
    timeline = fetch_json(f"{root}/batches/{batch_id}/timeline", token)
    batch = detail.get("batch", detail)
    jars = detail.get("jars", [])
    if not jars and isinstance(timeline, dict):
        jars = timeline.get("jars", [])
    events = timeline.get("events", []) if isinstance(timeline, dict) else []
    if not jars:
        raise RuntimeError("LDS response did not include jars for the requested batch.")
    batch = dict(batch)
    batch["inoculation_date"] = event_date(events, {"inoculated"}, {"inoculation"})
    batch["transfer_date"] = event_date(events, {"transferred_to_light"}, {"transfer_dark_to_light"})
    batch["jars"] = []
    for jar in jars:
        combined = dict(jar)
        combined.setdefault("batch_id", batch_id)
        combined.setdefault("strain", batch.get("strain"))
        combined["inoculation_date"] = batch["inoculation_date"]
        combined["transfer_date"] = batch["transfer_date"]
        batch["jars"].append(combined)
    return records_from_data({"batch": batch, "jars": batch["jars"]})


def write_pdf(pdf_path: Path, sheets: list[Image.Image]) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = canvas.Canvas(str(pdf_path), pagesize=A4)
    document.setTitle("Cordyceps Lab v2 QR Label Sheets")
    document.setAuthor("Perplexity Computer")
    page_w, page_h = A4
    for sheet in sheets:
        document.drawImage(ImageReader(sheet), 0, 0, width=page_w, height=page_h)
        document.showPage()
    document.save()


def write_pngs(pdf_path: Path, sheets: list[Image.Image], dpi: int) -> list[Path]:
    outputs: list[Path] = []
    for index, sheet in enumerate(sheets, start=1):
        sheet_path = pdf_path.with_name(f"{pdf_path.stem}_sheet_{index:02d}.png")
        sheet.save(sheet_path, dpi=(dpi, dpi))
        outputs.append(sheet_path)
    # Convenience copy gives a stable .png sibling for one-page print jobs.
    if len(sheets) == 1:
        sibling = pdf_path.with_suffix(".png")
        if sibling != outputs[0]:
            shutil.copyfile(outputs[0], sibling)
            outputs.append(sibling)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Offline .json or .csv jar-record file")
    source.add_argument("--lds", help="LDS base URL, for example http://host:8189")
    parser.add_argument("--token", help="LDS bearer token (required with --lds)")
    parser.add_argument("--batch", help="Batch ID (required with --lds)")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"HA base URL for QR payloads (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--output", type=Path, required=True, help="Destination PDF path")
    parser.add_argument(
        "--link-mode",
        choices=("redirect", "direct"),
        default=DEFAULT_LINK_MODE,
        help=("'redirect' (default) encodes <base>/s/<token> and lets the Lab Data "
              "Service forward to Home Assistant, so printed labels survive an HA "
              "port or hostname change. 'direct' encodes <base>/lab-scan?t=<token>."),
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), default="a4_24up")
    parser.add_argument("--cols", type=int, help="Override preset column count")
    parser.add_argument("--rows", type=int, help="Override preset row count")
    parser.add_argument("--label-width-mm", type=float, help="Override label width")
    parser.add_argument("--label-height-mm", type=float, help="Override label height")
    parser.add_argument("--padding-mm", type=float, default=2.0, help="Internal padding (default: 2)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="PNG resolution (default: 300)")
    return parser.parse_args()


def main() -> int:
    global LINK_MODE
    args = parse_args()
    if bool(args.lds) != bool(args.token) or bool(args.lds) != bool(args.batch):
        raise SystemExit("--lds requires both --token and --batch.")
    LINK_MODE = args.link_mode
    preset = PRESETS[args.preset]
    layout = Layout(
        cols=args.cols or preset["cols"],
        rows=args.rows or preset["rows"],
        label_w_mm=args.label_width_mm or preset["label_w_mm"],
        label_h_mm=args.label_height_mm or preset["label_h_mm"],
        padding_mm=args.padding_mm,
        dpi=args.dpi,
    )
    if layout.cols < 1 or layout.rows < 1 or layout.padding_mm <= 0:
        raise SystemExit("Rows, columns, and padding must be positive.")
    if layout.labels_per_sheet < 2:
        raise SystemExit("At least two label positions are needed: batch label plus jar label.")

    batch, jars = read_lds(args.lds, args.token, args.batch) if args.lds else read_offline_input(args.input)
    jars_per_sheet = layout.labels_per_sheet - 1
    record_sheets = [
        [batch] + jars[start : start + jars_per_sheet]
        for start in range(0, len(jars), jars_per_sheet)
    ] or [[batch]]

    sheets: list[Image.Image] | None = None
    last_error: Exception | None = None
    # The primary render uses 90% of usable height. If a device/decoder cannot
    # read the output, use progressively larger QR tracks before failing.
    for qr_fraction in (0.90, 0.92, 0.94):
        try:
            sheets = [render_sheet(sheet, layout, args.base_url, qr_fraction) for sheet in record_sheets]
            break
        except RuntimeError as exc:
            last_error = exc
    if sheets is None:
        raise RuntimeError(f"QR verification did not pass after rerendering: {last_error}")

    write_pdf(args.output, sheets)
    pngs = write_pngs(args.output, sheets, layout.dpi)
    print(f"Created {args.output} ({len(sheets)} A4 sheet(s), {layout.dpi} DPI PNG equivalent).")
    for png in pngs:
        print(f"Created {png}")
    print("QR payloads were decoded from the rendered sheets and verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
