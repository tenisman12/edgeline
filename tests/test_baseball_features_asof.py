"""Regression check: future games and same-day results cannot affect features."""
import unittest
from unittest.mock import patch

from nucleo import features


def game(pk, date, home_runs, away_runs):
    common = {"gamePk": str(pk), "league": "MLB", "season": "2025",
              "game_date": date}
    home = dict(common, team="Local", opp="Visitor", is_home="1",
                runs=str(home_runs), runs_opp=str(away_runs))
    away = dict(common, team="Visitor", opp="Local", is_home="0",
                runs=str(away_runs), runs_opp=str(home_runs))
    return [home, away]


class HistoricalFeaturesAsOfTest(unittest.TestCase):
    def test_future_scores_and_same_day_scores_are_hidden(self):
        old = sum((game(i, f"2025-04-0{i}", i + 1, 2)
                   for i in range(1, 4)), [])
        same_day = game(4, "2025-04-04", 1, 12) + game(5, "2025-04-04", 20, 0)
        future = game(6, "2025-04-05", 30, 1)
        with patch("nucleo.features.io.cargar_juegos", return_value=old + same_day):
            first, _ = features.construir("beisbol", "mlb", min_juegos=3)
        with patch("nucleo.features.io.cargar_juegos", return_value=old + same_day + future):
            second, _ = features.construir("beisbol", "mlb", min_juegos=3)
        self.assertEqual(first, [r for r in second if r["game_date"] == "2025-04-04"])
        self.assertEqual(len(first), 2)
        for field in ("elo_dif", "cs_dif", "ca_dif",
                      "of_home", "of_away", "df_home", "df_away", "lg_rs"):
            self.assertEqual(first[0][field], first[1][field], field)

    def test_default_prior_is_unchanged(self):
        self.assertEqual(features.k_carreras("MLB"), 6.0)
        self.assertEqual(features.k_carreras("KBO"), 6.0)
        self.assertEqual(features.k_carreras("MLB", override=100), 100.0)


if __name__ == "__main__":
    unittest.main()
