#!/usr/bin/env python3
"""Bundle an existing UTF-8 cloud Skill as non-executable reference data."""
import argparse,hashlib,json,os
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('source',type=Path)
 p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'firmware-epaper/main/device_skill_cache.h')
 args=p.parse_args();raw=args.source.read_bytes()
 if not 0<len(raw)<=32768:raise SystemExit('Skill snapshot must be 1..32768 bytes')
 text=raw.decode('utf-8');digest=hashlib.sha256(raw).hexdigest()
 fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:
  f.write('#pragma once\nstatic const char cached_skill[]='+json.dumps(text,ensure_ascii=False)+';\n')
  f.write('static const char cached_skill_sha[]="'+digest+'";\n')
 print(f'Reference snapshot: {len(raw)} bytes; SHA256 {digest}')
if __name__=='__main__':main()
