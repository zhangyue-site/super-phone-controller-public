"""Server-only interaction state writer. Execution evidence comes from the current board turn."""
import argparse,json,os,tempfile,time
from pathlib import Path

STATES=frozenset(('idle','listening','thinking','running','waiting','done','error','stopped'))
ROOT=Path(os.environ.get('EPAPER_STATE','/var/lib/phone-controller'))


def read(device):
    try:
        data=json.loads((ROOT/(device+'.json')).read_text())
        if data.get('state') in ('listening','thinking','running') and time.time()-data.get('updatedAt',0)>60:
            data.update(state='error',task='交互状态更新超时，请检查服务器执行器')
        return data
    except (OSError,ValueError):return {}


def write(device,state,task='',phone='',step=0):
    if state not in STATES or not device or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in device):
        raise ValueError('invalid device or state')
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(dir=ROOT)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump({'state':state,'task':task[:120],'phone':phone[:24],'step':max(0,int(step)),
                       'updatedAt':int(time.time())},f,ensure_ascii=False)
        os.replace(tmp,ROOT/(device+'.json'))
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('device');p.add_argument('--state',choices=sorted(STATES),required=True)
    p.add_argument('--task',default='');p.add_argument('--phone',default='');p.add_argument('--step',default=0,type=int)
    args=p.parse_args();write(args.device,args.state,args.task,args.phone,args.step)

if __name__=='__main__':main()
