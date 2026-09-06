"""Render the three service deliverables from customer-approved text, without an API.

Example: python scripts/render_team_cards.py --input docs/team_cards_sample.json
  --font C:/Windows/Fonts/meiryo.ttc --out-dir build/customer-private/order-001
Keep customer input and output in build/ (ignored by git), never web/.
"""
import argparse
import json
import re
from pathlib import Path


def render(data, font_path, output):
    from PIL import Image, ImageDraw, ImageFont

    required = ("team", "opponent", "date", "time", "venue", "score",
                "next_opponent", "next_date", "next_time", "next_venue")
    for key in required:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key}: text is required")
        if len(data[key]) > 70 or any(c in data[key] for c in "\n\r\t"):
            raise ValueError(f"{key}: use one short line, up to 70 characters")
    accent = data.get("accent", "#64D8C5")
    if not isinstance(accent, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise ValueError("accent must be a #RRGGBB color")
    if type(data.get("sample", True)) is not bool:
        raise ValueError("sample must be true or false")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for kind, number, heading, date, time, venue, opponent in (
        ("announcement", "01", "MATCH DAY", data["date"], data["time"], data["venue"], data["opponent"]),
        ("result", "02", "FULL TIME", data["date"], "試合終了", data["venue"], data["opponent"]),
        ("next", "03", "NEXT MATCH", data["next_date"], data["next_time"], data["next_venue"], data["next_opponent"]),
    ):
        img = Image.new("RGB", (1080, 1350), "#0B0E14")
        draw = ImageDraw.Draw(img)

        def text(value, xy, size, fill="#F2F0E6", width=920):
            while size >= 22:
                font = ImageFont.truetype(str(font_path), size)
                if draw.textbbox((0, 0), value, font=font)[2] <= width:
                    draw.text(xy, value, font=font, fill=fill, anchor="lt")
                    return
                size -= 1
            raise ValueError(f"Text is too wide for this design: {value}")

        # Native geometric artwork; no team logos or third-party photos.
        for x in range(600, 1300, 100):
            draw.line([(x, 0), (x - 550, 1350)], fill="#151E2A", width=2)
        draw.rectangle((0, 0, 16, 1350), fill=accent)
        text("COLLESPO / TEAM GRAPHICS", (80, 72), 25, accent)
        text(number, (876, 68), 45, accent, 130)
        draw.line((80, 147, 1000, 147), fill="#303A4B", width=2)
        text(heading, (80, 206), 91)
        text("試合結果" if kind == "result" else "次回の試合" if kind == "next" else "試合のお知らせ", (84, 330), 28, "#B0B9C8")
        if kind == "result":
            text(data["score"], (80, 444), 222, accent)
            text(data["team"], (84, 748), 59)
            text("vs  " + opponent, (84, 847), 43, "#B0B9C8")
        else:
            text(date, (80, 458), 122, accent)
            text(time, (86, 632), 48)
            text(data["team"], (84, 786), 59)
            text("vs  " + opponent, (84, 884), 43, "#B0B9C8")
        draw.line((80, 1028, 1000, 1028), fill="#303A4B", width=2)
        text(date + " / " + time if kind == "result" else "会場", (84, 1070), 27, "#B0B9C8")
        text(venue, (84, 1129), 37)
        if data.get("sample", True):
            text("制作見本 / 架空のチーム・試合です", (84, 1260), 25, "#B0B9C8")
        img.save(out / f"{kind}.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--font", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    render(json.loads(Path(args.input).read_text(encoding="utf-8-sig")), args.font, args.out_dir)
    print("Created 3 PNG files (1080 x 1350). Review the text before delivery.")


if __name__ == "__main__":
    main()
