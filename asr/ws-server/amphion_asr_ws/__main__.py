from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import signal

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from . import __version__
from .manifest import load_manifest
from .metrics import start_metrics_server
from .recognizer import build_recognizer
from .scheduler import DecodeScheduler
from .session import StreamingSession

LOG = logging.getLogger(__name__)


def parse_addr(value: str) -> tuple[str, int]:
    host, port_text = value.rsplit(":", 1)
    return host, int(port_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amphion streaming ASR WebSocket service")
    parser.add_argument("--listen", default="0.0.0.0:8010", help="WebSocket listen address")
    parser.add_argument("--metrics-listen", default="0.0.0.0:9100", help="Prometheus metrics address")
    parser.add_argument("--manifest", required=True, help="Path to server-side model manifest")
    parser.add_argument("--provider", default="cpu", choices=["cpu", "cuda", "coreml"], help="sherpa-onnx provider")
    parser.add_argument("--num-threads", type=int, default=4, help="sherpa-onnx CPU threads")
    parser.add_argument("--max-batch-size", type=int, default=50, help="Max decode batch size")
    parser.add_argument("--max-wait-ms", type=float, default=10.0, help="Max wait time to form a decode batch")
    parser.add_argument("--nn-pool-size", type=int, default=1, help="Decode worker pool size")
    parser.add_argument("--max-active-connections", type=int, default=100, help="Max concurrent WS sessions")
    parser.add_argument("--session-idle-timeout-sec", type=float, default=300.0, help="Idle session timeout")
    parser.add_argument("--debug", action="store_true", help="Enable sherpa debug logging")
    parser.add_argument("--log-level", default="INFO", help="Python log level")
    return parser


async def amain(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    prefer_fp32 = args.provider == "cuda"
    manifest = load_manifest(Path(args.manifest), prefer_fp32=prefer_fp32)
    recognizer = build_recognizer(manifest, provider=args.provider, num_threads=args.num_threads, debug=args.debug)
    scheduler = DecodeScheduler(
        recognizer,
        max_wait_ms=args.max_wait_ms,
        max_batch_size=args.max_batch_size,
        nn_pool_size=args.nn_pool_size,
    )
    scheduler.start()
    start_metrics_server(args.metrics_listen)

    active_sem = asyncio.Semaphore(args.max_active_connections)

    async def handler(connection: ServerConnection) -> None:
        if active_sem.locked():
            await connection.close(code=1013, reason="too many active ASR sessions")
            return
        async with active_sem:
            session = StreamingSession(
                connection,
                recognizer=recognizer,
                manifest=manifest,
                scheduler=scheduler,
                session_idle_timeout_sec=args.session_idle_timeout_sec,
            )
            await session.run()

    def process_request(connection: ServerConnection, request: Request) -> Response | None:
        if request.path == "/healthz":
            body = (
                f"ok\nversion={__version__}\nmodel_id={manifest.model_id}\n"
                f"provider={args.provider}\nqueue_depth={scheduler.queue_depth()}\n"
            ).encode("utf-8")
            return Response(200, "OK", Headers({"Content-Type": "text/plain; charset=utf-8"}), body)
        return None

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    host, port = parse_addr(args.listen)
    LOG.info(
        "starting ASR WS service listen=%s manifest=%s model_id=%s provider=%s max_batch_size=%s",
        args.listen,
        args.manifest,
        manifest.model_id,
        args.provider,
        args.max_batch_size,
    )
    async with serve(handler, host, port, process_request=process_request, max_size=None):
        await stop_event.wait()
    await scheduler.close()


def main() -> None:
    parser = build_parser()
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
