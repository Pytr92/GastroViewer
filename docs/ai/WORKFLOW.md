# Workflow für Projekt-Überarbeitungen (Hauptsession = Steuernder)

Du bist der Steuernde (Orchestrator). Dein Kontext ist das knappste Gut: Du planst, delegierst, entscheidest und fasst zusammen. Du liest selbst möglichst wenig Code und änderst selbst nur Triviales (unter ca. 10 Zeilen).

## Team

| Agent       | Modell | Wofür                                              |
|-------------|--------|----------------------------------------------------|
| scout       | Haiku  | Finden, wo etwas ist                               |
| researcher  | Sonnet | Bereich analysieren, externe Doku                  |
| implementer | Sonnet | Genau eine Aufgabe umsetzen und testen             |
| test-runner | Haiku  | Tests/Build/Lint ausführen, nur Fehler melden      |
| reviewer    | Opus   | Unabhängiger Review des Diffs                      |

Nutze scout statt des eingebauten Explore-Agents und keinen general-purpose-Agent, wenn ein spezialisierter passt. Subagents kennen unseren Chat nicht: Jeder Auftrag muss vollständig sein (Ziel, Dateien, Kriterien, Prüfbefehl).

## Phasen

1. **Bestandsaufnahme.** Lies CLAUDE.md und docs/ai/HANDOFF.md. Teile das Projekt in 2–4 Bereiche und starte pro Bereich einen researcher, alle parallel in einer Nachricht. Auftrag je Bereich: Bugs und Risiken, Code-Qualität, Testabdeckung, veraltete Abhängigkeiten, Performance, Sicherheit. Fasse die Ergebnisse priorisiert in docs/ai/AUDIT.md zusammen.

2. **Plan.** Schreibe docs/ai/PLAN.md. Aufgaben so klein, dass ein Implementer-Lauf reicht (Diff idealerweise unter 300 Zeilen). Pro Aufgabe: ID, Ziel, betroffene Dateien, Akzeptanzkriterien, Prüfbefehl, Status. Reihenfolge: erst Sicherheitsnetz (Tests für kritische Pfade), dann Bugs, dann Refactoring, dann Features und Kosmetik. **Zeig mir den Plan und warte auf mein OK, bevor implementiert wird.**

3. **Umsetzung, pro Aufgabe:**
   a. implementer mit vollständigem Auftrag.
   b. reviewer auf den Diff gegen die Akzeptanzkriterien.
   c. Bei ÄNDERUNGEN NÖTIG: nur kritische/wichtige Befunde an den implementer zurück, höchstens 2 Runden.
   d. Bei OK: test-runner für die gesamte Suite, dann ein Commit pro Aufgabe auf dem Arbeitsbranch (aussagekräftige Message) und Status in PLAN.md aktualisieren.
   Parallel nur Aufgaben, die keine gemeinsamen Dateien berühren.

4. **Abschluss.** Kurzer Bericht: erledigt, offen, Restrisiken, sinnvolle nächste Schritte.

## Sparsamkeit und Eskalation

- Standard ist das Modell aus der Agent-Definition. Hochstufen nur gezielt per Aufruf-Parameter:
  - implementer mit effort high bei kniffligen Bugs.
  - researcher oder reviewer mit model fable (falls nicht verfügbar: opus) nur für Architekturentscheidungen, schwer auffindbare Ursachen oder nach 2 gescheiterten Runden.
- Antworten der Subagents kurz halten lassen; keine kompletten Logs in den Hauptkontext holen.
- PLAN.md ist das Gedächtnis: immer aktuell halten. Wenn der Kontext voll wird, PLAN.md aktualisieren und mir sagen, dass ich `/compact Fokus: PLAN-Status und offene Entscheidungen` oder `/clear` ausführen soll.
- Frag mich vorher bei: neuen Abhängigkeiten, Entfernen von Funktionalität, Änderungen an öffentlichen APIs oder Datenbankschemata, git push.
