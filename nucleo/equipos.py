# -*- coding: utf-8 -*-
"""
nucleo/equipos.py - empata los nombres de ESPN con los de TUS datos.

ESPN llama "Manchester United" a lo que football-data llama "Man United", y "WSH" a
lo que nflverse llama "WAS". Este modulo resuelve eso en un solo lugar:

    emp = Emparejador(claves_de_tu_modelo)
    clave, score = emp.buscar(["Manchester United", "Man United"], abrev="MUN")

Si no hay un empate confiable devuelve (None, score) y la plataforma lo reporta en vez
de adivinar. Para tenis, EmparejadorJugadores empata "A. Muller" / "Alexandre Muller".

Solo stdlib.
"""
import re, unicodedata

UMBRAL = 0.80


def _norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# palabras que no distinguen a un equipo de otro
_STOP = {"fc", "cf", "afc", "sc", "cd", "de", "la", "el", "the", "club", "and", "sv", "fsv",
         "tsg", "vfl", "vfb", "rb", "ssc", "us", "as", "ud", "rc", "ca", "sd"}

# nombres cortos de football-data.co.uk -> nombre completo (claves ya normalizadas)
ALIAS = {
    # Premier
    "man city": "manchester city", "man united": "manchester united",
    "nottm forest": "nottingham forest", "newcastle": "newcastle united",
    "tottenham": "tottenham hotspur", "wolves": "wolverhampton wanderers",
    "west ham": "west ham united", "brighton": "brighton and hove albion",
    "leeds": "leeds united", "leicester": "leicester city", "norwich": "norwich city",
    "ipswich": "ipswich town", "luton": "luton town", "west brom": "west bromwich albion",
    "sheffield utd": "sheffield united",
    # La Liga
    "ath madrid": "atletico madrid", "ath bilbao": "athletic club",
    "sociedad": "real sociedad", "betis": "real betis", "vallecano": "rayo vallecano",
    "celta": "celta vigo", "espanol": "espanyol", "alaves": "deportivo alaves",
    "valladolid": "real valladolid",
    # Serie A
    "inter": "inter milan", "milan": "ac milan", "verona": "hellas verona",
    # Bundesliga
    "m gladbach": "borussia monchengladbach", "dortmund": "borussia dortmund",
    "leverkusen": "bayer leverkusen", "ein frankfurt": "eintracht frankfurt",
    "fc koln": "koln", "koln": "koln", "bayern munich": "bayern munich",
    # Ligue 1
    "paris sg": "paris saint germain", "st etienne": "saint etienne",
}

# abreviaturas de ESPN -> otras que usan nflverse / api-web.nhle.com
ALIAS_ABREV = {
    "NY": ["NYK"], "GS": ["GSW"], "SA": ["SAS"], "NO": ["NOP"],      # NBA (datos/nba.csv usa 3 letras)
    "WSH": ["WAS"], "LAR": ["LA"], "TB": ["TBL", "TB"], "NJ": ["NJD"], "SJ": ["SJS"],
    "LA": ["LAK", "LA"], "UTAH": ["UTA"], "MON": ["MTL"], "VGS": ["VGK"], "CLB": ["CBJ"],
}


def _tokens(s):
    return [t for t in s.split() if t not in _STOP and not t.isdigit()]


def _score(na, nb):
    """similitud 0..1 entre dos nombres YA normalizados (na = nombre en tus datos)."""
    na = ALIAS.get(na, na)
    if na == nb:
        return 1.0
    ta, tb = _tokens(na), _tokens(nb)
    if not ta or not tb:
        return 0.0
    chico, grande = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    usados, m = set(), 0
    for t in chico:
        for i, u in enumerate(grande):
            if i in usados:
                continue
            if t == u or (len(t) >= 3 and len(u) >= 3 and (u.startswith(t) or t.startswith(u))):
                usados.add(i); m += 1
                break
    if m < len(chico):
        return 0.0
    return 0.80 + 0.19 * (m / len(grande))


class Emparejador:
    def __init__(self, claves):
        self.claves = [c for c in dict.fromkeys(claves) if c]
        self.n = {c: _norm(c) for c in self.claves}

    def buscar(self, variantes, abrev=None):
        """variantes: nombres de ESPN (displayName, location, name...). -> (clave|None, score)"""
        if abrev:
            ab = str(abrev).upper()
            cand = [ab] + ALIAS_ABREV.get(ab, [])
            for c in self.claves:
                if c.upper() in cand:
                    return c, 0.97
        mejor, sm = None, 0.0
        for v in variantes:
            nb = _norm(v)
            if not nb:
                continue
            for c in self.claves:
                s = _score(self.n[c], nb)
                if s > sm:
                    mejor, sm = c, s
        return (mejor, sm) if sm >= UMBRAL else (None, sm)


class EmparejadorJugadores:
    """Empata jugadores de tenis: nombre completo, o inicial + apellido."""
    def __init__(self, claves):
        self.claves = [c for c in dict.fromkeys(claves) if c]
        self.por_norm = {}
        self.por_apellido = {}
        self.por_tokens = {}          # mismas palabras en cualquier orden: "Zheng Qinwen" = "Qinwen Zheng"
        for c in self.claves:
            n = _norm(c)
            self.por_norm[n] = c
            t = n.split()
            if t:
                self.por_apellido.setdefault(t[-1], []).append((t[0], c))
                self.por_tokens.setdefault(" ".join(sorted(t)), []).append(c)

    def buscar(self, nombre):
        n = _norm(nombre)
        if n in self.por_norm:
            return self.por_norm[n], 1.0
        t = n.split()
        if not t:
            return None, 0.0
        og = self.por_tokens.get(" ".join(sorted(t)), [])
        if len(og) == 1:
            return og[0], 0.95
        cand = [c for ini, c in self.por_apellido.get(t[-1], []) if ini[:1] == t[0][:1]]
        if len(cand) == 1:
            return cand[0], 0.9
        return None, 0.0
