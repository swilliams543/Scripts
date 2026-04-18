"""
Windows Wallpaper Rotator
Fetches random high-quality images from RSS feeds and updates the desktop background.
"""
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

def get_image_url_from_feed(feed_url):
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

    # Shuffle entries to get a random image
    entries = feed.entries[:]
    random.shuffle(entries)

    for entry in entries:
        url = extract_url(entry)
        if url:
            return url

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

def download_image(url):
    """Downloads the image to a persistent file in the Pictures folder."""
    try:
        logging.info("Downloading image: %s", url)
        headers = {"User-Agent": "DesktopWallpaperBot/1.0"}
        response = requests.get(url, headers=headers, stream=True, timeout=20)
        response.raise_for_status()

        # Save to a persistent location. If the file is deleted (like in a temp folder),
        # Windows will lose the wallpaper source and show a black background.
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Wallpapers")
        if not os.path.exists(folder):
            os.makedirs(folder)

        ext = os.path.splitext(url)[1].split('?')[0].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.bmp']:
            ext = ".jpg"

        path = os.path.join(folder, f"wallpaper_current{ext}")

        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return path
    except (requests.RequestException, OSError) as e:
        logging.error("Download failed: %s", e)
        return None

def set_wallpaper(image_path):
    """Sets the desktop wallpaper on Windows."""
    logging.info("Setting wallpaper to: %s", image_path)
    try:
        # SystemParametersInfoW requires absolute path
        abs_path = os.path.abspath(image_path)
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, abs_path, SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE
        )
        if not result:
            logging.error("SystemParametersInfoW returned False.")
    except OSError as e:
        logging.error("Failed to set wallpaper: %s", e)

def main():
    """Main function to fetch and set wallpaper."""
    # Select a random feed
    feed_url = random.choice(FEEDS)

    image_url = get_image_url_from_feed(feed_url)
    if not image_url:
        logging.error("Could not find an image URL from the selected feed. Exiting.")
        return

    local_path = download_image(image_url)
    if not local_path:
        logging.error("Could not download image. Exiting.")
        return

    set_wallpaper(local_path)
    logging.info("Wallpaper updated successfully.")

if __name__ == "__main__":
    main()
