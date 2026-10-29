"""サッカー専用の見た目。既存の指定・既定値には触れない。"""
import os


def v5():
    return os.environ.get('COLLESPO_SOCCER_LOOK') in ('v5', 'v6') or os.environ.get('COLLESPO_SHORT_LOOK') in ('v5', 'v6')


def readable():
    return os.environ.get('COLLESPO_SOCCER_LOOK') == 'v6' or os.environ.get('COLLESPO_SHORT_LOOK') == 'v6'


def activate():
    # 共通のcharacters/outroはv4の配置を使う。別プロセスのMLBには影響しない。
    if v5():
        os.environ['COLLESPO_SOCCER_LOOK'] = 'v6' if readable() else 'v5'
        os.environ['COLLESPO_SHORT_LOOK'] = 'v4'


def transition(previous, image, frame, fps=30):
    if image.info.get('soccer_readable'):
        return image.tobytes()  # v6は描画済みの0.35秒フェードだけ。
    import motion
    moved = motion.transition(previous, image, frame, fps)
    if moved is not None:return moved
    if v5():
        from soccer_v5_cards import scarf_transition
        return scarf_transition(previous, image, frame / fps)
    import video_common
    return video_common.short_transition(previous, image, frame, fps, True)
