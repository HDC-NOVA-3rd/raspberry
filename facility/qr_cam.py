import subprocess
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import time

class QRCam:
    def __init__(self):
        self.process = None
    
    def scan_once(self, timeout=10):
        """
        최대 timeout 초 동안 스캔 시도.
        QR을 찾으면 데이터를 반환, 못 찾으면 None 반환.
        """
        cmd = [
            "rpicam-vid", "-t", "0", "--width", "640", "--height", "480",
            "--codec", "yuv420", "--framerate", "30", "-o", "-", "-n"
        ]
        try:
            # 카메라 프로세스 시작
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)

            start_time = time.time()
            width, height = 640, 480
            frame_size = int(width * height * 1.5)
            
            print("[CAM] 스캔 시작...")
            
            # timeout 초 동안 스캔 유지
            while (time.time() - start_time) < timeout:
                raw_data = self.process.stdout.read(frame_size)
                
                if len(raw_data) != frame_size:
                    continue

                # Raw 데이터를 OpenCV 이미지 포맷(BGR)으로 변환
                # YUV I420 -> BGR 변환 공식 사용
                yuv = np.frombuffer(raw_data, dtype=np.uint8).reshape((int(height * 1.5), width))
                frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

                # QR 디코딩 (pyzbar)
                decoded = decode(frame)
                if decoded:
                    qr_data = decoded[0].data.decode("utf-8")
                    print(f"[CAM] QR 발견: {qr_data}")
                    self.stop()
                    return qr_data
            
            print("[CAM] 시간 초과")
            self.stop()
            return None
        
        except Exception as e:
            print(f"[CAM] 에러: {e}")
            self.stop()
            return None
        
    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None