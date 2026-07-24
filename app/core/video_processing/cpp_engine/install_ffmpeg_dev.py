import os
import requests
import tempfile
import shutil

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z"
TEMP_DIR = os.path.join(os.environ['TEMP'], 'ffmpeg_dev_install')
FFMPEG_DEV_DIR = r"C:\ffmpeg_win_dev"

def main():
    print("=" * 60)
    print("  FFmpeg Dev Library Installer")
    print("=" * 60)
    
    if os.path.exists(os.path.join(FFMPEG_DEV_DIR, "include", "libavcodec", "avcodec.h")):
        print("\n[SKIP] FFmpeg dev libs already exist!")
        return
    
    os.makedirs(TEMP_DIR, exist_ok=True)
    archive_path = os.path.join(TEMP_DIR, "ffmpeg.7z")
    
    # Resolve redirect
    print("\n[0/3] Resolving download URL...")
    try:
        head = requests.head(FFMPEG_URL, allow_redirects=True)
        final_url = head.url
        print(f"  Final URL: {final_url}")
    except Exception as e:
        print(f"  Redirect resolve failed: {e}")
        final_url = FFMPEG_URL
    
    print(f"\n[1/3] Downloading FFmpeg dev package (~80MB)...")
    print(f"  URL: {final_url}")
    
    try:
        with requests.get(final_url, stream=True, timeout=300) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(archive_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded / total * 100
                            mb = downloaded / 1024 / 1024
                            print(f"\r  Progress: {pct:.0f}% ({mb:.1f} MB)", end='', flush=True)
            print(f"\n  Download complete: {os.path.getsize(archive_path) / 1024 / 1024:.1f} MB")
    except Exception as e:
        print(f"\n  Download FAILED: {e}")
        print("\nManual download:")
        print(f"  1. Visit: {FFMPEG_URL}")
        print(f"  2. Download and extract to: {FFMPEG_DEV_DIR}")
        return
    
    print("\n[2/3] Extracting...")
    extract_dir = os.path.join(TEMP_DIR, "extracted")
    
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            z.extractall(extract_dir)
        print("  Extracted with py7zr")
    except ImportError:
        print("  py7zr not available, trying 7z.exe...")
        seven_zip = r"C:\Program Files\7-Zip\7z.exe"
        if os.path.exists(seven_zip):
            os.system(f'"{seven_zip}" x "{archive_path}" -o"{extract_dir}" -y')
        else:
            print("  7-Zip not found! Install it or run: pip install py7zr")
            return
    except Exception as e:
        print(f"  Extraction FAILED: {e}")
        return
    
    print("\n[3/3] Installing to", FFMPEG_DEV_DIR)
    os.makedirs(FFMPEG_DEV_DIR, exist_ok=True)
    
    installed = False
    for item in os.listdir(extract_dir):
        item_path = os.path.join(extract_dir, item)
        if os.path.isdir(item_path):
            include_src = os.path.join(item_path, "include")
            lib_src = os.path.join(item_path, "lib")
            if os.path.exists(include_src):
                shutil.copytree(include_src, os.path.join(FFMPEG_DEV_DIR, "include"), dirs_exist_ok=True)
                if os.path.exists(lib_src):
                    shutil.copytree(lib_src, os.path.join(FFMPEG_DEV_DIR, "lib"), dirs_exist_ok=True)
                installed = True
                print(f"  Found package: {item}")
                break
    
    if installed:
        if os.path.exists(os.path.join(FFMPEG_DEV_DIR, "include", "libavcodec", "avcodec.h")):
            print("\n" + "=" * 60)
            print("  FFmpeg dev libs installed successfully!")
            print(f"  Headers: {FFMPEG_DEV_DIR}\\include\\")
            print(f"  Libs:    {FFMPEG_DEV_DIR}\\lib\\")
            print("=" * 60)
        else:
            print("  WARNING: Header files not found after install!")
    else:
        print("  ERROR: Could not find include/lib directories!")
    
    # Cleanup
    try:
        shutil.rmtree(TEMP_DIR)
    except Exception:
        pass

if __name__ == "__main__":
    main()
