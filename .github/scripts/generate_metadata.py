import os
import json
import re
import datetime
import subprocess
import colorsys
from PIL import Image

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
THUMB_SIZE = (640, 360)
PREVIEW_SIZE = (1920, 1080)
THUMB_DIR = 'thumbnails'
PREVIEW_DIR = 'previews'
METADATA_FILE = 'wallpapers.json'
DATES_FILE = '.github/data/wallpaper-dates.json'
METADATA_VERSION = 5 # Increment this to force re-processing

def get_wallhaven_id(filename):
    match = re.search(r'wallhaven-([a-z0-9]+)', filename, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def get_git_mtime(filename):
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%cI', filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        if result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return datetime.datetime.fromtimestamp(os.stat(filename).st_mtime).isoformat()

def load_wallpaper_dates():
    """Load the authoritative filename -> date map. On main, files are orphan
    snapshots with no history, so git mtimes are unreliable; this checked-in map
    is the source of truth for mtime."""
    if os.path.exists(DATES_FILE):
        try:
            with open(DATES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {DATES_FILE}: {e}")
    return {}

def get_dominant_color(img):
    try:
        # Resize to 1x1 to get average color
        img = img.convert('RGB')
        img = img.resize((1, 1), resample=Image.Resampling.BILINEAR)
        color = img.getpixel((0, 0))
        return '#{:02x}{:02x}{:02x}'.format(*color)
    except Exception:
        return '#47464f' # Fallback

def get_color_groups(img):
    """Samples the image and returns a unique list of human-readable color groups with a frequency threshold."""
    img = img.convert('RGB')
    # Use 8x8 grid for better statistical accuracy (64 samples)
    grid_size = 8
    small_img = img.resize((grid_size, grid_size), resample=Image.Resampling.BILINEAR)
    
    color_counts = {}
    for x in range(grid_size):
        for y in range(grid_size):
            r, g, b = small_img.getpixel((x, y))
            r_norm, g_norm, b_norm = r/255.0, g/255.0, b/255.0
            h, s, v = colorsys.rgb_to_hsv(r_norm, g_norm, b_norm)
            h_deg = h * 360
            
            # SMART THRESHOLDS
            # Colors with very low saturation (s < 0.25) look gray/white
            # Colors with very low value (v < 0.20) look black
            if s < 0.25 or v < 0.20: continue
            
            group = None
            # Precision-calibrated Hue ranges for human perception
            if h_deg < 10 or h_deg >= 345: group = "Red"
            elif h_deg < 45: group = "Orange"
            elif h_deg < 70: group = "Yellow"
            elif h_deg < 160: group = "Green"
            elif h_deg < 250: group = "Blue"   # Ends at 250 to catch Indigo in Purple
            elif h_deg < 345: group = "Purple" # Starts at 250, covers Indigo/Pink, ends at 345
            
            if group:
                color_counts[group] = color_counts.get(group, 0) + 1
    
    # Significant threshold (12/64 = ~19% of image area)
    significant_groups = [g for g, count in color_counts.items() if count >= 12]
    
    # Fallback: If nothing is significant enough, take the top 1 only if it's clear enough
    if not significant_groups and color_counts:
        top_color = max(color_counts, key=color_counts.get)
        # Fallback must have at least 6 pixels (~9% area)
        if color_counts[top_color] >= 6:
            significant_groups = [top_color]
        
    return sorted(significant_groups)

def generate_metadata():
    if not os.path.exists(THUMB_DIR):
        os.makedirs(THUMB_DIR)
    if not os.path.exists(PREVIEW_DIR):
        os.makedirs(PREVIEW_DIR)

    # Load existing metadata
    old_metadata = {}
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f:
                data = json.load(f)
                # Key by filename
                old_metadata = {item['filename']: item for item in data}
        except Exception as e:
            print(f"Warning: Could not load old metadata: {e}")

    # List current image files
    current_files = [f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
    
    # Load authoritative dates (orphan snapshot: no per-file git history on main)
    wallpaper_dates = load_wallpaper_dates()

    wallpapers = []
    processed_count = 0
    skipped_count = 0
    
    for filename in current_files:
        thumb_name = f"thumb_{os.path.splitext(filename)[0]}.webp"
        thumb_path = os.path.join(THUMB_DIR, thumb_name)
        
        preview_name = f"preview_{os.path.splitext(filename)[0]}.webp"
        preview_path = os.path.join(PREVIEW_DIR, preview_name)
        
        # Check if we can reuse metadata AND if version matches AND it's not Unknown
        if filename in old_metadata and os.path.exists(thumb_path) and os.path.exists(preview_path) and \
           old_metadata[filename].get("version") == METADATA_VERSION and \
           old_metadata[filename].get("resolution") != "Unknown":
            wallpapers.append(old_metadata[filename])
            skipped_count += 1
            continue
        
        # If not, process the file
        print(f"Processing: {filename}")
        processed_count += 1
        mtime = wallpaper_dates.get(filename) or get_git_mtime(filename)
        
        dominant_color = '#47464f'
        color_groups = []
        resolution = "Unknown"
        
        # Try processing with PIL first
        try:
            with Image.open(filename) as img:
                width, height = img.size
                resolution = f"{width}x{height}"
                dominant_color = get_dominant_color(img)
                color_groups = get_color_groups(img)
                if not os.path.exists(preview_path):
                    preview_img = img.copy()
                    preview_img.thumbnail(PREVIEW_SIZE)
                    preview_img.save(preview_path, 'WEBP', optimize=True, quality=85)
                if not os.path.exists(thumb_path):
                    thumb_img = img.copy()
                    thumb_img.thumbnail(THUMB_SIZE)
                    thumb_img.save(thumb_path, 'WEBP', optimize=True, quality=85)
        except Exception as e:
            print(f"PIL error for {filename}: {e}. Trying ImageMagick fallback...")
            
            # Fallback for Resolution using identify
            try:
                res_result = subprocess.run(
                    ['identify', '-format', '%wx%h', filename],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
                )
                if res_result.stdout.strip():
                    resolution = res_result.stdout.strip()
            except Exception as res_err:
                print(f"Identify error for {filename}: {res_err}")

            # Fallback for Preview using magick or convert
            if not os.path.exists(preview_path):
                try:
                    cmd = ['magick', filename, '-thumbnail', f'{PREVIEW_SIZE[0]}x{PREVIEW_SIZE[1]}>', preview_path]
                    try:
                        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        cmd[0] = 'convert'
                        subprocess.run(cmd, check=True)
                except Exception as prev_err:
                    print(f"Magick/Convert preview error for {filename}: {prev_err}")

            # Fallback for Thumbnail using magick or convert
            if not os.path.exists(thumb_path):
                try:
                    # Try 'magick' first (v7), then 'convert' (v6)
                    cmd = ['magick', filename, '-thumbnail', f'{THUMB_SIZE[0]}x{THUMB_SIZE[1]}>', thumb_path]
                    try:
                        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        cmd[0] = 'convert'
                        subprocess.run(cmd, check=True)
                except Exception as thumb_err:
                    print(f"Magick/Convert thumb error for {filename}: {thumb_err}")
                    # Keep the intended thumb path so the original is never served
                    # as a "thumbnail" (would break dist-only deployments).

            # Try to get colors using a "cleaned" temp image if PIL failed initially
            temp_clean = f"temp_clean_{filename}.png"
            try:
                # Use magick or convert to strip profiles
                cmd = ['magick', filename, '-strip', temp_clean]
                try:
                    subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    cmd[0] = 'convert'
                    subprocess.run(cmd, check=True)
                
                with Image.open(temp_clean) as clean_img:
                    dominant_color = get_dominant_color(clean_img)
                    color_groups = get_color_groups(clean_img)
                os.remove(temp_clean)
            except Exception as color_err:
                print(f"Color extraction fallback error for {filename}: {color_err}")
                if os.path.exists(temp_clean): os.remove(temp_clean)
        
        wallpaper = {
            "filename": filename,
            "thumbnail": thumb_path,
            "preview": preview_path,
            "mtime": mtime,
            "resolution": resolution,
            "color": dominant_color,
            "color_groups": color_groups,
            "wallhaven_id": get_wallhaven_id(filename),
            "version": METADATA_VERSION
        }
        wallpapers.append(wallpaper)
            
    wallpapers.sort(key=lambda x: x['mtime'], reverse=True)
    
    with open(METADATA_FILE, 'w') as f:
        json.dump(wallpapers, f, indent=2)
    
    # Persist dates for any newly processed files so future runs are stable
    if processed_count:
        updated = False
        for wp in wallpapers:
            if wp['filename'] not in wallpaper_dates:
                wallpaper_dates[wp['filename']] = wp['mtime']
                updated = True
        if updated:
            os.makedirs(os.path.dirname(DATES_FILE), exist_ok=True)
            with open(DATES_FILE, 'w') as f:
                json.dump({k: wallpaper_dates[k] for k in sorted(wallpaper_dates)}, f, indent=2)
            print(f"Updated {DATES_FILE} with {len(wallpaper_dates)} entries")
    
    # Cleanup thumbnails and previews
    current_thumb_names = {f"thumb_{os.path.splitext(f)[0]}.webp" for f in current_files}
    current_thumb_names.add('thumb_social_preview.webp')
    for thumb in os.listdir(THUMB_DIR):
        if thumb not in current_thumb_names:
            try:
                os.remove(os.path.join(THUMB_DIR, thumb))
            except:
                pass
                
    current_preview_names = {f"preview_{os.path.splitext(f)[0]}.webp" for f in current_files}
    for prev in os.listdir(PREVIEW_DIR):
        if prev not in current_preview_names:
            try:
                os.remove(os.path.join(PREVIEW_DIR, prev))
            except:
                pass
    
    # Stable "random" thumbnail for social previews (og:image).
    # Uses the newest wallpaper so the preview is always fresh yet stable between runs.
    if wallpapers:
        rand_wp = wallpapers[0]
        random_thumb = os.path.join(THUMB_DIR, 'thumb_social_preview.webp')
        try:
            with Image.open(rand_wp['filename']) as img:
                thumb_img = img.copy()
                thumb_img.thumbnail(THUMB_SIZE)
                thumb_img.save(random_thumb, 'WEBP', optimize=True, quality=85)
        except Exception as e:
            print(f"Random thumbnail error: {e}")

    print(f"Done! Processed: {processed_count}, Skipped: {skipped_count}")

if __name__ == "__main__":
    generate_metadata()
