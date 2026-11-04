"""招集台本の検証中だけ共有する読み。通常の追跡名簿へは登録しない。"""
from contextvars import ContextVar

readings = ContextVar('national_squad_readings', default={})
