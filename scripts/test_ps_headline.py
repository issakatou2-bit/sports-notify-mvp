"""A persistent clinch flag must never be promoted to today's news."""
import unittest
from copy import deepcopy
import postseason


class HeadlineFreshness(unittest.TestCase):
    def setUp(self):
        self.data = {'103': {'leaders': [], 'clinched': [
            {'id': 139, 'name': 'レイズ', 'clinched': True},
            {'id': 114, 'name': 'ガーディアンズ', 'clinched': True}]}}

    def test_existing_clinches_are_not_news(self):
        original = deepcopy(self.data)
        for changes in (None, [], [{'kind': 'magic', 'name': 'レイズ'}]):
            self.assertEqual(postseason.headline(self.data, changes),
                             'ポストシーズン進出争い')
        self.assertEqual(self.data, original)

    def test_new_clinch_selects_changed_team_not_first(self):
        self.assertEqual(postseason.headline(self.data, [
            {'kind': 'clinch', 'name': 'ガーディアンズ'}]),
            'ガーディアンズ 進出決定')

    def test_event_needs_current_confirmation(self):
        self.assertNotIn('進出決定', postseason.headline(self.data, [
            {'kind': 'clinch', 'name': '未確定球団'}]))

    def test_positive_division_magic_is_valid_even_after_berth(self):
        self.data['103']['leaders'] = [dict(name='ガーディアンズ',
            magic=4, clinched=True, div_champ=False)]
        self.assertEqual(postseason.headline(self.data, []),
                         'ガーディアンズ 地区優勝マジック4')

    def test_zero_invalid_or_champion_magic_not_news(self):
        for magic, champion in [(0,False),(-1,False),(True,False),('1',False),(1,True)]:
            self.data['103']['leaders'] = [dict(name='レイズ', magic=magic,
                                                div_champ=champion)]
            self.assertNotIn('マジック', postseason.headline(self.data, []))


if __name__ == '__main__':
    unittest.main(argv=['test_ps_headline'])
