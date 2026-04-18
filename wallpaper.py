"""
Windows Wallpaper Rotator
Fetches random high-quality images from RSS feeds and updates the desktop background.
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import textwrap   # for wrapping long titles
import winreg
import os
import random
import ctypes
import logging
import re


import requests
import feedparser

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Constants for Windows Wallpaper API
SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDWININICHANGE = 0x02

# List of RSS Feeds (Reddit and Wikimedia Commons)
FEEDS = [
    "https://commons.wikimedia.org/w/api.php?action=featuredfeed&feed=potd&feedformat=rss&language=en",
    "https://www.reddit.com/r/wallpapers/.rss",
    "https://www.reddit.com/r/wallpaper/.rss",
    "https://www.reddit.com/r/EarthPorn/.rss",
    'https://www.reddit.com/r/BotanicalPorn/.rss',
    'https://www.reddit.com/r/MacroPorn/.rss',
    'https://www.reddit.com/r/NaturePorn/.rss',
]

def get_image_url_from_feed_with_entry(feed_url):
    """Parses an RSS feed and returns (image_url, entry, source_name)"""
    logging.info("Fetching feed: %s", feed_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
    }

    try:
        response = requests.get(feed_url, headers=headers, timeout=20)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException as e:
        logging.error("Failed to fetch feed %s: %s", feed_url, e)
        return None, None, "Unknown"

    # Determine source name from the feed URL
    if "wikimedia.org" in feed_url.lower():
        source_name = "Wikimedia Commons • Picture of the Day"
    else:
        # Extract subreddit name from Reddit URL (e.g. /r/BotanicalPorn)
        match = re.search(r'/r/([^/]+)/', feed_url)
        source_name = f"/r/{match.group(1)}" if match else "Reddit"

    entries = feed.entries[:]
    random.shuffle(entries)

    for entry in entries:
        url = extract_url(entry)
        if url:
            return url, entry, source_name

    logging.warning("No suitable image found in feed entries.")
    return None, None, source_name

def extract_url(entry):
    """Extracts image URL from a feed entry."""
    def clean_wikimedia(url):
        """Converts Wikimedia thumb URL to full-size image URL."""
        if "upload.wikimedia.org" in url.lower() and "/thumb/" in url.lower():
            parts = url.split('/')
            try:
                # Wikimedia thumb URLs have 'thumb' and an extra resolution segment at the end
                idx = parts.index('thumb')
                parts.pop(idx) # Remove 'thumb'
                parts.pop(-1)  # Remove the trailing thumbnail resolution segment
                return '/'.join(parts)
            except (ValueError, IndexError):
                return url
        return url

    content = ""
    if hasattr(entry, 'content'):
        content = entry.content[0].value
    elif hasattr(entry, 'summary'):
        content = entry.summary
    elif hasattr(entry, 'description'):
        content = entry.description

    if content:
        # Find all links (href and src) that look like images
        links = re.findall(r'(?:href|src)="([^"]+\.(?:jpg|jpeg|png|bmp))"', content, re.IGNORECASE)

        # 1. Prioritize direct high-res image hosts (common for Reddit and Wikimedia)
        for link in links:
            lower_link = link.lower()
            if any(domain in lower_link for domain in ["i.redd.it", "i.imgur.com", "upload.wikimedia.org"]):
                if "preview" not in lower_link:
                    return clean_wikimedia(link)

        # 2. Fallback to any image link that isn't a preview/thumbnail
        for link in links:
            lower_link = link.lower()
            if "preview" not in lower_link and "thumb" not in lower_link:
                return clean_wikimedia(link)

    # Method 2: Check for media_content (usually better than thumbnails)
    if hasattr(entry, 'media_content'):
        # Sort by width if available to pick the largest image
        media_list = sorted(entry.media_content, key=lambda x: int(x.get('width', 0)), reverse=True)
        for media in media_list:
            if 'image' in media.get('type', '') or media.get('medium') == 'image':
                return clean_wikimedia(media['url'])

    # Method 3: Check for img src as a last resort from content
    if content:
        srcs = re.findall(r'src="([^"]+\.(?:jpg|jpeg|png))"', content, re.IGNORECASE)
        if srcs:
            # Try to find one that isn't a preview
            for src in srcs:
                lower_src = src.lower()
                if "preview" not in lower_src and "thumb" not in lower_src:
                    return clean_wikimedia(src)
            return clean_wikimedia(srcs[0])

    return None

def download_image(url, entry=None, source_name=""):
    """Downloads the image, resizes it, and adds caption."""
    try:
        logging.info("Downloading image: %s", url)
        headers = {"User-Agent": "DesktopWallpaperBot/1.0"}
        response = requests.get(url, headers=headers, stream=True, timeout=20)
        response.raise_for_status()

        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Wallpapers")
        os.makedirs(folder, exist_ok=True)

        ext = os.path.splitext(url.split('?')[0])[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.bmp']:
            ext = ".jpg"

        final_path = os.path.join(folder, f"wallpaper_current{ext}")

        # Save downloaded image
        with open(final_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Resize
        with Image.open(final_path) as img:
            img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            img.save(final_path, quality=95)

        # Add caption
        if entry:
            title = getattr(entry, 'title', 'Untitled')

            author = ""
            if hasattr(entry, 'author'):
                author = entry.author
            elif hasattr(entry, 'dc_creator'):
                author = entry.dc_creator
            elif hasattr(entry, 'credit'):
                author = entry.credit

            add_caption_to_image(final_path, title, author, source_name)

        logging.info("Image processed and saved: %s", final_path)
        return final_path

    except Exception as e:
        logging.error("Download or processing failed: %s", e)
        return None

def add_caption_to_image(image_path, title, source="", subreddit_or_source=""):
    """Adds caption in bottom-right with black outline (no background box)."""
    try:
        with Image.open(image_path).convert("RGB") as img:
            draw = ImageDraw.Draw(img)

            # Load fonts
            try:
                font = ImageFont.truetype("arial.ttf", 20)      # Title font - slightly larger
                small_font = ImageFont.truetype("arial.ttf", 15)  # Subreddit / author
            except IOError:
                font = ImageFont.load_default()
                small_font = ImageFont.load_default()

            # Build the lines
            lines = [title.strip()]
            #if subreddit_or_source:
            #    lines.append(subreddit_or_source)
            if source and source.strip() and source.lower() not in title.lower():
                lines.append(source.strip())

            # Wrap very long title
            if len(lines[0]) > 80:
                wrapped = textwrap.wrap(lines[0], width=65)
                lines = wrapped + lines[1:]

            # Calculate positioning
            margin = 50
            padding = 15

            # Draw each line with black outline + white fill
            current_y = img.height - margin

            for i, line in enumerate(reversed(lines)):   # Draw from bottom up for easier positioning
                current_font = font if i == len(lines) - 1 else small_font
                text_color = (255, 255, 255)
                outline_color = (0, 0, 0)

                # Get text size
                bbox = draw.textbbox((0, 0), line, font=current_font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                # Position: right-aligned with margin
                x = img.width - text_width - margin
                y = current_y - text_height - padding

                # Draw black outline (stroke) - multiple offsets for thickness
                for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                    draw.text((x + dx, y + dy), line, font=current_font, fill=outline_color)

                # Draw main white text on top
                draw.text((x, y), line, font=current_font, fill=text_color)

                # Move up for next line
                current_y = y - 4   # small gap between lines

            img.save(image_path, quality=95)
            logging.info("Caption with black outline added (no background).")

    except Exception as e:
        logging.warning("Could not add caption: %s", e)


def set_wallpaper_fit(image_path):
    """Sets the desktop wallpaper and forces 'Fit' style (preserves aspect ratio, no crop)."""
    try:
        abs_path = os.path.abspath(image_path)

        # Set registry keys for "Fit" style
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "6")   # 6 = Fit
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
        winreg.CloseKey(key)

        # Apply the wallpaper
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, abs_path, SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE
        )

        if result:
            logging.info("Wallpaper set successfully with 'Fit' style.")
        else:
            logging.error("SystemParametersInfoW failed.")

    except Exception as e:
        logging.error("Failed to set wallpaper style: %s", e)

def main():
    feed_url = random.choice(FEEDS)
    logging.info("Selected feed: %s", feed_url)

    image_url, entry, source_name = get_image_url_from_feed_with_entry(feed_url)

    if not image_url:
        logging.error("Could not find an image URL. Exiting.")
        return

    local_path = download_image(image_url, entry, source_name)

    if not local_path:
        logging.error("Could not process image. Exiting.")
        return

    set_wallpaper_fit(local_path)
    logging.info("Wallpaper updated successfully with caption and source.")

if __name__ == "__main__":
    main()
