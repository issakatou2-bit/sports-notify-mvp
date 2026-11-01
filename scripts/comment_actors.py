"""コメントの人の役割を原文・親・返信と照合。曖昧なYankeeを選手にしない。"""
import re

FAN = re.compile(r'\b(?:fans?|crowd|spectators?|stands|fan interference)\b', re.I)
PLAYER = re.compile(r'\b(?:players?|pitchers?|batters?|hitters?|outfielders?|infielders?)\b', re.I)
YANKEE = re.compile(r'\b(?:a|the|that|this) Yankee\b', re.I)
JA_PLAYER = re.compile(r'選手|投手|打者|外野手|内野手')


def check(original, translation, context=''):
    """明記された選手や、観客が選手を語る原文は通す。役割の根拠だけを見る。"""
    original, translation = original or '', translation or ''
    if not JA_PLAYER.search(translation):
        return []
    if PLAYER.search(original):
        return []
    if YANKEE.search(original) and re.search(r'ヤンキース(?:の)?(?:選手|投手|打者)', translation):
        # 観客妨害の返信が付く実例。文脈が欠けても選手という役割は追加しない。
        return ['Yankeeの役割を原文にない選手としています']
    if FAN.search(original) and not PLAYER.search(context or ''):
        # 名前が残る文はファンと別の選手を語る可能性があるため、全体では止めない。
        # 「ファン/観客」という主体自体を「選手」に替えた短い訳だけを止める。
        if (re.search(r'(?:選手|投手|打者)(?:さん|たち|達|ら)?(?:が|は)', translation)
                and not re.search(r'ファン|観客|スタンド|応援団|受け|された', translation)):
            return ['fan/crowdの主体を選手に替えています']
    return []
