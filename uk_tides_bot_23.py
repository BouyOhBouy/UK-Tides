"""
UK Daily Tides Email Bot
Data source : Environment Agency Tide Gauge API (FREE, no key required)
Email       : Gmail SMTP (free, uses App Password)
"""

import os
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from PIL import Image, ImageDraw, ImageFont

# ─── BST HELPER ──────────────────────────────────────────────────────────────

def to_local_time(utc_dt):
    """Converts UTC datetime to UK local time (BST in summer, GMT in winter)."""
    import time
    # UK is UTC+1 during BST (last Sunday March to last Sunday October)
    year = utc_dt.year
    # Find last Sunday in March
    import calendar
    def last_sunday(year, month):
        last_day = calendar.monthrange(year, month)[1]
        for day in range(last_day, 0, -1):
            if datetime(year, month, day).weekday() == 6:
                return datetime(year, month, day, 1, 0, tzinfo=timezone.utc)
    bst_start = last_sunday(year, 3)
    bst_end   = last_sunday(year, 10)
    if bst_start <= utc_dt.replace(tzinfo=timezone.utc) < bst_end:
        from datetime import timedelta
        return utc_dt + timedelta(hours=1), "BST"
    return utc_dt, "GMT"

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

GMAIL_USER     = "stevencocks77@gmail.com"
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO       = "stevencocks77@gmail.com"
EA_BASE          = "https://environment.data.gov.uk/flood-monitoring"
PIXABAY_KEY      = os.environ.get("PIXABAY_API_KEY", "")
ADMIRALTY_KEY    = os.environ.get("ADMIRALTY_API_KEY", "")
ADMIRALTY_BASE   = "https://admiraltyapi.azure-api.net/uktidalapi/api/V1"

# Search terms rotated daily for variety
PHOTO_SEARCHES = [
    "sandy beach waves sea", "beach sunset ocean", "tropical beach clear water",
    "beach waves crashing rocks", "beautiful beach summer", "ocean beach blue sky",
    "beach coastline aerial", "beach surf waves", "golden sand beach",
    "beach morning sunrise", "rocky beach cove", "beach turquoise water",
    "ocean waves beach sunny", "beach low tide sand", "coastal beach scenery"
]

# Admiralty API station IDs with display names
# IDs match EasyTide PortIDs: easytide.admiralty.co.uk/?PortID=XXXX
STATIONS = [
    {"id": "0014",  "name": "Plymouth / Looe"},
    {"id": "0002",  "name": "Newlyn / Penzance"},
    {"id": "0005",  "name": "Falmouth / Fowey"},
    {"id": "0535",  "name": "Ilfracombe / N Devon"},
]

# ─── DATA FETCHING (ADMIRALTY API) ───────────────────────────────────────────

def get_tide_predictions(station_id, station_name):
    """Fetches today's predicted high/low tide times from the Admiralty API."""
    result = {"highs": [], "lows": [], "error": False, "name": station_name}
    if not ADMIRALTY_KEY:
        print("  No Admiralty API key — skipping predictions")
        result["error"] = True
        return result
    try:
        url = f"{ADMIRALTY_BASE}/Stations/{station_id}/TidalEvents?duration=1"
        headers = {"Ocp-Apim-Subscription-Key": ADMIRALTY_KEY}
        r = requests.get(url, headers=headers, timeout=15)
        print(f"  {station_name} → HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"    Error: {r.text[:200]}")
            result["error"] = True
            return result

        events = r.json()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for event in events:
            dt_str = event.get("DateTime", "")
            event_type = event.get("EventType", "")
            height = event.get("Height")

            try:
                # Admiralty API returns GMT — parse and convert to BST
                dt = datetime.fromisoformat(dt_str.split(".")[0])
                dt_utc = dt.replace(tzinfo=timezone.utc)
                local_dt, tz = to_local_time(dt_utc)
                time_str = local_dt.strftime("%H:%M") + f" {tz}"
                h = round(float(height), 2) if height is not None else 0.0

                if "High" in event_type:
                    result["highs"].append({"time": time_str, "height": h})
                elif "Low" in event_type:
                    result["lows"].append({"time": time_str, "height": h})
            except Exception as e:
                print(f"    Parse error: {e}")
                continue

        # Trend: find next tidal event after now and determine if rising or falling
        def time_only(t): return t.split(" ")[0]  # strip BST/GMT
        now_str = datetime.now().strftime("%H:%M")
        all_events = sorted(
            [(time_only(h["time"]), "High") for h in result["highs"]] +
            [(time_only(l["time"]), "Low") for l in result["lows"]],
            key=lambda x: x[0]
        )
        next_event = next((e for e in all_events if e[0] >= now_str), None)
        if next_event:
            result["trend"] = "Rising" if next_event[1] == "High" else "Falling"
        else:
            result["trend"] = "Slack"
        print(f"    {len(result['highs'])} highs, {len(result['lows'])} lows, trend: {result['trend']}")
    except Exception as e:
        print(f"    Error: {e}")
        result["error"] = True

    return result

# ─── PHOTO FETCH ─────────────────────────────────────────────────────────────

def fetch_coastal_photo():
    """Fetches a free coastal photo from Pixabay, rotated daily."""
    if not PIXABAY_KEY:
        print("  No Pixabay key — skipping photo")
        return None
    try:
        import random
        search = PHOTO_SEARCHES[datetime.now().timetuple().tm_yday % len(PHOTO_SEARCHES)]
        print(f"  Fetching photo: {search}")
        params = {
            "key": PIXABAY_KEY,
            "q": search,
            "image_type": "photo",
            "orientation": "horizontal",
            "category": "nature",
            "min_width": 1200,
            "safesearch": "true",
            "per_page": 10
        }
        r = requests.get("https://pixabay.com/api/", params=params, timeout=15)
        print(f"  Pixabay status: {r.status_code}")
        if r.status_code != 200:
            print(f"  Pixabay error: {r.text[:200]}")
            return None
        hits = r.json().get("hits", [])
        if not hits:
            print("  No photos found")
            return None
        # Pick a different photo each day
        photo = hits[datetime.now().day % len(hits)]
        img_url = photo["webformatURL"]
        img_r = requests.get(img_url, timeout=15)
        from io import BytesIO
        img = Image.open(BytesIO(img_r.content)).convert("RGB")
        print(f"  Photo fetched: {photo.get('pageURL','')}")
        return img, photo.get("user", "Pixabay")
    except Exception as e:
        print(f"  Photo fetch failed: {e}")
        return None

# ─── IMAGE GENERATION ────────────────────────────────────────────────────────

BG        = (8,  12, 20)
SURFACE   = (16, 24, 38)
SURFACE2  = (22, 34, 54)
BORDER    = (0,  180, 140)
BORDER2   = (30, 50, 78)
HI_COL    = (0,  210, 160)
LO_COL    = (255, 140, 60)
TEXT      = (225, 235, 250)
MUTED     = (100, 130, 165)
TITLE_COL = (0,  220, 165)
TREND_UP  = (0,  200, 120)
TREND_DN  = (255, 100, 80)
TREND_NT  = (100, 130, 165)


def font(size, bold=False):
    paths = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
    ]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()


def draw_wave_icon(draw, cx, cy, r=6):
    """Draws a small wave decoration."""
    for i in range(3):
        x = cx - 12 + i * 12
        draw.arc([(x-r, cy-r), (x+r, cy+r)], 180, 0, fill=BORDER, width=2)


def generate_image(tide_data, photo_data=None):
    W, H = 1080, 1350
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Subtle dot grid background
    for y in range(30, 1350, 36):
        for x in range(30, 1080, 36):
            draw.ellipse([(x-1,y-1),(x+1,y+1)], fill=(18,28,44))

    # ── HEADER ──────────────────────────────────────────────────────────────
    draw.rectangle([(0,0),(W,82)], fill=(12,18,30))
    draw.rectangle([(0,80),(W,83)], fill=BORDER)
    draw.text((40, 10), "UK TIDE TIMES", font=font(38, True), fill=TITLE_COL)
    draw.text((40, 54), datetime.now().strftime("%A  %d %B %Y").upper(), font=font(17), fill=MUTED)
    draw.text((W-40, 57), "ADMIRALTY DATA", font=font(13), fill=(50,80,110), anchor="ra")

    # ── STATION CARDS ───────────────────────────────────────────────────────
    cw, ch = 504, 580
    pad_x, pad_y = 24, 94
    gap = 18

    for idx, d in enumerate(tide_data):
        col = idx % 2
        row = idx // 2
        cx = pad_x + col * (cw + gap)
        cy = pad_y + row * (ch + gap)

        # Card background
        draw.rounded_rectangle([(cx,cy),(cx+cw,cy+ch)], radius=10, fill=SURFACE)
        # Bright outer border — full card outline
        draw.rounded_rectangle([(cx,cy),(cx+cw,cy+ch)], radius=10, outline=BORDER, width=3)
        # Teal left accent bar — inset so it doesnt fight the rounded corners
        draw.rectangle([(cx+3, cy+12),(cx+8, cy+ch-12)], fill=BORDER)

        # Station name
        name = d["name"].upper()
        draw.text((cx+16, cy+18), name, font=font(36, True), fill=TEXT)

        # Divider under name
        draw.line([(cx+10, cy+68),(cx+cw-10, cy+68)], fill=BORDER2, width=1)

        if d["error"]:
            draw.text((cx+16, cy+86), "Data unavailable", font=font(28), fill=MUTED)
            continue

        # Two columns: High left, Low right
        mid = cx + cw // 2
        draw.line([(mid, cy+68),(mid, cy+ch-10)], fill=BORDER2, width=1)

        # HIGH column (left)
        hx = cx + 16
        yo = cy + 80
        draw.text((hx, yo), "HIGH", font=font(34, True), fill=HI_COL)
        draw.text((hx, yo+42), "TIDES", font=font(34, True), fill=HI_COL)
        yo += 104
        if d["highs"]:
            for h in d["highs"][:2]:
                t = h["time"].replace(" BST","").replace(" GMT","")
                draw.text((hx, yo), t, font=font(62, True), fill=TEXT)
                draw.text((hx, yo+70), f"{h['height']:.2f}m", font=font(34), fill=HI_COL)
                yo += 118
        else:
            draw.text((hx, yo), "None today", font=font(28), fill=MUTED)

        # LOW column (right)
        lx = mid + 16
        yo = cy + 80
        draw.text((lx, yo), "LOW", font=font(34, True), fill=LO_COL)
        draw.text((lx, yo+42), "TIDES", font=font(34, True), fill=LO_COL)
        yo += 104
        if d["lows"]:
            for l in d["lows"][:2]:
                t = l["time"].replace(" BST","").replace(" GMT","")
                draw.text((lx, yo), t, font=font(62, True), fill=TEXT)
                draw.text((lx, yo+70), f"{l['height']:.2f}m", font=font(34), fill=LO_COL)
                yo += 118
        else:
            draw.text((lx, yo), "None today", font=font(28), fill=MUTED)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    foot_y = 1350 - 44
    draw.rectangle([(0, foot_y),(W, H)], fill=(12,18,30))
    draw.rectangle([(0, foot_y),(W, foot_y+2)], fill=BORDER)
    draw.text((40, foot_y+12), "Plan your coastal day safely  |  #UKTides  #Cornwall  #Devon", font=font(13), fill=MUTED)

    path = "uk_tides_today.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Image saved: {path}")
    return path

# ─── PHOTO POST GENERATION ──────────────────────────────────────────────────

def generate_photo_post(photo_data):
    """Generates a full 1080x1080 coastal photo post for Instagram."""
    if not photo_data:
        print("  No photo data — skipping photo post")
        return None
    try:
        photo_img, photographer = photo_data
        # Resize to fill 1080x1080
        ratio = max(1080 / photo_img.width, 1080 / photo_img.height)
        new_w = int(photo_img.width * ratio)
        new_h = int(photo_img.height * ratio)
        photo_img = photo_img.resize((new_w, new_h), Image.LANCZOS)
        # Crop to centre square
        left = (new_w - 1080) // 2
        top  = (new_h - 1080) // 2
        photo_img = photo_img.crop((left, top, left + 1080, top + 1080))

        draw = ImageDraw.Draw(photo_img)

        # Dark gradient overlay at bottom
        from PIL import ImageFilter
        for i in range(400):
            opacity = int((i / 400) * 180)
            draw.line([(0, 1080 - i), (1080, 1080 - i)], fill=(0, 0, 0, opacity))

        # Title
        draw.text((50, 820), "🌊 UK COASTAL GUIDE", font=font(38, True), fill=(0, 210, 160))
        draw.text((50, 875), datetime.now().strftime("%A %d %B %Y"), font=font(26), fill=(220, 235, 255))
        draw.text((50, 920), "Plan your coastal visit around the tides", font=font(20), fill=(180, 200, 220))
        draw.text((50, 960), "#Cornwall #Devon #UKCoast #CoastalLife #BeachLife", font=font(17), fill=(120, 145, 175))
        draw.text((50, 990), "#Surfing #Sailing #UKBeach #CoastalWalking #Newquay", font=font(17), fill=(120, 145, 175))
        draw.text((1030, 1060), f"Photo: {photographer} / Pixabay", font=font(12), fill=(100, 120, 140), anchor="rb")

        path = "uk_coast_photo.jpg"
        photo_img.save(path, "JPEG", quality=95)
        print(f"  Photo post saved: {path}")
        return path
    except Exception as e:
        print(f"  Photo post failed: {e}")
        return None

# ─── EMAIL ────────────────────────────────────────────────────────────────────

def send_email(image_path, photo_path=None):
    if not GMAIL_PASSWORD:
        print("No Gmail app password — skipping email.")
        return

    today = datetime.now().strftime("%d %B %Y")
    msg   = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_TO
    msg["Subject"] = f"UK Tide Times — {today}"

    body = (
        f"Your daily posts are attached for {today}.\n\n"
        "POST 1 — TIDE TIMES (uk_tides_today.jpg)\n"
        f"Caption: 🌊 UK High & Low Tide Times — {datetime.now().strftime('%d/%m/%Y')}\n"
        "Covering SW England and South Coast stations.\n"
        "Data from the Environment Agency. Stay safe! 🏄\n"
        "#UKTides #CoastalSafety #UKCoast #Cornwall #Devon #TideTimes\n\n"
        "POST 2 — COASTAL PHOTO (uk_coast_photo.jpg)\n"
        "Caption: 🌊 Todays coastal inspiration!\n"
        "#Cornwall #Devon #UKCoast #CoastalLife #BeachLife #Surfing #Newquay\n"
    )
    msg.attach(MIMEText(body, "plain"))

    with open(image_path, "rb") as f:
        att1 = MIMEImage(f.read(), name="uk_tides_today.jpg")
    msg.attach(att1)

    if photo_path and os.path.exists(photo_path):
        with open(photo_path, "rb") as f:
            att2 = MIMEImage(f.read(), name="uk_coast_photo.jpg")
        msg.attach(att2)
        print("  Photo post attached to email")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASSWORD)
            s.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"Email failed: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"UK Tides Bot — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("-" * 50)

    print("Fetching predicted tide times from Admiralty API...")
    tide_data = []
    for station in STATIONS:
        print(f"  {station['name']}...")
        data = get_tide_predictions(station["id"], station["name"])
        tide_data.append(data)

    print("\nFetching coastal photo...")
    photo_data = fetch_coastal_photo()

    print("\nGenerating tide image...")
    image_path = generate_image(tide_data)

    print("\nGenerating photo post...")
    photo_path = generate_photo_post(photo_data)

    print("\nSending email...")
    send_email(image_path, photo_path)

    print("\nDone.")

if __name__ == "__main__":
    main()
