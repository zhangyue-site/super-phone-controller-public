"""Run on 106 after deploying the service. Changes only its dedicated nginx include."""
from pathlib import Path
import subprocess
p=Path('/www/server/panel/vhost/nginx/erweima.zhangyue.site.conf')
original=p.read_text()
include='    include /www/server/nginx/conf/phone-controller-location.conf;'
if include not in original:
    backup=p.with_name(p.name+'.bak-phone-controller-20261020')
    if not backup.exists():backup.write_text(original)
    lines=original.splitlines()
    i=next(i for i,line in enumerate(lines) if 'server_name ' in line)
    lines.insert(i+1,include)
    p.write_text('\n'.join(lines)+'\n')
    result=subprocess.run(['/www/server/nginx/sbin/nginx','-t'],capture_output=True,text=True)
    if result.returncode:
        p.write_text(original)
        raise RuntimeError(result.stderr)
    subprocess.run(['/www/server/nginx/sbin/nginx','-s','reload'],check=True)
print('dedicated display route enabled')
