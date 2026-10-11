import unittest

from nucleo.equipos import Emparejador


class MLSAliasTest(unittest.TestCase):
    def test_lafc_does_not_resolve_to_galaxy(self):
        emp = Emparejador(["Los Angeles FC", "Los Angeles Galaxy"])
        self.assertEqual(emp.buscar(["LAFC"], "LAFC")[0], "Los Angeles FC")


if __name__ == "__main__":
    unittest.main()
