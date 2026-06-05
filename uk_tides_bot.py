"""
UK Daily Tides Email Bot
==============================
Data source : Environment Agency Tide Gauge API (FREE, no key required)
Image lib   : Pillow
Email       : Gmail SMTP (free, uses App Password)

Sends the daily tide image to your email every morning.
"""

import os
import math
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from PIL import Image, ImageDraw, ImageFont

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

GMAIL_USER     = "stevencocks77@gmail.com"
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO       = "stevencocks77@gmail.com"

STATIONS = {
    "E72637": {"name": "Aberdeen",    "xy": (700, 130)},
    "E72660": {"name": "Liverpool",   "xy": (370, 440)},
    "E70186": {"name": "Cardiff",     "xy": (340, 620)},
    "E72639": {"name": "Avonmouth",   "xy": (310, 660)},
    "E72642": {"name": "Portsmouth",  "xy": (700, 720)},
    "E72641": {"name": "Bournemouth", "xy": (620, 750)},
    "E72649": {"name": "Barmouth",    "xy": (270, 490)},
    "E72651": {"name": "Heysham",     "xy": (390, 380)},
    "E72658": {"name": "Whitby",      "xy": (680, 330)},
    "E72656": {"name": "Immingham",   "xy": (720, 430)},
}

EA_BASE = "https://environment.data.gov.uk/flood-monitoring"

# ─── DATA FETCHING ────────────────────────────────────────────────────────────

def get_tide_readings(station_id):
    result = {"latest_level": None, "trend": "—", "today_readings": [], "error": False}
    try:
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
        latest_ts, latest_val = readings[-1]
        result["latest_level"] = round(latest_val, 2)
        result["latest_time"] = latest_ts.strftime("%H:%M")

        if len(readings) >= 3:
            recent = readings[-1][1]
            earlier = readings[-3][1]
            if recent > earlier + 0.05:
                result["trend"] = "Rising"
            elif recent < earlier - 0.05:
                result["trend"] = "Falling"
            else:
                result["trend"] = "Slack"

        highs, lows = detect_peaks(readings)
        result["highs"] = highs
        result["lows"] = lows

    except Exception as e:
        print(f"  Error fetching {station_id}: {e}")
        result["error"] = True

    return result


def detect_peaks(readings):
    highs, lows = [], []
    values = [v for _, v in readings]
    times = [t for t, _ in readings]
    window = 4
    for i in range(window, len(values) - window):
        segment = values[i - window: i + window + 1]
        if values[i] == max(segment) and values[i] > values[i - 1]:
            highs.append((times[i], values[i]))
        elif values[i] == min(segment) and values[i] < values[i - 1]:
            lows.append((times[i], values[i]))
    return highs, lows

# ─── IMAGE GENERATION ────────────────────────────────────────────────────────

CANVAS_SIZE = (1080, 1080)
BG_COLOR    = (10, 15, 25)
CARD_COLOR  = (20, 30, 48)
CARD_BORDER = (0, 180, 140)
HIGH_COLOR  = (0, 200, 160)
LOW_COLOR   = (255, 120, 60)
TEXT_COLOR  = (220, 235, 255)
MUTED_COLOR = (120, 145, 175)
TITLE_COLOR = (0, 210, 160)


def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def draw_mini_chart(draw, readings, x, y, w, h):
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


def generate_image(tide_data):
    img = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(img)

    for y in range(0, 1080, 60):
        draw.line([(0, y), (1080, y)], fill=(20, 28, 42), width=1)

    draw.rectangle([(0, 0), (1080, 110)], fill=(15, 22, 38))
    draw.line([(0, 110), (1080, 110)], fill=CARD_BORDER, width=2)

    font_title   = load_font(46, bold=True)
    font_sub     = load_font(22)
    font_station = load_font(19, bold=True)
    font_data    = load_font(16)
    font_small   = load_font(13)

    today_str = datetime.now().strftime("%A %d %B %Y")
    draw.text((40, 22), "UK TIDE TIMES", font=font_title, fill=TITLE_COLOR)
    draw.text((40, 78), today_str, font=font_sub, fill=MUTED_COLOR)
    draw.text((1080 - 10, 1070), "Data: Environment Agency (Open Govt Licence)", font=font_small, fill=(60, 80, 100), anchor="rb")

    card_w, card_h = 480, 170
    margin_x, margin_y = 35, 125
    gap_x, gap_y = 30, 18
    cols = 2

    for idx, (station_id, info) in enumerate(tide_data.items()):
        col = idx % cols
        row = idx // cols
        cx = margin_x + col * (card_w + gap_x)
        cy = margin_y + row * (card_h + gap_y)

        draw.rectangle([(cx, cy), (cx + card_w, cy + card_h)], fill=CARD_COLOR)
        draw.rectangle([(cx, cy), (cx + card_w, cy + card_h)], outline=(35, 55, 80), width=1)
        draw.rectangle([(cx, cy), (cx + 4, cy + card_h)], fill=CARD_BORDER)

        d = info["data"]
        name = info["name"]

        if d["error"]:
            draw.text((cx + 16, cy + 14), name, font=font_station, fill=TEXT_COLOR)
            draw.text((cx + 16, cy + 45), "Data unavailable", font=font_data, fill=MUTED_COLOR)
            continue

        draw.text((cx + 16, cy + 12), name.upper(), font=font_station, fill=TEXT_COLOR)
        trend = d.get("trend", "")
        trend_color = HIGH_COLOR if "Rising" in trend else LOW_COLOR if "Falling" in trend else MUTED_COLOR
        draw.text((cx + card_w - 10, cy + 14), trend, font=font_small, fill=trend_color, anchor="ra")

        level_txt = f"Now: {d['latest_level']}m  ({d.get('latest_time','')} UTC)"
        draw.text((cx + 16, cy + 40), level_txt, font=font_data, fill=MUTED_COLOR)

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

        lows = d.get("lows", [])
        draw.text((cx + 16, cy + y_off), "LOW TIDES", font=font_small, fill=LOW_COLOR)
        y_off += 18
        if lows:
            for ts, val in lows[:2]:
                draw.text((cx + 16, cy + y_off), f"  {ts.strftime('%H:%M')}  {val:.2f}m", font=font_data, fill=LOW_COLOR)
                y_off += 18
        else:
            draw.text((cx + 16, cy + y_off), "  Low tide: not yet today", font=font_data, fill=LOW_COLOR)

        if d.get("today_readings"):
            draw_mini_chart(draw, d["today_readings"], cx + card_w - 160, cy + 40, 150, 110)

    foot_y = 1080 - 48
    draw.rectangle([(0, foot_y), (1080, 1080)], fill=(15, 22, 38))
    draw.line([(0, foot_y), (1080, foot_y)], fill=(35, 55, 80), width=1)
    draw.text((40, foot_y + 14), "Plan your coastal day safely  #UKTides #CoastalSafety #UKCoast", font=font_small, fill=MUTED_COLOR)

    output_path = "uk_tides_today.jpg"
    img.save(output_path, "JPEG", quality=95)
    print(f"Image saved: {output_path}")
    return output_path

# ─── EMAIL ───────────────────────────────────────────────────────────────────

def send_email(image_path):
    if not GMAIL_PASSWORD:
        print("No Gmail app password set — skipping email.")
        return

    today_str = datetime.now().strftime("%d %B %Y")
    subject = f"UK Tide Times — {today_str}"

    body = f"""
Your daily UK tide times image is attached for {today_str}.

Stations covered: Aberdeen, Liverpool, Cardiff, Avonmouth, Portsmouth,
Bournemouth, Barmouth, Heysham, Whitby, Immingham.

Save the attached image and post it to your Instagram page!

Caption to use:
🌊 UK High & Low Tide Times — {datetime.now().strftime('%d/%m/%Y')}
Covering 10 coastal stations around the UK.
Data from the Environment Agency, updated every 15 minutes.
Always check local conditions before heading to the coast. Stay safe! 🏄
#UKTides #CoastalSafety #UKCoast #BeachLife #TideTimes #Sailing #Surfing #UKBeach #CoastalWalking #Fishing
    """

    msg = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(image_path, "rb") as f:
        img_data = f.read()
    image_attachment = MIMEImage(img_data, name="uk_tides_today.jpg")
    msg.attach(image_attachment)

    try:
        print("Sending email...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"Email failed: {e}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"UK Tides Bot — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("-" * 50)

    print("Fetching tide data...")
    tide_data = {}
    for station_id, info in STATIONS.items():
        print(f"  -> {info['name']}...")
        data = get_tide_readings(station_id)
        tide_data[station_id] = {"name": info["name"], "xy": info["xy"], "data": data}

    print("\nGenerating image...")
    image_path = generate_image(tide_data)

    print("\nSending email...")
    send_email(image_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
