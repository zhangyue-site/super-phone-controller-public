#!/usr/bin/env python3
"""Private SSH publisher. The requested source commit must be a JSON first line.
Wire format: {"source":"<40 hex>","generation":123}\n followed by raw ESP app image.
A restricted SSH key can run only this command, never a caller-supplied shell.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from display_service.firmware import publish

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--device',required=True);p.add_argument('--activate',action='store_true')
 args=p.parse_args()
 header=sys.stdin.buffer.readline(256)
 if not header.endswith(b'\n'):raise SystemExit('invalid publish header')
 metadata=json.loads(header);source=metadata['source'];generation=metadata.get('generation',0);data=sys.stdin.buffer.read(0x340001)
 entry=publish(args.device,data,source,activate=args.activate,generation=generation)
 print(json.dumps(dict(entry,activated=args.activate,device=args.device)))
if __name__=='__main__':main()
