"""選択規則の試験用生成器。停止・重複試験にも実際の情報数判定を通す。"""
from copy import deepcopy
from types import SimpleNamespace


def generator(topics):
    """原稿生成インターフェースを1か所で保つ。内容の境界試験は材料を明示する。"""
    catalog = deepcopy(topics)
    for spec in catalog.values():
        spec.setdefault('items', [('試験用の事実A', '1件'), ('試験用の事実B', '2件'), ('試験用の事実C', '3件')])
        spec.setdefault('source', '選択試験の偽材料')
    def narration(key):
        return dict(segments=[dict(kind='list', meta=dict(start=0, count=len(catalog[key]['items'])))])
    return SimpleNamespace(LIST_TOPICS=catalog, build_narration=narration)
