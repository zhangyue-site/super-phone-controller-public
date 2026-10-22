#!/usr/bin/env python3
"""USB-only diagnostic loop. No credentials or phone input commands are sent."""
import argparse
import time
import serial
from serial.tools import list_ports


def connect(port=None):
    if not port:
        candidates=[p for p in list_ports.comports()
                    if p.vid==0x303a and p.product=='Epaper Phone Controller']
        if len(candidates)!=1:
            raise SystemExit(f'Expected one controller; found {len(candidates)}. Specify --port.')
        port=candidates[0].device
    device=serial.Serial()
    device.port=port;device.baudrate=115200;device.timeout=.1
    device.dtr=False;device.rts=False;device.open()
    return device


def command(device,text,seconds=2):
    device.write((text+'\n').encode())
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            data=device.read(4096)
        except serial.SerialException:
            print('[USB disconnected; expected for restart/download commands]')
            return
        if data:print(data.decode(errors='replace'),end='',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port')
    parser.add_argument('command',choices=['audio','audio-up','audio-down','audio-mute','audio-test','audio-click','version','status','logs','storage','sdlogs','safe','reboot','bootloader','wifi-on','wifi-off','page','mic-test','watch'])
    parser.add_argument('--seconds',type=float,default=20)
    args=parser.parse_args()
    with connect(args.port) as device:
        if args.command=='watch':
            end=time.monotonic()+args.seconds
            while time.monotonic()<end:
                command(device,'STATUS',.5);command(device,'LOGS',1)
                time.sleep(2)
        else:command(device,args.command.replace('-',' ').upper())

if __name__=='__main__':main()
