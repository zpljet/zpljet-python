"""Convert a batch of labels concurrently with AsyncZplJet, bounded by a
semaphore so you stay under your plan's per-second rate limit (the SDK still
auto-retries any 429s).

Run: ZPLJET_API_KEY=zpl_… python examples/05_async_batch.py
"""

import asyncio
import os
from pathlib import Path

from zpljet import AsyncZplJet

zpljet = AsyncZplJet(api_key=os.environ["ZPLJET_API_KEY"], max_retries=5)

ORDERS = ["A-1001", "A-1002", "A-1003", "A-1004", "A-1005", "A-1006"]
CONCURRENCY = 2  # match your plan's rate limit


async def render_order(order_id: str, limiter: asyncio.Semaphore) -> None:
    async with limiter:
        label = await zpljet.convert(
            zpl=(
                f"^XA^FO40,40^A0N,50,50^FDOrder {order_id}^FS"
                f"^FO40,120^BY3^BCN,100,Y,N,N^FD{order_id}^FS^XZ"
            )
        )
        Path(f"{order_id}.pdf").write_bytes(label.data)
        print(f"✓ {order_id}.pdf")


async def main() -> None:
    limiter = asyncio.Semaphore(CONCURRENCY)
    await asyncio.gather(*(render_order(order, limiter) for order in ORDERS))
    print(f"Done — {len(ORDERS)} labels rendered.")


asyncio.run(main())
