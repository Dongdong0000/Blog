"""
사이드바 아바타 생성기.
원본에서 얼굴 중심으로 정사각 크롭 -> 256px PNG.

  python3 avatar-crop.py

- Stack 은 아바타를 최대 120px 로 표시하므로 256px 이면 레티나까지 충분합니다.
- 원형은 CSS(border-radius:100%)가 씌우므로 여기서는 정사각으로 저장합니다.
- 얼굴 위치를 옮기려면 CX, CY 를, 당기고/밀려면 S 를 조정하세요 (원본 좌표 기준).
"""
from PIL import Image

SRC = "Flux2_dev_00004_.png"
OUT = "avatar.png"
CX, CY, S = 1280, 375, 690   # 얼굴 중심(1280,375), 한 변 690px

src = Image.open(SRC).convert("RGB")
W, H = src.size
half = S // 2
l = max(0, min(CX - half, W - S))
t = max(0, min(CY - half, H - S))
crop = src.crop((l, t, l + S, t + S)).resize((256, 256), Image.LANCZOS)
crop.convert("P", palette=Image.ADAPTIVE, colors=256).save(OUT, optimize=True)
print(f"{OUT} 저장 완료 (크롭 {l},{t} ~ {l+S},{t+S})")
