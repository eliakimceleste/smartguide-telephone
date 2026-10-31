"""Calculs géographiques simples : distance, cap, écart à un segment.

Un point est un tuple (latitude, longitude) en degrés.
"""
import math

RAYON_TERRE = 6371000.0  # mètres


def distance(a, b):
    """Distance en mètres entre deux points (formule de haversine)."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * RAYON_TERRE * math.asin(math.sqrt(h))


def cap(a, b):
    """Cap de a vers b en degrés (0 = nord, 90 = est)."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def angle_relatif(cap_cible, cap_actuel):
    """Angle à tourner, entre -180 (gauche) et +180 (droite)."""
    return (cap_cible - cap_actuel + 180) % 360 - 180


def _plan(origine, p):
    """Coordonnées locales en mètres (x vers l'est, y vers le nord)."""
    lat0 = math.radians(origine[0])
    x = math.radians(p[1] - origine[1]) * math.cos(lat0) * RAYON_TERRE
    y = math.radians(p[0] - origine[0]) * RAYON_TERRE
    return x, y


def ecart_segment(p, a, b):
    """Distance en mètres entre le point p et le segment [a, b]."""
    ax, ay = 0.0, 0.0
    bx, by = _plan(a, b)
    px, py = _plan(a, p)
    longueur2 = bx * bx + by * by
    if longueur2 == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / longueur2))
    return math.hypot(px - (ax + t * bx), py - (ay + t * by))


def deplace(p, cap_deg, metres):
    """Point atteint en partant de p, au cap donné, après `metres` mètres."""
    lat0 = math.radians(p[0])
    dy = math.cos(math.radians(cap_deg)) * metres
    dx = math.sin(math.radians(cap_deg)) * metres
    return (p[0] + math.degrees(dy / RAYON_TERRE),
            p[1] + math.degrees(dx / (RAYON_TERRE * math.cos(lat0))))
