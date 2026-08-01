"""Datenquellen des Standort-Datenterminals.

Bewusst ohne Sammelimporte: ``gastroviewer.http`` braucht ``sources.base`` für die
Fehlerklassen, während die Quellenmodule ``gastroviewer.http`` brauchen. Ein
Eager-Import hier würde diesen Kreis schließen.
"""
