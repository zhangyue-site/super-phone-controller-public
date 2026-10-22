"""Strict bounded HTTP/1.1 chunk reader; no recording is persisted here."""
import time

def read_chunks(stream, on_chunk=lambda size: None):
    raw=bytearray();deadline=time.monotonic()+25
    while True:
        if time.monotonic()>deadline:raise ValueError('recording timed out')
        line=stream.readline(64)
        if not line.endswith(b'\r\n') or len(line)>16:raise ValueError('invalid chunk header')
        try:size=int(line.strip(),16)
        except ValueError:raise ValueError('invalid chunk size')
        # Reverse proxies may merge the board's 3200-byte writes into one larger chunk.
        if size<0 or size>320000 or len(raw)+size>320000:raise ValueError('audio too large')
        if size==0:
            if stream.read(2)!=b'\r\n':raise ValueError('trailers unsupported')
            break
        chunk=stream.read(size)
        if len(chunk)!=size or stream.read(2)!=b'\r\n':raise ValueError('truncated audio')
        raw.extend(chunk);on_chunk(len(raw))
    return bytes(raw)
