"""Convert ZPL to a PDF and save it locally.

Run: ZPLJET_API_KEY=zpl_… python examples/01_convert_to_pdf.py
"""

import os
from pathlib import Path

from zpljet import ZplJet

zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])

label = zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello from ZPLJet^FS^XZ")

Path("label.pdf").write_bytes(label.data)
print(f"Saved label.pdf ({len(label.data)} bytes, conversion {label.id})")
