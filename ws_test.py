import asyncio
import websockets

async def test():
    uri = "wss://yard-ladies-nuclei.ngrok-free.dev/ws/tata-tele"
    async with websockets.connect(uri) as ws:
        print("✅ Connected")

        # send dummy bytes
        await ws.send(b"hello")
        print("📤 sent")

        # try to receive (optional)
        try:
            msg = await ws.recv()
            print("📥 received:", msg)
        except:
            print("No response (ok for now)")

asyncio.run(test())