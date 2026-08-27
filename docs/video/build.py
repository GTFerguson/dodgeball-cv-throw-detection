"""Embed the deck's images and sounds as data URIs so docs/video/deck.html is one portable file."""
import base64, pathlib, sys
here = pathlib.Path(__file__).parent
assets = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else here / "assets"
html = (here / "deck.src.html").read_text()
def uri(name, mime):
    return f"data:{mime};base64," + base64.b64encode((assets / name).read_bytes()).decode()
import re
for key in sorted(set(re.findall(r"__(IMG|SND)_([A-Z0-9_]+)__", html))):
    kind, name = key
    if kind == "SND":
        ext, mime = "mp3", "audio/mpeg"
    elif (assets / f"{name.lower()}.png").exists():
        ext, mime = "png", "image/png"
    else:
        ext, mime = "jpg", "image/jpeg"
    html = html.replace(f"__{kind}_{name}__", uri(f"{name.lower()}.{ext}", mime))
left = re.findall(r"__(?:IMG|SND)_[A-Z0-9_]+__", html)
assert not left, f"unresolved placeholders: {left}"
(here / "deck.html").write_text(html)
print("deck.html", len(html) // 1024, "KB")
