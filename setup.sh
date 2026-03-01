#!/bin/bash

echo "=== 1. 시스템 패키지 업데이트 및 필수 라이브러리 설치 ==="
sudo apt-get update
sudo apt-get install -y libzbar0 libatlas-base-dev

echo "=== 2. 가상환경 생성 (없을 경우) ==="
if [ ! -d "myenv" ]; then
    python3 -m venv myenv
    echo "가상환경(myenv) 생성 완료"
fi

echo "=== 3. 가상환경 활성화 및 파이썬 패키지 설치 ==="
source myenv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 4. 설정 파일 확인 ==="
if [ ! -f ".env" ]; then
    echo "[경고] .env 파일이 없습니다. .env.template을 복사하여 .env를 생성합니다."
    cp .env.template .env
    echo ".env 파일을 열어 실제 설정값으로 수정해주세요!"
else
    echo "설정 완료! 실행하려면 다음 명령어를 입력하세요:"
    echo "source myenv/bin/activate"
    echo "python entrance_worker.py"
fi