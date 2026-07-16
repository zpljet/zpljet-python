"""Render a 300 dpi PNG preview of a 4x6" shipping label.

Run: ZPLJET_API_KEY=zpl_… python examples/02_convert_to_png.py
"""

import os
from pathlib import Path

from zpljet import ZplJet

zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])

label = zpljet.convert(
    zpl=(
        "^XA"
        "^FO40,40^A0N,60,60^FDACME Logistics^FS"
        "^FO40,130^BY3^BCN,120,Y,N,N^FD123456789012^FS"
        "^XZ"
    ),
    format="png",
    dpmm=12,  # 300 dpi
    width_mm=101.6,
    height_mm=152.4,
)

Path("label.png").write_bytes(label.data)
print(f"Saved label.png ({len(label.data)} bytes)")
