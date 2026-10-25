"""Route actual curl to the local fixture; emulate only Kindle hardware APIs."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from PIL import Image

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["E2E_DEVICE"])
if name == "curl":
    config_index = args.index("--config") + 1
    config = Path(args[config_index]).read_text()
    url = next(line.split('"')[1] for line in config.splitlines() if line.startswith("url = "))
    parsed = urlsplit(url)
    if parsed.hostname not in {"images.e2e.test", "rsf.qiniuapi.com"}:
        sys.exit(90)
    target = os.environ["E2E_ORIGIN"] + parsed.path + "?" + parsed.query
    config = config.replace(url, target) + f'header = "Host: {parsed.netloc}"\n'
    args[config_index] = "-"
    args[args.index("--proto") + 1] = "=http"
    # Keep real curl's transfer, timeout, status and output-file behavior.
    sys.exit(subprocess.run([os.environ["E2E_CURL"], *args, "--noproxy", "*"],
                            input=config.encode()).returncode)
elif name == "fbink":
    source = Path(args[-1].removeprefix("file="))
    with Image.open(source) as image:
        image.load()
    if os.environ.get("E2E_DRAW_FAIL") == "1" and source.name == "next.png":
        sys.exit(1)
    (root / "display.png").write_bytes(source.read_bytes())
elif name == "lipc-get-prop":
    print("7")
elif name == "lipc-set-prop":
    pass
else:
    sys.exit(91)
