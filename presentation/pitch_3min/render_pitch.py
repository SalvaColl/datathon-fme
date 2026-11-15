"""Render local HTML only, with installed headless Chrome. No packages are installed."""
import concurrent.futures
import json
import subprocess
from pathlib import Path
from PIL import Image

P = Path(__file__).resolve().parent
OUT = P / "_render"
OUT.mkdir(exist_ok=True)
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
BASE = [str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
        "--disable-background-networking", "--disable-component-update",
        "--disable-extensions", "--no-first-run", "--no-default-browser-check",
        "--hide-scrollbars", "--force-device-scale-factor=1"]

def run(args):
    result = subprocess.run(BASE + args, capture_output=True, timeout=45,
                            creationflags=0x08000000)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf8", "replace")[-1600:])

def screenshot(i):
    run(["--user-data-dir=" + str(OUT / f"screen_profile_{i}"),
         "--window-size=1600,900",
         "--screenshot=" + str(OUT / f"slide_{i+1}.png"),
         "--virtual-time-budget=800",
         (P / "pitch.html").as_uri() + f"?s={i}&clean=1"])
    return i+1

if __name__ == "__main__":
    run(["--user-data-dir=" + str(OUT / "pdf_profile"),
         "--print-to-pdf=" + str(P / "Team26_3min.pdf"),
         "--no-pdf-header-footer", "--virtual-time-budget=1200",
         (P / "pitch.html").as_uri() + "?clean=1"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(screenshot, range(6)))
    canvas = Image.new("RGB", (1600, 1390), "#0a101a")
    for i in range(6):
        im = Image.open(OUT / f"slide_{i+1}.png").convert("RGB")
        im.thumbnail((780, 439))
        canvas.paste(im, (10+(i%2)*800, 10+(i//2)*460))
    canvas.save(P / "preview.png")
    print(json.dumps({"pdf": str(P/"Team26_3min.pdf"), "preview": str(P/"preview.png")}))
