"""見本作成の識別と、後続SNSワークフローへの伝播。公開機能は持たない。"""
import argparse
import json
import os
from pathlib import Path


def enabled():
    return os.environ.get('COLLESPO_SAMPLE_ONLY', 'false').lower() == 'true'


def assert_publish_allowed():
    if enabled():
        raise ValueError('sample_onlyの見本は公開・台帳保存できません')


def source_is_sample(artifacts):
    return any(a.get('name', '').startswith('sample-') for a in artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mark', type=Path)
    parser.add_argument('--require-video', action='store_true')
    args = parser.parse_args()
    if args.mark:
        if not enabled():
            raise ValueError('見本実行以外では識別ファイルを作りません')
        args.mark.parent.mkdir(parents=True, exist_ok=True)
        args.mark.write_text(json.dumps(dict(sample_only=True, published=False))+'\n', encoding='utf-8')
    if args.require_video and not any(Path('build').rglob('*.mp4')):
        raise ValueError('見本のmp4がありません。材料と描画の検査結果を確認してください')


if __name__ == '__main__':
    main()
