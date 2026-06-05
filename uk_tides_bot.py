"""
UK Daily Tides Instagram Bot
==============================
Data source : Environment Agency Tide Gauge API (FREE, no key required)
              https://environment.data.gov.uk/flood-monitoring/doc/tidegauge
Image lib   : Pillow  (pip install Pillow)
Instagram   : instagrapi  (pip install instagrapi)

HOW TO RUN DAILY FOR FREE
--------------------------
Option A – GitHub Actions (recommended, completely free):
  1. Push this file to a private GitHub repo
  2. Add your Instagram credentials as GitHub Secrets:
       INSTA_USERNAME  and  INSTA_PASSWORD
  3. Create .github/workflows/daily_post.yml  (template at bottom of file)

Option B – Local cron job (Linux/Mac):
  Run:  crontab -e
  Add:  0 7 * * * /usr/bin/python3 /path/to/uk_tides_bot.py

Option C – Free cloud (Render.com or Railway.app free tier):
  Deploy as a cron job service.

INSTAGRAM NOTE
--------------
instagrapi works but Instagram can flag automated logins.
Reduce risk by:
  - Running from the same IP each time
  - Not posting more than once a day
  - Using a dedicated account (not your personal one)
"""

import os
import math
import requests
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
INSTA_USERNAME = "bouy_oh_bouy"
INSTA_PASSWORD = "Flossy19!"

# Environment Agency station IDs → label and rough map position on a 1080x1080 canvas
# Positions are (x, y) — tweak to match your map template
# Full station list: https://environment.data.gov.uk/flood-monitoring/id/stations?type=TideGauge
STATIONS = {
    "E72637": {"name": "Aberdeen",   "xy": (700, 130)},
    "E72660": {"name": "Liverpool",  "xy": (370, 440)},
    "E70186": {"name": "Cardiff",    "xy": (340, 620)},
    "E72639": {"name": "Avonmouth", "xy": (310, 660)},
    "E72642": {"name": "Portsmouth", "xy": (700, 720)},
    "E72641": {"name": "Bournemouth","xy": (620, 750)},
    "E72649": {"name": "Barmouth",   "xy": (270, 490)},
    "E72651": {"name": "Heysham",    "xy": (390, 380)},
    "E72658": {"name": "Whitby",     "xy": (680, 330)},
    "E72656": {"name": "Immingham",  "xy": (720, 430)},
}

EA_BASE = "https://environment.data.gov.uk/flood-monitoring"

# ─── DATA FETCHING ────────────────────────────────────────────────────────────

def get_station_label(station_id: str) -> str:
    """Returns the human-readable name from the EA API as a fallback."""
    try:
        r = requests.get(f"{EA_BASE}/id/stations/{station_id}", timeout=10)
        if r.status_code == 200:
            return r.json()["items"].get("label", station_id)
    except Exception:
        pass
    return station_id


def get_tide_readings(station_id: str) -> dict:
    """
    Fetches today's tidal readings for a station from the EA API.
    Returns a dict with 'latest_level', 'trend', and 'today_readings'.
    """
    result = {"latest_level": None, "trend": "—", "today_readings": [], "error": False}
    try:
        # Get all of today's readings (sorted ascending)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = (
            f"{EA_BASE}/id/stations/{station_id}/readings"
            f"?date={today}&unitName=m&_sorted&_limit=200"
        )
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            result["error"] = True
            return result

        items = r.json().get("items", [])
        if not items:
            result["error"] = True
            return result

        # Extract numeric readings with timestamps
        readings = []
        for item in items:
            try:
                val = float(item["value"])
                ts = datetime.fromisoformat(item["dateTime"].replace("Z", "+00:00"))
                readings.append((ts, val))
            except (KeyError, ValueError):
                continue

        if not readings:
            result["error"] = True
            return result

        result["today_readings"] = readings

        # Latest level
        latest_ts, latest_val = readings[-1]
        result["latest_level"] = round(latest_val, 2)
        result["latest_time"] = latest_ts.strftime("%H:%M")

        # Simple trend: compare last reading to 30 mins ago
        if len(readings) >= 3:
            recent = readings[-1][1]
            earlier = readings[-3][1]
            if recent > earlier + 0.05:
                result["trend"] = "▲ Rising"
            elif recent < earlier - 0.05:
                result["trend"] = "▼ Falling"
            else:
                result["trend"] = "► Slack"

        # Estimate high/low from today's data using peak detection
        highs, lows = detect_peaks(readings)
        result["highs"] = highs
        result["lows"] = lows

    except Exception as e:
        print(f"  Error fetching {station_id}: {e}")
        result["error"] = True

    return result


def detect_peaks(readings: list) -> tuple:
    """Simple peak/trough detector on a list of (datetime, float) tuples."""
    highs, lows = [], []
    values = [v for _, v in readings]
    times = [t for t, _ in readings]

    window = 4  # look-around window (each reading = 15 min, so ±1 hour)
    for i in range(window, len(values) - window):
        segment = values[i - window: i + window + 1]
        if values[i] == max(segment) and values[i] > values[i - 1]:
            highs.append((times[i], values[i]))
        elif values[i] == min(segment) and values[i] < values[i - 1]:
            lows.append((times[i], values[i]))

    return highs, lows

# ─── IMAGE GENERATION ────────────────────────────────────────────────────────

CANVAS_SIZE = (1080, 1080)
BG_COLOR    = (10, 15, 25)       # dark navy
CARD_COLOR  = (20, 30, 48)       # slightly lighter card
CARD_BORDER = (0, 180, 140)      # teal accent
HIGH_COLOR  = (0, 200, 160)      # teal for high tide
LOW_COLOR   = (255, 120, 60)     # orange for low tide
TEXT_COLOR  = (220, 235, 255)    # near white
MUTED_COLOR = (120, 145, 175)    # muted blue-grey
TITLE_COLOR = (0, 210, 160)      # bright teal title


def load_font(size: int, bold: bool = False):
    """Loads a font — falls back to default if no TTF available."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def draw_mini_chart(draw: ImageDraw, readings: list, x: int, y: int, w: int, h: int):
    """Draws a small sparkline chart of today's tide readings."""
    if len(readings) < 4:
        return
    values = [v for _, v in readings]
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1

    pts = []
    for i, (_, v) in enumerate(readings):
        px = x + int((i / (len(readings) - 1)) * w)
        py = y + h - int(((v - mn) / rng) * h)
        pts.append((px, py))

    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=HIGH_COLOR, width=2)


def generate_image(tide_data: dict) -> str:
    """Builds the 1080×1080 Instagram graphic and saves it."""
    img = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Background grid lines (subtle)
    for y in range(0, 1080, 60):
        draw.line([(0, y), (1080, y)], fill=(20, 28, 42), width=1)

    # Title bar
    draw.rectangle([(0, 0), (1080, 110)], fill=(15, 22, 38))
    draw.line([(0, 110), (1080, 110)], fill=CARD_BORDER, width=2)

    font_title   = load_font(46, bold=True)
    font_sub     = load_font(22)
    font_station = load_font(19, bold=True)
    font_data    = load_font(16)
    font_small   = load_font(13)

    today_str = datetime.now().strftime("%A %d %B %Y")
    draw.text((40, 22), "🌊 UK TIDE TIMES", font=font_title, fill=TITLE_COLOR)
    draw.text((40, 78), today_str, font=font_sub, fill=MUTED_COLOR)

    # Watermark / attribution (required by open govt licence)
    attr = "Data: Environment Agency (Open Govt Licence)"
    draw.text((1080 - 10, 1070), attr, font=font_small, fill=(60, 80, 100), anchor="rb")

    # Layout: 2-column grid of station cards
    card_w, card_h = 480, 170
    margin_x, margin_y = 35, 125
    gap_x, gap_y = 30, 18
    cols = 2

    for idx, (station_id, info) in enumerate(tide_data.items()):
        col = idx % cols
        row = idx // cols
        cx = margin_x + col * (card_w + gap_x)
        cy = margin_y + row * (card_h + gap_y)

        # Card background
        draw.rectangle([(cx, cy), (cx + card_w, cy + card_h)], fill=CARD_COLOR)
        draw.rectangle([(cx, cy), (cx + card_w, cy + card_h)], outline=(35, 55, 80), width=1)
        draw.rectangle([(cx, cy), (cx + 4, cy + card_h)], fill=CARD_BORDER)  # left accent bar

        d = info["data"]
        name = info["name"]

        if d["error"]:
            draw.text((cx + 16, cy + 14), name, font=font_station, fill=TEXT_COLOR)
            draw.text((cx + 16, cy + 45), "Data unavailable", font=font_data, fill=MUTED_COLOR)
            continue

        # Station name + trend
        draw.text((cx + 16, cy + 12), name.upper(), font=font_station, fill=TEXT_COLOR)
        trend_color = HIGH_COLOR if "Rising" in d.get("trend","") else LOW_COLOR if "Falling" in d.get("trend","") else MUTED_COLOR
        draw.text((cx + card_w - 10, cy + 14), d.get("trend", ""), font=font_small, fill=trend_color, anchor="ra")

        # Current level
        level_txt = f"Now: {d['latest_level']}m  ({d.get('latest_time','')} UTC)"
        draw.text((cx + 16, cy + 40), level_txt, font=font_data, fill=MUTED_COLOR)

        # High tides
        highs = d.get("highs", [])
        y_off = 65
        if highs:
            draw.text((cx + 16, cy + y_off), "HIGH TIDES", font=font_small, fill=HIGH_COLOR)
            y_off += 18
            for ts, val in highs[:2]:
                draw.text((cx + 16, cy + y_off), f"  {ts.strftime('%H:%M')}  {val:.2f}m", font=font_data, fill=HIGH_COLOR)
                y_off += 18
        else:
            draw.text((cx + 16, cy + y_off), "High tide: not yet today", font=font_small, fill=MUTED_COLOR)
            y_off += 36

        # Low tides
        lows = d.get("lows", [])
        draw.text((cx + 16, cy + y_off), "LOW TIDES", font=font_small, fill=LOW_COLOR)
        y_off += 18
        if lows:
            for ts, val in lows[:2]:
                draw.text((cx + 16, cy + y_off), f"  {ts.strftime('%H:%M')}  {val:.2f}m", font=font_data, fill=LOW_COLOR)
                y_off += 18
        else:
            draw.text((cx + 16, cy + y_off), "  Low tide: not yet today", font=font_data, fill=LOW_COLOR)

        # Sparkline chart (right side of card)
        if d.get("today_readings"):
            draw_mini_chart(draw, d["today_readings"], cx + card_w - 160, cy + 40, 150, 110)

    # Footer strip
    foot_y = 1080 - 48
    draw.rectangle([(0, foot_y), (1080, 1080)], fill=(15, 22, 38))
    draw.line([(0, foot_y), (1080, foot_y)], fill=(35, 55, 80), width=1)
    draw.text((40, foot_y + 14), "Plan your coastal day safely 🏖️  #UKTides #CoastalSafety #UKCoast", font=font_small, fill=MUTED_COLOR)

    output_path = "uk_tides_today.jpg"
    img.save(output_path, "JPEG", quality=95)
    print(f"✅ Image saved: {output_path}")
    return output_path

# ─── INSTAGRAM POSTING ───────────────────────────────────────────────────────

def post_to_instagram(image_path: str):
    """Posts the image to Instagram. Credentials read from env vars."""
    try:
        from instagrapi import Client
    except ImportError:
        print("⚠️  instagrapi not installed. Run: pip install instagrapi")
        print(f"   Image is ready at: {image_path}")
        return

    if INSTA_USERNAME == "YOUR_INSTAGRAM_USERNAME":
        print("⚠️  Instagram credentials not set. Image saved but not posted.")
        print("    Set INSTA_USERNAME and INSTA_PASSWORD as environment variables.")
        return

    today_str = datetime.now().strftime("%d/%m/%Y")
    caption = (
        f"🌊 UK High & Low Tide Times — {today_str}\n\n"
        "Covering Aberdeen, Liverpool, Cardiff, Avonmouth, Portsmouth, "
        "Bournemouth, Barmouth, Heysham, Whitby & Immingham.\n\n"
        "Data updates every 15 minutes via the Environment Agency. "
        "Always check local conditions before heading to the coast. Stay safe! 🏄\n\n"
        "#UKTides #CoastalSafety #UKCoast #BeachLife #TideTimes "
        "#Sailing #Surfing #UKBeach #CoastalWalking #Fishing"
    )

    print("📲 Logging into Instagram...")
    cl = Client()
    # Session file avoids repeated logins (reduces ban risk)
    session_file = "insta_session.json"
    try:
        if os.path.exists(session_file):
            cl.load_settings(session_file)
            cl.login(INSTA_USERNAME, INSTA_PASSWORD)
        else:
            cl.login(INSTA_USERNAME, INSTA_PASSWORD)
            cl.dump_settings(session_file)

        media = cl.photo_upload(image_path, caption)
        print(f"✅ Posted to Instagram! Media ID: {media.id}")
    except Exception as e:
        print(f"❌ Instagram post failed: {e}")
        print(f"   Image is ready at: {image_path} — you can post it manually.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"🌊 UK Tides Bot — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("─" * 50)

    # 1. Fetch tide data for all stations
    print("📡 Fetching tide data from Environment Agency API...")
    tide_data = {}
    for station_id, info in STATIONS.items():
        print(f"  → {info['name']} ({station_id})...")
        data = get_tide_readings(station_id)
        tide_data[station_id] = {"name": info["name"], "xy": info["xy"], "data": data}

    # 2. Generate image
    print("\n🎨 Generating image...")
    image_path = generate_image(tide_data)

    # 3. Post to Instagram
    print("\n📲 Posting to Instagram...")
    post_to_instagram(image_path)

    print("\n✅ Done.")


if __name__ == "__main__":
    main()


# ─── GITHUB ACTIONS WORKFLOW (copy to .github/workflows/daily_post.yml) ──────
"""
name: Daily UK Tides Post

on:
  schedule:
    - cron: '0 7 * * *'   # runs every day at 07:00 UTC
  workflow_dispatch:        # allows manual trigger from GitHub UI

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install Pillow instagrapi requests

      - name: Run bot
        env:
          INSTA_USERNAME: ${{ secrets.INSTA_USERNAME }}
          INSTA_PASSWORD: ${{ secrets.INSTA_PASSWORD }}
        run: python uk_tides_bot.py
"""
