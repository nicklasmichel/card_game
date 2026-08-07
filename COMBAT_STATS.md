| Stat | Bedeutung         |
| ---- | ----------------- |
| AW   | Angriffswert      |
| VW   | Verteidigungswert |
| LW   | Lebenswert        |
| SW   | Schadenswert      |

- `LW` ersetzt `VW` als Lebensbasis fuer Kreaturen.
- `current_hp` bleibt als Laufzeitfeld bestehen, repraesentiert aber jetzt aktuelles `LW`.
- Angreifer wuerfeln `AW` W6, Blocker `VW` W6.
- Hoehere Summe gewinnt und verursacht `SW` Schaden an der gegnerischen Kreatur.
- Ungeblockte Angreifer verursachen `SW` Schaden am gegnerischen Spieler.
- Gleichstaende loesen einen vollstaendigen Reroll beider Wuerfelpools aus.
- Trampelnd verursacht bei gewonnenem geblocktem Kampf zusaetzlich `floor((Angriffssumme - Verteidigungssumme) / 6)` Spielerschaden.
- Wasser- und Erdkreaturen duerfen voruebergehend noch ueber eine Migrations-Kompatibilitaet laufen: fehlendes `LW` faellt auf `VW` zurueck, fehlendes `SW` auf `AW`.
