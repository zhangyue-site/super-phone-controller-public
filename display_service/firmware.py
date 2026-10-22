"""Authenticated, per-device immutable firmware. Never exposed as public downloads."""
import hashlib,json,os,re,threading
_REPORT_LOCK=threading.Lock()
from pathlib import Path
ROOT=Path(os.environ.get('EPAPER_FIRMWARE','/var/lib/phone-controller/firmware'))
def release(device,sha=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device):raise ValueError('device')
    folder=ROOT/device
    if sha is None:
        entry=json.loads((folder/'current.json').read_text())
        sha=entry['sha256']
    else:
        entry=json.loads((folder/(sha+'.json')).read_text()) if re.fullmatch(r'[0-9a-f]{64}',sha) else {}
    if not re.fullmatch(r'[0-9a-f]{64}',sha or '') or entry.get('sha256')!=sha:raise ValueError('hash')
    version=entry['version'];size=entry['size']
    if not re.fullmatch(r'[a-zA-Z0-9._-]{1,31}',version) or type(size)!=int or not 1024<=size<=0x340000:raise ValueError('metadata')
    data=(folder/(sha+'.bin')).read_bytes()
    if len(data)!=size or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('artifact')
    return entry,data

def manifest(device):
    entry,_=release(device)
    return ('PCOTA1\n%d\n%s\n%s\n'%(entry['size'],entry['sha256'],entry['version'])).encode()


def report(device,raw):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device):raise ValueError('device')
    obj=json.loads(raw)
    if not isinstance(obj,dict) or set(obj)!={'version','slot','phase','imageState'}:raise ValueError('fields')
    if not isinstance(obj['version'],str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,31}',obj['version']):raise ValueError('version')
    if obj['slot'] not in ('ota_0','ota_1') or obj['phase'] not in ('boot-confirmed','current','failed'):raise ValueError('state')
    if type(obj['imageState']) is not int or obj['imageState'] not in (-1,0,1,2,3,4,5,6):raise ValueError('image state')
    import time
    obj['receivedAt']=int(time.time())
    folder=ROOT/device;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    # A bounded latest acknowledgement, atomic replacement; no user content.
    with _REPORT_LOCK:
        temp=folder/'report.tmp';temp.write_text(json.dumps(obj));temp.chmod(0o600);temp.replace(folder/'report.json')
    print('OTA report device=%s version=%s slot=%s phase=%s image_state=%d'%(device,obj['version'],obj['slot'],obj['phase'],obj['imageState']),flush=True)
    return obj


def image_version(data):
    """Validate unsigned ESP32-S3 image segments, XOR checksum and appended SHA."""
    import struct
    if not 1024<=len(data)<=0x340000 or data[0]!=0xe9 or not 1<=data[1]<=16 or struct.unpack_from('<H',data,12)[0]!=9:
        raise ValueError('not an ESP32-S3 image')
    if struct.unpack_from('<I',data,32)[0]!=0xabcd5432:raise ValueError('missing app descriptor')
    def field(offset):
        value=data[offset:offset+32].split(b'\0',1)[0].decode('ascii')
        if not re.fullmatch(r'[a-zA-Z0-9._-]{1,31}',value):raise ValueError('descriptor field')
        return value
    version=field(48)
    if field(80)!='phone_controller_epaper':raise ValueError('wrong project')
    offset=24;checksum=0xef
    for _ in range(data[1]):
        if offset+8>len(data):raise ValueError('segment header')
        size=struct.unpack_from('<I',data,offset+4)[0];offset+=8
        if offset+size>len(data):raise ValueError('segment size')
        for byte in data[offset:offset+size]:checksum^=byte
        offset+=size
    end=(offset//16+1)*16
    if end>len(data) or data[end-1]!=checksum:raise ValueError('image checksum')
    if data[23]!=1 or len(data)!=end+32 or hashlib.sha256(data[:end]).digest()!=data[end:]:raise ValueError('image SHA')
    return version


def publish(device,data,source,activate=False,generation=0):
    """SSH/CLI-only publishing; no public upload route. Stage unless activated."""
    import fcntl,tempfile,time
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device):raise ValueError('device')
    if not re.fullmatch(r'[0-9a-f]{40}',source):raise ValueError('source commit')
    if type(generation) is not int or not 0<=generation<2**53:raise ValueError('publish generation')
    version=image_version(data);sha=hashlib.sha256(data).hexdigest()
    entry={'version':version,'sha256':sha,'size':len(data),'source':source,'publishedAt':int(time.time())}
    folder=ROOT/device;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    def atomic(path,blob):
        fd,name=tempfile.mkstemp(prefix='.publish-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as out:out.write(blob);out.flush();os.fsync(out.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)
    with (folder/'.publish.lock').open('a') as lock:
        os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        image=folder/(sha+'.bin');metadata=folder/(sha+'.json')
        if image.exists() and image.read_bytes()!=data:raise ValueError('immutable image mismatch')
        if not image.exists():atomic(image,data)
        if metadata.exists():
            stored=json.loads(metadata.read_text())
            if any(stored.get(k)!=entry[k] for k in ('version','sha256','size')):raise ValueError('immutable metadata mismatch')
            entry=stored
        else:atomic(metadata,json.dumps(entry).encode())
        release(device,sha)
        if activate:
            current=folder/'current.json'
            previous=json.loads(current.read_text()) if current.exists() else {}
            previous_generation=previous.get('activationGeneration',0)
            if previous_generation>0 and generation<=previous_generation and previous.get('sha256')!=sha:raise ValueError('stale cloud build')
            entry=dict(entry,activationGeneration=max(generation,previous_generation))
            if current.exists() and json.loads(current.read_text()).get('sha256')!=sha:atomic(folder/'previous.json',current.read_bytes())
            atomic(current,json.dumps(entry).encode())
    return entry
