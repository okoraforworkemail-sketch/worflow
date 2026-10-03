# Thumbnail-Generator (GPT Image)

Du gibst ein Thema ein (oder legst Skripte ab), und das Tool erstellt automatisch mehrere klickstarke YouTube-Thumbnails im 16:9-Format mit dem neuesten OpenAI-Bildmodell.

## Einrichtung (einmalig)
```bash
pip install -r requirements.txt
cp .env.example .env      # API-Key eintragen, ggf. IMAGE_MODEL auf das neueste Modell setzen
```

## Benutzung
```bash
# Thema -> 4 Thumbnails (Standard)
python thumbnail_generator.py --topic "Ich habe 30 Tage nur Wasser getrunken"

# Mehr Varianten
python thumbnail_generator.py -t "Thema A" -t "Thema B" -n 8

# Eine Datei mit einem Thema pro Zeile
python thumbnail_generator.py --topics-file themen.txt

# Ein Thumbnail pro Skript (alle .txt/.md im Ordner scripts/)
python thumbnail_generator.py --scripts scripts/

# Ohne Argumente: fragt nach dem Thema
python thumbnail_generator.py
```
Die Bilder landen in `thumbnails/<datum>/`, dazu eine `prompts.json` mit allen Konzepten.

Optionen: `--style "Kanalfarben Gelb/Schwarz, mein Gesicht links"`, `--quality low|medium|high`, `--workers 8`.

## Maximale Anzahl – dauerhaft
- **API statt ChatGPT-App:** In der ChatGPT-App gibt es feste Tageslimits. Über die API gibt es kein Tageslimit, nur Rate-Limits pro Minute (abhängig von deinem Usage-Tier) – du bezahlst pro Bild.
- **Parallelität:** `--workers` (oder `WORKERS` in `.env`) so hoch setzen, wie dein Tier erlaubt. Das Tool läuft so lange am Limit, wie es geht.
- **Auto-Retry:** Bei Rate-Limits (429) oder Serverfehlern wartet das Tool (beachtet `retry-after`) und macht automatisch weiter – kein Bild geht verloren.
- **Kosten senken:** `--quality medium` oder `low` für Entwürfe, dann die besten in `high` neu erzeugen.
- **Mehr Limit:** Höheres Usage-Tier unter platform.openai.com → Limits.

## Nur ChatGPT-Abo (ohne API)?
```bash
python thumbnail_generator.py -t "Thema" -n 10 --prompts-only
```
Erstellt `chatgpt_prompts.txt` mit fertigen Prompts zum Einfügen in ChatGPT. (Benötigt trotzdem einen API-Key für die Konzept-Erstellung mit dem Textmodell.)

## Modell
Standard ist `gpt-image-1.5`. Erscheint ein neueres Modell, einfach `IMAGE_MODEL` in `.env` ändern – kein Code nötig.
