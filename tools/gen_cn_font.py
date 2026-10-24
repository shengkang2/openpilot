#!/usr/bin/env python3
"""为 openpilot UI 生成中文位图字库（BMFont 格式 .fnt + .png）。

用 NotoSansSC 渲染 po 里实际出现的全部字符，输出多种字重的 .fnt/.png 对，
供 font_fallback 在中文语言下使用，替代粗糙的 16px unifont 点阵。

BMFont 文本格式要点（raylib 的 LoadFont 能直接读）：
  info/common/page/chars 四段，char 行字段：
  id x y w h xoffset yoffset xadvance page chnl

为什么是 80px 而不是更小：
  Inter 图集基准 200px，UI 实际只用 40~85px（缩小 → 清晰）；
  原 48px 中文字库在 UI 里被放大到 55~75px，非整数倍放大必然模糊。
  BMFont 位图字库的 info size 要接近 UI 实际最大渲染尺寸，宁大勿小。
"""
import argparse
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# 字重 → 字体文件名模板（NotoSansSC 家族）。找不到就用 Regular 兜底。
FONT_CANDIDATES = {
    'Regular': ['NotoSansSC-Regular.otf', 'Noto Sans SC (TrueType).otf'],
    'Medium': ['NotoSansSC-Medium.otf', 'Noto Sans SC Medium (TrueType).otf'],
    'SemiBold': ['NotoSansSC-SemiBold.otf', 'Noto Sans SC Medium (TrueType).otf'],
    'Bold': ['NotoSansSC-Bold.otf', 'Noto Sans SC Bold (TrueType).otf'],
}

# Medium/SemiBold/Bold 用描边加粗，Regular/SemiBold 用 0。
# 注意：SemiBold 与 Medium 共用同一份 Noto Sans SC Medium 文件，靠描边区分层级。
STROKES = {'Regular': 0, 'Medium': 0, 'SemiBold': 1, 'Bold': 1}

# 候选字体搜索目录（设备 /usr/share/fonts 与 PC 字体目录）
FONT_DIRS = [
    '/usr/share/fonts',
    '/usr/share/fonts/truetype',
    '/usr/local/share/fonts',
    os.path.expanduser('~/.fonts'),
    'C:/Windows/Fonts',
]


def find_font(weight: str) -> str:
    """按字重找到字体文件，找不到就退回 Regular，再找不到就报错。"""
    names = FONT_CANDIDATES.get(weight, []) + FONT_CANDIDATES['Regular']
    for name in names:
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return ''


def collect_chars(po_path: str):
    """收集 po 全文出现的所有字符，加 ASCII 基本集。

    直接扫整个文件，不做 msgid/msgstr 区分：
    gettext 的复数形式写作 `msgstr[0] "{} 分钟前"`，按 `msgstr ` 前缀精细解析
    很容易漏掉（曾因此漏了「钟」，界面上显示成「7 分 前」）。
    全量扫描只会多收几个字符，代价可忽略。
    """
    chars = set(chr(i) for i in range(0x20, 0x7F))
    with open(po_path, encoding='utf-8') as f:
        text = f.read()
    chars.update(text)
    # 去掉控制字符、换行，以及 BMP 外的字符（emoji 等，字体里通常没有字形）
    return {c for c in chars if c not in '\n\r\t' and ord(c) <= 0xFFFF}


def build_font(chars, size, out_base, font_path, stroke=0):
    """用 PIL 渲染字符到位图，写出 BMFont .fnt + .png。"""
    font = ImageFont.truetype(font_path, size)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent

    # 逐字量尺寸
    glyphs = []
    for ch in sorted(chars, key=ord):
        try:
            bbox = font.getbbox(ch, stroke_width=stroke)
        except Exception:
            continue
        if bbox is None:
            continue
        w = max(bbox[2] - bbox[0], 0)
        h = max(bbox[3] - bbox[1], 0)
        adv = int(round(font.getlength(ch)))
        if w == 0 or h == 0:
            # 空白字符也保留，给个最小占位
            glyphs.append((ord(ch), 0, 0, 0, 0, 0, 0, adv))
        else:
            glyphs.append((ord(ch), w, h, bbox[0], bbox[1], adv))

    # 简单货架打包
    PAD = 2
    MAXW = 2048
    x = PAD
    y = PAD
    row_h = 0
    placed = []
    for g in glyphs:
        cid, w, h = g[0], g[1], g[2]
        if w == 0:
            placed.append((g, 0, 0))
            continue
        if x + w + PAD > MAXW:
            x = PAD
            y += row_h + PAD
            row_h = 0
        placed.append((g, x, y))
        x += w + PAD
        row_h = max(row_h, h)
    atlas_h = y + row_h + PAD
    atlas_h = max(atlas_h, 16)

    img = Image.new('RGBA', (MAXW, atlas_h), (255, 255, 255, 0))
    # BMFont 常规做法：白字透明底；raylib 会拿 alpha 当字形覆盖
    draw = ImageDraw.Draw(img)

    for g, gx, gy in placed:
        cid, w, h = g[0], g[1], g[2]
        if w == 0:
            continue
        ch = chr(cid)
        bbox = font.getbbox(ch, stroke_width=stroke)
        draw.text((gx - bbox[0], gy - bbox[1]), ch, font=font,
                  fill=(255, 255, 255, 255), stroke_width=stroke,
                  stroke_fill=(255, 255, 255, 255))

    png_path = out_base + '.png'
    img.save(png_path)

    # 写 .fnt
    base_size = size
    lines = []
    lines.append('info face="OpFont-zh-CHS" size=%d bold=0 italic=0 charset="" '
                 'unicode=1 stretchH=100 smooth=1 aa=1 padding=0,0,0,0 spacing=0,0 '
                 'outline=%d' % (-base_size, stroke))
    lines.append('common lineHeight=%d base=%d scaleW=%d scaleH=%d pages=1 packed=0 '
                 'alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4'
                 % (line_h, ascent, MAXW, atlas_h))
    lines.append('page id=0 file="%s"' % os.path.basename(png_path))
    lines.append('chars count=%d' % len(placed))
    for g, gx, gy in placed:
        cid, w, h = g[0], g[1], g[2]
        if w == 0:
            adv = g[-1]
            lines.append('char id=%d x=0 y=0 width=0 height=0 xoffset=0 yoffset=0 '
                         'xadvance=%d page=0 chnl=15' % (cid, adv))
            continue
        xoff = g[3]
        yoff = g[4]
        adv = g[5]
        lines.append('char id=%d x=%d y=%d width=%d height=%d xoffset=%d yoffset=%d '
                     'xadvance=%d page=0 chnl=15'
                     % (cid, gx, gy, w, h, xoff, yoff, adv))

    with open(out_base + '.fnt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print(f'  {os.path.basename(out_base)}.fnt  字形 {len(placed)}  图集 {MAXW}x{atlas_h}')
    return len(placed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=80)
    ap.add_argument('--weights', default='Regular,Medium,SemiBold,Bold')
    ap.add_argument('--po', default=None, help='po 文件路径')
    ap.add_argument('--out', default=None, help='字库输出目录')
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    po = args.po or os.path.join(repo, 'selfdrive', 'ui', 'translations', 'app_zh-CHS.po')
    out_dir = args.out or os.path.join(repo, 'selfdrive', 'assets', 'fonts')

    if not os.path.isfile(po):
        print(f'!! po 文件不存在: {po}')
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    chars = collect_chars(po)
    cjk = [c for c in chars if '\u4e00' <= c <= '\u9fff']
    print(f'收集字符 {len(chars)} 个（其中汉字 {len(cjk)}）')

    for w in args.weights.split(','):
        w = w.strip()
        if not w:
            continue
        fp = find_font(w)
        if not fp:
            print(f'!! 找不到 {w} 字体，跳过')
            continue
        out = os.path.join(out_dir, f'Zh-{w}')
        build_font(chars, args.size, out, fp, stroke=STROKES.get(w, 0))


if __name__ == '__main__':
    main()
