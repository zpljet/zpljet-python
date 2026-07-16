"""Handle every error the API can raise, with typed context fields.

Run: ZPLJET_API_KEY=zpl_… python examples/04_error_handling.py
"""

import os

from zpljet import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ConversionFailedError,
    QuotaExceededError,
    RateLimitError,
    ZplJet,
)

zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])

# Deliberately invalid — there is no ^XA…^XZ block.
bad_zpl = "this is not zpl"

try:
    zpljet.convert(zpl=bad_zpl)
except BadRequestError as err:
    print(f'Invalid request — field "{err.param}": {err.message}')
    print(f"Docs: {err.doc_url}")
except AuthenticationError:
    print("Bad API key — create one at https://zpljet.com/dashboard")
except QuotaExceededError as err:
    print(f"Quota: {err.used}/{err.quota} used, resets {err.resets_at}")
except RateLimitError as err:
    # The SDK already retried with backoff before raising this.
    print(f"Still rate-limited — retry after {err.retry_after}s ({err.retry_at})")
except ConversionFailedError as err:
    print(f"Engine rejected the ZPL — support id: {err.conversion_id}")
except APIConnectionError as err:
    print(f"Network/timeout problem after retries: {err}")
