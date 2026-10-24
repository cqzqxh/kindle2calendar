"""Geometric monochrome weather symbols, rendered without emoji fonts."""
import math

from PIL import Image, ImageDraw, ImageFilter


def weather_icon(code, size=56):
    scale = 4
    image = Image.new("L", (64 * scale, 64 * scale), 255)
    draw = ImageDraw.Draw(image)

    def box(coords):
        return tuple(round(value * scale) for value in coords)

    def line(points, width=2.5):
        draw.line([tuple(round(value * scale) for value in point) for point in points],
                  fill=0, width=round(width * scale))

    def sun(cx, cy, radius):
        draw.ellipse(box((cx-radius, cy-radius, cx+radius, cy+radius)),
                     fill=255, outline=0, width=round(2.5 * scale))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            line([(cx + math.cos(radians) * distance, cy + math.sin(radians) * distance)
                  for distance in (radius + 4, radius + 9)])

    def cloud():
        mask = Image.new("L", image.size, 0)
        pen = ImageDraw.Draw(mask)
        for coords in [(7, 23, 33, 46), (21, 13, 47, 44), (37, 24, 59, 46)]:
            pen.ellipse(box(coords), fill=255)
        pen.rectangle(box((19, 31, 49, 46)), fill=255)
        # The union has one continuous outline, without overlapping circle seams.
        image.paste(0, (0, 0), mask)
        image.paste(255, (0, 0), mask.filter(ImageFilter.MinFilter(21)))

    def snowflake(cx, cy, radius=4):
        for angle in (0, 60, 120):
            radians = math.radians(angle)
            dx, dy = math.cos(radians)*radius, math.sin(radians)*radius
            line([(cx-dx, cy-dy), (cx+dx, cy+dy)], 1.8)

    if code == 0:
        sun(32, 32, 13)
    elif code in (1, 2):
        sun(18, 18, 7)
        cloud()
    elif code == 3:
        cloud()
    elif code in (45, 48):
        cloud()
        line([(10, 53), (54, 53)])
        line([(16, 60), (48, 60)])
    elif code in (51, 53, 55):
        cloud()
        for x, y in [(19, 54), (33, 58), (47, 54)]:
            draw.ellipse(box((x-1.7, y-1.7, x+1.7, y+1.7)), fill=0)
    elif code in (56, 57, 66, 67):
        cloud()
        line([(20, 51), (16, 60)])
        snowflake(42, 56)
    elif code in (61, 63, 65, 80, 81, 82):
        cloud()
        for x in (20, 34, 48):
            line([(x, 51), (x-4, 61)])
    elif code in (71, 73, 75, 77, 85, 86):
        cloud()
        snowflake(20, 56)
        snowflake(44, 56)
    elif code in (95, 96, 99):
        cloud()
        draw.polygon([tuple(round(value * scale) for value in point)
                      for point in [(32, 44), (24, 55), (32, 55), (28, 63), (43, 50), (34, 50), (39, 44)]], fill=0)
        if code in (96, 99):
            for x in (16, 51):
                draw.ellipse(box((x-2, 54, x+2, 58)), fill=0)
    else:
        # Unknown conditions get a neutral dash, never a misleading sunny symbol.
        line([(20, 32), (44, 32)], 3)
    return image.resize((size, size), Image.Resampling.LANCZOS)
