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

class EarlyDisconnect(Exception):
    """Client closed the upload before the final chunk; data read so far is in args[0]."""

def read_chunks_tolerant(stream, on_chunk=lambda size: None):
    """read_chunks, but a client that stops mid-upload raises EarlyDisconnect with the
    partial payload instead of ValueError. Complete chunks already consumed are kept,
    so the caller can still recognize what was said (xiaozhi-esp32 tolerance model)."""
    raw=bytearray();deadline=time.monotonic()+25
    while True:
        if time.monotonic()>deadline:raise EarlyDisconnect(bytes(raw))
        try:
            line=stream.readline(64)
        except OSError:
            raise EarlyDisconnect(bytes(raw))
        if not line:raise EarlyDisconnect(bytes(raw))
        if not line.endswith(b'\r\n') or len(line)>16:raise ValueError('invalid chunk header')
        try:size=int(line.strip(),16)
        except ValueError:raise ValueError('invalid chunk size')
        if size<0 or size>320000 or len(raw)+size>320000:raise ValueError('audio too large')
        if size==0:
            if stream.read(2)!=b'\r\n':raise ValueError('trailers unsupported')
            break
        chunk=stream.read(size)
        if len(chunk)!=size:
            raw.extend(chunk);raise EarlyDisconnect(bytes(raw))
        try:
            follow=stream.read(2)
        except OSError:
            raw.extend(chunk);raise EarlyDisconnect(bytes(raw))
        if follow!=b'\r\n':
            raw.extend(chunk);raise EarlyDisconnect(bytes(raw))
        raw.extend(chunk);on_chunk(len(raw))
    return bytes(raw)
