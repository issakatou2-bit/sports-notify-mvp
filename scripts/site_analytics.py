"""設定に応じて公開用HTMLへCookieを使わない解析を追加・除去する。"""
import argparse
import json
import pathlib
import re

START = '<!-- collespo-analytics:start -->'
END = '<!-- collespo-analytics:end -->'


def analytics_script(config="data/site_analytics.json"):
    path = pathlib.Path(config)
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    code = data.get("goatcounter", "").strip()
    if not code:
        return ""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", code):
        raise ValueError("goatcounterにはURLではなく登録したコード名を指定してください")
    return (START + '\n<script data-goatcounter="https://' + code
            + '.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>\n' + END)


def apply_analytics(page, script):
    page = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", page, flags=re.S)
    if script:
        page = re.sub(r"</head\s*>", lambda _: script + '\n</head>', page, count=1, flags=re.I)
    return page


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="public")
    parser.add_argument("--config", default="data/site_analytics.json")
    args = parser.parse_args()
    script = analytics_script(args.config)
    changed = 0
    for path in pathlib.Path(args.site).rglob("*.html"):
        original = path.read_text(encoding="utf-8")
        page = apply_analytics(original, script)
        if page != original:
            path.write_text(page, encoding="utf-8")
            changed += 1
    print(f"[info] GoatCounter {'有効' if script else '無効'} / HTML更新 {changed}件")


if __name__ == "__main__":
    main()
