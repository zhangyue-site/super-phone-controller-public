"""Run firmware's platform-independent regression tests with a host C++ compiler."""
from pathlib import Path
import subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    for test in sorted(list((ROOT/'tests').glob('*_test.cpp'))+list((ROOT/'tests').glob('*_test.c'))):
        binary=str(Path(temp)/test.stem)
        compiler,standard=('cc','-std=c11') if test.suffix=='.c' else ('c++','-std=c++17')
        cmd=[compiler,standard,'-I',str(ROOT/'firmware-epaper/main'),str(test)]
        if test.stem=='interaction_test':cmd.append(str(ROOT/'firmware-epaper/main/gesture.cpp'))
        subprocess.run(cmd+['-o',binary],check=True)
        subprocess.run([binary],check=True)
        print(test.name, 'PASS')
