"""文脈で読みが変わる「上で」を、表示文を変えずに音声だけ直す。"""
import re

# 動詞の連体形・完了形と「する上で」。物理的な「机の上で」は変えない。
ACTION_UE = re.compile(r'([ぁ-んァ-ヶ一-龯々]+(?:する|した|る|た|う|く|ぐ|す|つ|ぬ|ぶ|む))上で')


def apply(text, dictionary):
    if dictionary:
        pattern = re.compile('|'.join(re.escape(k) for k in sorted(dictionary, key=len, reverse=True)))
        text = pattern.sub(lambda match: dictionary[match[0]], text)
    return ACTION_UE.sub(lambda match: match[1] + 'うえで', text)


def unresolved(text):
    """同じ種類の未処理を試験・監査から調べる。"""
    return [match[0] for match in ACTION_UE.finditer(text)]
