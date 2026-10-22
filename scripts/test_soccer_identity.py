"""同じ頭文字の兄弟と、省略のない名の優先を二つの取得経路で検査する。"""
import sys
import unittest

import soccer_jp_week as week
import soccer_results as results


class IdentityTests(unittest.TestCase):
    def test_short_sano_cannot_identify_either_brother(self):
        row = {'athlete': {'id': '1', 'lastName': 'Sano', 'fullName': 'K. Sano'}}
        fpl = {'id': 1, 'first_name': 'K.', 'second_name': 'Sano'}
        for name in ('Kaishu Sano', 'Kodai Sano'):
            self.assertIsNone(results.resolve_player([row], name))
            self.assertIsNone(week.resolve([fpl], name))

    def test_full_first_name_overrides_short_display_name(self):
        row = {'athlete': {'id': '1', 'lastName': 'Sano', 'firstName': 'Kodai',
                           'displayName': 'K. Sano'}}
        self.assertIsNone(results.resolve_player([row], 'Kaishu Sano'))
        self.assertIs(results.resolve_player([row], 'Kodai Sano'), row)

    def test_unique_initial_and_full_names_still_match(self):
        row = {'athlete': {'id': '1', 'lastName': 'Maeda', 'displayName': 'D. Maeda'}}
        self.assertIs(results.resolve_player([row], 'Daizen Maeda'), row)
        self.assertEqual(week.resolve([{'id': 1, 'first_name': 'D.', 'second_name': 'Maeda'}],
                                      'Daizen Maeda'), 1)
        for given in ('Kaishu', 'Kodai'):
            row = {'athlete': {'id': '1', 'lastName': 'Sano', 'fullName': given + ' Sano'}}
            self.assertIs(results.resolve_player([row], given + ' Sano'), row)

    def test_empty_or_surname_only_is_unresolved(self):
        for name in ('', None, 'Sano'):
            self.assertIsNone(results.resolve_player([], name))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
