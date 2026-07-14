from PIL import Image, ImageDraw, ImageFilter

S = 1024  # 크게 그린 뒤 축소 → 계단현상 제거
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

def px(v): return int(v * S / 512)

# ── 하늘: 위에서 아래로 그라디언트 (한 줄씩)
top, bot = (242, 247, 236), (203, 220, 194)
for y in range(S):
    t = y / S
    c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    d.line([(0, y), (S, y)], fill=c + (255,))

# ── 해
d.ellipse([px(330 - 54), px(150 - 54), px(330 + 54), px(150 + 54)], fill=(253, 254, 251, 235))

def firs(spec, color):
    for (x, base, top_y, half) in spec:
        d.polygon([(px(x - half), px(base)), (px(x), px(top_y)), (px(x + half), px(base))], fill=color)

# ── 먼 산 (연한 초록)
firs([(100,300,190,40),(165,310,175,45),(242,300,195,42),(325,305,185,45),(402,300,190,42),(470,310,200,40),(38,305,200,38)],
     (179, 203, 175, 255))
# ── 중간
firs([(75,360,215,55),(170,370,205,60),(272,360,220,57),(372,368,210,62),(468,360,225,58)],
     (123, 165, 127, 255))

# ── 안개: 중간층 아래를 부드럽게 덮음
mist = Image.new("RGBA", (S, S), (0, 0, 0, 0))
md = ImageDraw.Draw(mist)
for y in range(px(300), px(430)):
    t = (y - px(300)) / (px(430) - px(300))
    md.line([(0, y), (S, y)], fill=(234, 240, 227, int(150 * t)))
mist = mist.filter(ImageFilter.GaussianBlur(px(8)))
img = Image.alpha_composite(img, mist)
d = ImageDraw.Draw(img)

# ── 가까운 숲
firs([(60,430,250,60),(172,440,240,72),(296,435,255,66),(420,442,245,70),(505,430,260,45)],
     (63, 112, 80, 255))
# ── 가장 앞 (짙은 실루엣)
firs([(55,512,300,75),(205,512,285,85),(355,512,295,80),(500,512,305,78)],
     (37, 73, 47, 255))

# ── 바닥
d.rectangle([0, px(470), S, S], fill=(27, 54, 36, 255))

# ── 원형 마스크
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).ellipse([0, 0, S, S], fill=255)
img.putalpha(mask)

img = img.resize((512, 512), Image.LANCZOS)
img.save("avatar.png")
print("저장 완료:", img.size)
