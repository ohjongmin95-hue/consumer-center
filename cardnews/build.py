"""민주의 카드뉴스 제작 프로그램: 더블클릭 실행 파일 만들기 (PyInstaller). 만드는 컴퓨터의 운영체제용 파일이 나온다.

  윈도우 → dist/MinjuCardNews.exe 하나 (Python 설치 없이 실행) ← 쓰는 사람들은 모두 윈도우
  맥     → dist/MinjuCardNews.app (→ dist/MinjuCardNews-mac.zip)
  리눅스 → dist/MinjuCardNews (시험용)

평소에는 GitHub Actions(.github/workflows/cardnews-build.yml)가 윈도우 exe를 만들어 Releases의 'cardnews-latest'에 올린다.
직접 만들려면: pip install -r requirements.txt pyinstaller pillow && python build.py
"""
import os, platform, shutil, subprocess, sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).resolve().parent
NAME = 'MinjuCardNews'
os.chdir(HERE)
sep = os.pathsep
args = ['server.py', '--name', NAME, '--noconfirm', '--clean', '--icon', 'static/app-icon.png',
        f'--add-data=templates{sep}templates', f'--add-data=static{sep}static', '--collect-data', 'certifi']
system = platform.system()
if system == 'Darwin': args += ['--windowed', '--osx-bundle-identifier', 'kr.soboru.cardnews']  # .app (검은 창 없이)
elif system == 'Windows': args += ['--onefile', '--windowed']  # exe 하나 (검은 창 없이)
else: args += ['--onefile']
PyInstaller.__main__.run(args)

if system == 'Darwin':  # .app은 폴더라 zip으로 묶어 내려받기 쉽게
    out = HERE / 'dist' / f'{NAME}-mac.zip'
    out.unlink(missing_ok=True)
    subprocess.run(['ditto', '-c', '-k', '--keepParent', f'dist/{NAME}.app', str(out)], check=True)
shutil.rmtree(HERE / 'build', ignore_errors=True)
print('\n만들었어요:', *sorted(p.name for p in (HERE / 'dist').iterdir()), file=sys.stderr)
