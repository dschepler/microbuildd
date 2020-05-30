import asyncio

async def _shield_and_wait_body(coro, finish_event):
    try:
        await coro
    finally:
        finish_event.set()

async def shield_and_wait(coro):
    finish_event = asyncio.Event()
    task = asyncio.shield(_shield_and_wait_body(coro, finish_event))
    try:
        await task
    except asyncio.CancelledError:
        await finish_event.wait()
        raise

def shield_and_wait_decorator(coro_fn):
    return lambda *args, **kwargs: shield_and_wait(coro_fn(*args, **kwargs))
