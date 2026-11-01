"""2026年ゴールドグラブ最終候補60人の表記が揃っているか。

一人でも欠けると offseason_news.awards はその部門の賞全体を保留する。
名簿は MLB.com の最終候補記事（10/14）を公式の nameFirstLast と照合した物。
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
FINALISTS = '''Tanner Bibee|Jacob deGrom|José Soriano|Dillon Dingler|Brandon Valenzuela|Austin Wells
Vladimir Guerrero Jr.|Vinnie Pasquantino|Christian Walker|Michael Massey|Chase Meidroth|Cole Young
Caleb Durbin|Brooks Lee|Nick Loftin|Andrés Giménez|Taylor Walls|Bobby Witt Jr.
Cody Bellinger|Wyatt Langford|Chandler Simpson|Evan Carter|Steven Kwan|Ceddanne Rafaela
Wilyer Abreu|Nathan Lukes|Cam Smith|José Caballero|Ezequiel Duran|Zach McKinstry
Michael McGreevy|Nolan McLean|Chris Sale|Freddy Fermin|Gabriel Moreno|Luis Torrens
Ty France|Matt Olson|TJ Rumfield|Brandon Lowe|Brice Turang|JJ Wetherholt
Alex Bregman|Max Muncy|Javier Sanoja|Geraldo Perdomo|Dansby Swanson|Masyn Winn
Jackson Chourio|Ian Happ|Daylen Lile|Pete Crow-Armstrong|Michael Harris II|Andy Pages
Carson Benge|Corbin Carroll|Seiya Suzuki|Mauricio Dubón|Jared Triolo|Ildemaro Vargas'''.replace('\n', '|').split('|')


class AwardFinalistNames(unittest.TestCase):
    def test_every_finalist_has_a_japanese_name(self):
        names = json.loads((ROOT / 'data/player_kana.json').read_text(encoding='utf-8'))['names']
        self.assertEqual(len(set(FINALISTS)), 60)
        self.assertEqual([n for n in FINALISTS if not names.get(n)], [])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
