#!/usr/bin/env python3
"""
立ち絵のPSDから、目・眉・口を別々のPNGとして切り出す。

なぜ切り出すのか:
  1枚の絵のままだと、3分のあいだ2人が微動だにしない。
  PSDには目(閉じ目を含む)・眉・口が別の層で入っていたので、
  組み合わせれば、まばたきも口の動きも作れる。

  組み合わせの数だけ完成品を持つと 36通り×2人 になるので、
  **部品のまま持って、描くときに重ねる。**
  部品はほとんどが透明なので、1枚あたり数KBにしかならない。

  PSDを読むのに psd-tools が要るが、それは**ここだけ**。
  動画を作る側は出来上がったPNGを重ねるだけなので、
  GitHub Actions に psd-tools を入れる必要は無い。

出力:
  assets/portraits/<名前>/体.png      … 目・眉・口を消した下地
  assets/portraits/<名前>/目_*.png    … 目
  assets/portraits/<名前>/眉_*.png    … 眉
  assets/portraits/<名前>/口_*.png    … 口
  assets/portraits/<名前>/parts.json  … どれが何か

使い方(手元で1回だけ):
  pip install psd-tools
  python3 scripts/build_portrait_parts.py
"""

import json
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

# どのPSDから、どの層を取るか。
#
# 名前はPSDの層名そのまま。頭に * や ! が付いているのは
# 配布元の書き方(表示・非表示の目印)なので、そのまま使う。
SETS = {
    "ずんだもん": {
        "zip": "ずんだもん立ち絵素材改1.1.1.zip",
        # 正面向きの頭を使う。上向きは見上げた絵で、対話には合わない
        "head": "*頭_正面向き",
        "目": {"開": "*基本目", "閉": "*閉じ目", "笑": "*にっこり",
               "見開": "*見開き", "ジト": "*ジト目"},
        "眉": {"基本": "*基本眉", "上げ": "*上がり眉", "困り": "*困り眉"},
        "口": {"閉": "*ん", "開": "*お", "笑": "*にやり", "大": "*うわー"},
        # 腕。表情に合わせて変える。素材にあるものだけを使う。
        "右腕": {"基本": "*基本(直立用)", "上げ": "*手を挙げる",
                 "考え": "*口元", "指": "*指さし横"},
        "左腕": {"基本": "*基本", "上げ": "*手を挙げる",
                 "考え": "*あごに指", "指": "*横"},
    },
    "四国めたん": {
        "zip": "四国めたん立ち絵素材2.1.zip",
        "head": None,                    # めたんは頭の層が分かれていない
        "目": {"開": "*目セット", "閉": "*目閉じ", "笑": "*><",
               "見開": "*見上げ", "ジト": "*目閉じ2"},
        "眉": {"基本": "*ごきげん", "上げ": "*ややおこ", "困り": "*こまり"},
        "口": {"閉": "*▽", "開": "*お", "笑": "*ほほえみ", "大": "*わあー"},
        "右腕": {"基本": "*普通", "上げ": "*手をかざす",
                 "考え": "*普通", "指": "*指差す"},
        "左腕": {"基本": "*マイク", "上げ": "*マイク",
                 "考え": "*口元に指", "指": "*マイク"},
    },
}

# 顔と腕。どれも「体」から外して、あとで重ねられるようにする。
FACE_GROUPS = ("目", "眉", "口", "右腕", "左腕")


def find(node, name):
    """名前で層を探す。深さは問わない。"""
    for layer in node:
        if layer.name == name:
            return layer
        if layer.is_group():
            got = find(layer, name)
            if got is not None:
                return got
    return None


def only(group, name) -> bool:
    """その群のなかで、指定した1枚だけを表示にする。"""
    hit = False
    for layer in group:
        on = layer.name == name
        layer.visible = on
        hit = hit or on
    return hit


def main() -> int:
    try:
        from psd_tools import PSDImage
    except ImportError:
        print("[error] psd-tools が要ります: pip install psd-tools")
        return 1
    from PIL import Image

    for who, spec in SETS.items():
        src = ROOT / spec["zip"]
        if not src.exists():
            print(f"[skip] {src.name} がありません")
            continue
        tmp = ROOT / "build" / "psd"
        tmp.mkdir(parents=True, exist_ok=True)
        zf = zipfile.ZipFile(src)
        psd_name = [n for n in zf.namelist() if n.lower().endswith(".psd")][0]
        psd_path = tmp / f"{who}.psd"
        psd_path.write_bytes(zf.read(psd_name))

        psd = PSDImage.open(psd_path)
        out = ROOT / "assets" / "portraits" / who
        out.mkdir(parents=True, exist_ok=True)
        size = (psd.width, psd.height)
        view = (0, 0, psd.width, psd.height)

        # 頭が2つある絵がある(上向き・正面向き)。顔の層はその中に
        # 入っているので、使うほうを表示にしてから探す。
        #
        # ここを間違えると、非表示の親の中を書き出すことになり、
        # 全部が透明のPNGになる。実際1回そうなった。
        scope = psd
        if spec.get("head"):
            for layer in psd:
                if layer.is_group() and layer.name.lstrip("*!").startswith("頭"):
                    layer.visible = layer.name == spec["head"]
            scope = find(psd, spec["head"])
            if scope is None:
                print(f"[warn] {who}: 頭「{spec['head']}」が見つかりません")
                scope = psd

        # 顔の中身を全部消した下地。ここに重ねていく。
        groups = {}
        for g in FACE_GROUPS:
            # 腕は頭の外にあるので、頭の中だけを探すと見つからない
            look = psd if g.endswith("腕") else scope
            node = (find(look, "!" + g) or find(look, "*" + g)
                    or find(look, g))
            if node is None:
                print(f"[warn] {who}: 「{g}」の群が見つかりません")
                continue
            groups[g] = node
        for node in groups.values():
            node.visible = False
        body = psd.composite(viewport=view).convert("RGBA")
        body.save(out / "体.png")
        made = {"size": list(size), "体": "体.png"}

        # 部品。それぞれ全画面の大きさで書き出すので、
        # 重ねるときは (0,0) に貼るだけでよい。ずれようがない。
        for g, node in groups.items():
            node.visible = True
            made[g] = {}
            for tag, layer_name in spec[g].items():
                if not only(node, layer_name):
                    print(f"[warn] {who} {g}: 「{layer_name}」が無い")
                    continue
                im = node.composite(viewport=view).convert("RGBA")
                fn = f"{g}_{tag}.png"
                im.save(out / fn)
                made[g][tag] = fn
                px = sum(1 for a in im.getchannel("A").getdata() if a)
                print(f"  {who} {g}_{tag}: {px:,}px "
                      f"{(out / fn).stat().st_size // 1024}KB")
            node.visible = False

        (out / "parts.json").write_text(
            json.dumps(made, ensure_ascii=False, indent=2), encoding="utf-8")

        # 出来上がりを1枚確かめる(下地＋基本の目・眉・口)
        chk = Image.open(out / "体.png").convert("RGBA")
        for g, tag in (("右腕", "基本"), ("左腕", "基本"),
                       ("眉", "基本"), ("目", "開"), ("口", "閉")):
            fn = made.get(g, {}).get(tag)
            if fn:
                part = Image.open(out / fn).convert("RGBA")
                chk = Image.alpha_composite(chk, part)
        chk.save(ROOT / "build" / f"check_{who}.png")
        print(f"[info] {who}: {len(list(out.glob('*.png')))}枚 -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
