from __future__ import annotations

import argparse
import time

from .channel_runner import run_once


def process_once() -> int:
    return run_once(channel_id="local_jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local JSONL message chat gateway")
    parser.add_argument("--once", action="store_true", help="process inbox once and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")
    args = parser.parse_args()

    if args.once:
        count = process_once()
        print(f"Processed messages: {count}")
        return

    print("Message chat gateway running. Press Ctrl+C to stop.")
    try:
        while True:
            count = process_once()
            if count:
                print(f"Processed messages: {count}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
