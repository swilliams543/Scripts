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
    "https://www.reddit.com/r/EarthPorn/.rss"
]

def get_image_url_from_feed_with_entry(feed_url):
    """Parses an RSS feed and extracts a random image URL."""
    logging.info("Fetching feed: %s", feed_url)

    # Custom User-Agent and cache-control headers to prevent getting stale feeds
    headers = {
        "User-Agent": "DesktopWallpaperBot/1.0",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    try:
        # Fetch feed content first to handle headers correctly
        response = requests.get(feed_url, headers=headers, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException as e:
        logging.error("Failed to fetch feed %s: %s", feed_url, e)
        return None

    if not feed.entries:
        logging.warning("No entries found in feed.")
        return None

    entries = feed.entries[:]
    random.shuffle(entries)

    for entry in entries:
        url = extract_url(entry)
        if url:
            return url, entry

    return None, None

    logging.warning("No suitable image found in feed entries.")
    return None

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

def download_image(url, entry=None):
    """Downloads the image, resizes it, and adds caption if entry metadata is available."""
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

        # Resize to fit within 1920x1080 while preserving aspect ratio
        with Image.open(final_path) as img:
            img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            img.save(final_path, quality=95)

        # Add caption if we have the RSS entry
        if entry:
            title = getattr(entry, 'title', 'Untitled')
            # Try to get author/credit
            author = ""
            if hasattr(entry, 'author'):
                author = entry.author
            elif hasattr(entry, 'dc_creator'):      # some feeds use Dublin Core
                author = entry.dc_creator
            elif hasattr(entry, 'credit'):
                author = entry.credit

            add_caption_to_image(final_path, title, author)

        logging.info("Image processed and saved: %s", final_path)
        return final_path

    except Exception as e:
        logging.error("Download or processing failed: %s", e)
        return None

def add_caption_to_image(image_path, title, source=""):
    """Adds a nicely formatted caption in the bottom-right corner."""
    try:
        with Image.open(image_path).convert("RGB") as img:
            draw = ImageDraw.Draw(img)

            # Use a system font (fallback to default if not found)
            try:
                font = ImageFont.truetype("arial.ttf", 28)      # Windows
            except IOError:
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", 28)  # Linux/macOS common
                except IOError:
                    font = ImageFont.load_default()

            # Build caption text
            caption = title.strip()
            if source and source.strip() and source.lower() not in title.lower():
                caption += f"\n{source.strip()}"

            # Wrap long lines
            wrapped_lines = textwrap.wrap(caption, width=60)
            line_height = font.getbbox("A")[3] + 8   # approximate line spacing
            total_text_height = len(wrapped_lines) * line_height

            # Padding and position (bottom-right with margin)
            margin = 30
            padding = 15
            text_width = max(draw.textlength(line, font=font) for line in wrapped_lines)
            box_width = int(text_width + padding * 2)
            box_height = int(total_text_height + padding * 2)

            x = img.width - box_width - margin
            y = img.height - box_height - margin

            # Draw semi-transparent dark background
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)
            draw_overlay.rounded_rectangle(
                [x, y, x + box_width, y + box_height],
                radius=12,
                fill=(0, 0, 0, 180)   # semi-transparent black
            )

            # Composite the overlay onto the image
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

            # Redraw on the final image
            draw = ImageDraw.Draw(img)

            # Draw each line of text
            current_y = y + padding
            for line in wrapped_lines:
                draw.text((x + padding, current_y), line, font=font, fill=(255, 255, 255))
                current_y += line_height

            # Save back to the same file
            img.save(image_path, quality=95)
            logging.info("Caption added to bottom-right of image.")

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
    """Main function to fetch, process, and set wallpaper."""
    feed_url = random.choice(FEEDS)
    logging.info("Selected feed: %s", feed_url)

    # We need to modify get_image_url_from_feed slightly to also return the entry
    # For now, we'll adjust it minimally — see note below

    image_url, entry = get_image_url_from_feed_with_entry(feed_url)   # we'll create this

    if not image_url:
        logging.error("Could not find an image URL. Exiting.")
        return

    local_path = download_image(image_url, entry)
    if not local_path:
        logging.error("Could not process image. Exiting.")
        return

    set_wallpaper_fit(local_path)
    logging.info("Wallpaper updated successfully with caption.")

if __name__ == "__main__":
    main()
