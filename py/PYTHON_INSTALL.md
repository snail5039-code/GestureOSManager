# Python 한 번에 설치/실행 (AI Server)

## 1) 가상환경 생성 + 활성화
### Windows PowerShell
```powershell
cd <ai-server 폴더>
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

### macOS / Linux / WSL
```bash
cd <ai-server 폴더>
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

## 2) 의존성 한 번에 설치
### CPU 환경(기본)
```bash
pip install -r requirements.txt
```

### GPU(CUDA 12.1 예시)
```bash
pip install -r requirements-gpu-cu121.txt
```

## 3) 서버 실행(FastAPI 예시)
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 4) 설치가 꼬였을 때(클린 재설치)
```bash
pip freeze > requirements.lock.txt
pip uninstall -y -r requirements.lock.txt
pip install -r requirements.txt
```
