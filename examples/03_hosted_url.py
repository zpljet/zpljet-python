"""Host the rendered PDF and get a public URL back (paid plans).

Run: ZPLJET_API_KEY=zpl_… python examples/03_hosted_url.py
"""

import os

from zpljet import PermissionDeniedError, ZplJet

zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])

try:
    hosted = zpljet.convert(
        zpl="^XA^FO50,50^A0N,50,50^FDHosted label^FS^XZ",
        output="url",
    )
    print(f"URL:      {hosted.url}")
    print(f"Pages:    {hosted.pages}")
    print(f"Retained: {hosted.retention_days} days (deleted {hosted.expires_at})")
except PermissionDeniedError as err:
    print(f"Hosting not available on this plan: {err.message}")
