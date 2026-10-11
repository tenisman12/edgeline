"""La prueba auxiliar no puede modificar el prior de producción."""
import unittest
from unittest.mock import patch

from nucleo import encogimiento
from modelos import americano, futbol, hockey, nba


class EncogimientoPorLigaTest(unittest.TestCase):
    def test_habilitacion_y_cero_explicito(self):
        self.assertEqual(encogimiento.ficha("beisbol", "mlb")["k_publicado"], 100)
        self.assertEqual(encogimiento.ficha("hockey", "nhl")["k_publicado"], 12)
        self.assertEqual(encogimiento.k("americano", "ncaafb"), 6)
        self.assertEqual(encogimiento.k("americano", "ncaafb", referencia=True), 0)
        self.assertIsNone(encogimiento.k("tenis", "atp"))

    def test_motores_conservan_produccion_y_aislan_referencia(self):
        for modulo, liga, base, candidato in (
            (hockey, "nhl", 12, 20),
            (americano, "nfl", 6, 5),
            (nba, "nba", 8, 8),
            (futbol, "mls", 6, 20),
        ):
            with self.subTest(liga=liga), patch.object(modulo, "_juegos", return_value=[]):
                self.assertEqual(modulo.entrenar(liga)["eq"], {})
                self.assertEqual(modulo.entrenar(liga, referencia=True)["eq"], {})
                self.assertEqual(modulo.Eq().prior, base)
                self.assertEqual(modulo.Eq(candidato).prior, candidato)
        # Un equipo con datos demuestra que la opción modifica la vista de
        # anotación sin sustituir la predicción de producción por accidente.
        equipo = americano.Eq(encogimiento.k("americano", "ncaafb", True))
        equipo.n, equipo.pf = 2, 60
        self.assertEqual(equipo.of(20), 30)
        self.assertNotEqual(equipo.of(20), americano.Eq().of(20))


if __name__ == "__main__":
    unittest.main()
