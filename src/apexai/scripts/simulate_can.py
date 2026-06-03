#!/usr/bin/env python3
"""
CAN SLCAN USB Simulator Server
Streams raw CANable serial byte chunks from a file over a TCP port to emulate a CANable 2.0 device.
Supports precise timing, variable speeds, and endless looping.
"""

import argparse
import os
import socket
import sys
import time
from typing import List, Tuple


def parse_log_file(file_path: str) -> List[Tuple[float, bytes]]:
    """
    Parses a raw chunk log file of the format:
        <timestamp_ms>,<space-separated serial bytes as hex>

    Returns a list of (timestamp_ms, raw_chunk_bytes) tuples.
    """
    print(f"Loading and parsing raw serial chunks from '{file_path}'...")
    chunks = []
    
    if not os.path.exists(file_path):
        print(f"Error: Log file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    count = 0
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            count += 1
            line = line.strip()
            if not line or "," not in line:
                continue
            
            try:
                ts_str, hex_chunk = line.split(",", 1)
                timestamp_ms = float(ts_str)
                raw_bytes = bytes(int(part, 16) for part in hex_chunk.split())
                if raw_bytes:
                    chunks.append((timestamp_ms, raw_bytes))
            except ValueError:
                # Silently skip malformed lines
                continue

    print(f"Loaded {len(chunks)} valid raw serial chunks out of {count} lines.")
    return chunks


def run_server(bind_ip: str, port: int, log_file: str, speed: float, loop: bool, verbose: bool):
    """
    Starts the TCP server and streams frames to connected clients.
    """
    # Parse the chunks first to keep memory footprint clean before starting socket
    chunks = parse_log_file(log_file)
    if not chunks:
        print("Error: No valid raw serial chunks found in the log file.", file=sys.stderr)
        sys.exit(1)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Enable address reuse so we don't get "Address already in use" errors on restart
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((bind_ip, port))
        server_socket.listen(1)
        print(f"\nSimulator server listening on {bind_ip}:{port}")
        print(f"Playback Speed: {'Real-time (1.0x)' if speed == 1.0 else f'{speed}x' if speed > 0 else 'Maximum (no delays)'}")
        print(f"Loop Mode: {'Enabled' if loop else 'Disabled'}")
        print(f"To connect your Android device, run: adb reverse tcp:{port} tcp:{port}")
        print("Waiting for client connection...\n")
    except Exception as e:
        print(f"Error starting server on {bind_ip}:{port}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        while True:
            client_socket, client_addr = server_socket.accept()
            print(f"Client connected: {client_addr[0]}:{client_addr[1]}")
            
            try:
                # Playback loop
                while True:
                    start_time = time.time()
                    first_chunk_ts = chunks[0][0]
                    sent_count = 0
                    
                    for index, (ts, chunk) in enumerate(chunks):
                        # Calculate exact target sleep time to match log timings
                        if speed > 0.0 and index > 0:
                            # How many seconds in log-time have elapsed since the first chunk
                            elapsed_log_sec = (ts - first_chunk_ts) / 1000.0
                            # Target real-world absolute time for this chunk
                            target_time = start_time + (elapsed_log_sec / speed)
                            
                            # Sleep until target time
                            sleep_dur = target_time - time.time()
                            if sleep_dur > 0:
                                time.sleep(sleep_dur)
                        
                        # Send the exact raw serial bytes captured by the mobile app.
                        client_socket.sendall(chunk)
                        sent_count += 1
                        
                        if verbose and sent_count % 100 == 0:
                            print(f" -> Sent {sent_count} chunks... Current: {chunk.hex(' ').upper()}")
                        elif sent_count % 2000 == 0:
                            print(f"Sent {sent_count}/{len(chunks)} chunks...")
                            
                    print(f"Finished streaming all {sent_count} chunks.")
                    if not loop:
                        break
                    print("Looping back to start of log...")
                    
            except (socket.error, ConnectionResetError, BrokenPipeError) as e:
                print(f"Client disconnected: {e}")
            finally:
                try:
                    client_socket.close()
                except Exception:
                    pass
                print("Waiting for new client connection...\n")
                
    except KeyboardInterrupt:
        print("\nStopping simulator server.")
    finally:
        server_socket.close()


def main():
    parser = argparse.ArgumentParser(
        description="Emulates CANable 2.0 SLCAN USB serial byte chunks by serving a raw chunk log over TCP."
    )
    parser.add_argument(
        "file",
        type=str,
        nargs="?",
        default="mobile/telemetry_pull/can_raw_hex_chunks.txt",
        help="Path to the raw serial hex chunk log file (default: mobile/telemetry_pull/can_raw_hex_chunks.txt)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8080,
        help="TCP port to listen on (default: 8080)"
    )
    parser.add_argument(
        "-b", "--bind",
        type=str,
        default="127.0.0.1",
        help="IP address to bind the server to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "-s", "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier. E.g. 2.0 = double speed, 0.5 = half speed, 0 = maximum speed without delays (default: 1.0)"
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="Disable infinite looping (stop after streaming the log file once)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print every 100th chunk sent to stdout for debugging"
    )
    
    args = parser.parse_args()
    
    # Resolve relative paths in case script is run from different working directories
    log_file = args.file
    if not os.path.isabs(log_file):
        # Check standard locations
        possible_paths = [
            log_file,
            os.path.join(os.path.dirname(__file__), "..", log_file),
            os.path.join(os.path.dirname(__file__), log_file),
        ]
        resolved = False
        for path in possible_paths:
            if os.path.exists(path):
                log_file = os.path.abspath(path)
                resolved = True
                break
        if not resolved:
            # Let standard parser print error
            pass

    run_server(
        bind_ip=args.bind,
        port=args.port,
        log_file=log_file,
        speed=args.speed,
        loop=not args.no_loop,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
