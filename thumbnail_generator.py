#!/usr/bin/env python3
"""
Thumbnail-Generator mit dem neuesten OpenAI-Bildmodell (GPT Image).

Nutzung:
  python thumbnail_generator.py --topic "Warum Bitcoin 2027 explodiert" -n 6
  python thumbnail_generator.py --scripts scripts/          # 1 Thumbnail pro Skript
  python thumbnail_generator.py --topic "..." --prompts-only  # nur Prompts für ChatGPT-App

Ablauf:
  1. Ein Textmodell entwickelt aus Thema/Skript klickstarke, unterschiedliche
     Thumbnail-Konzepte (Hook-Text, Motiv, Komposition, Farben, Emotion).
  2. Das Bildmodell rendert jedes Konzept als 16:9-Thumbnail (1536x1024).
  3. Parallele Erzeugung bis zum Rate-Limit, automatische Wiederholung bei
     429/5xx mit exponentiellem Backoff -> dauerhaft maximaler Durchsatz.
"""
import argparse
import base64
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI, RateLimitError, APIStatusError, APIConnectionError
except ImportError:
    sys.exit("Bitte zuerst installieren: pip install -r requirements.txt")

IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1.5")
TEXT_MODEL = os.getenv("TEXT_MODEL", "gpt-5")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "thumbnails"))

CONCEPT_SYSTEM = """Du bist ein Top-YouTube-Thumbnail-Designer (MrBeast-, Ali-Abdaal-,
Veritasium-Niveau). Du entwirfst Thumbnails mit maximaler Klickrate (CTR).
Regeln:
- Max. 2-4 Wörter Text, riesig, fett, extrem gut lesbar, in der Sprache des Themas.
- Ein klarer Fokuspunkt, starker Kontrast, gesättigte Farben, Tiefe.
- Starke Emotion (Gesicht mit Ausdruck, wenn passend), Neugier-Lücke, nicht den Inhalt verraten.
- Funktioniert auch winzig auf dem Handy. Freie Fläche unten rechts (Video-Dauer-Badge).
- Jedes Konzept muss sich deutlich von den anderen unterscheiden (Winkel, Motiv, Farbwelt).
Antworte NUR mit JSON: {"concepts":[{"title":"...","hook_text":"...","image_prompt":"..."}]}
image_prompt: ausführlicher englischer Bild-Prompt (Motiv, Komposition, Licht, Farben,
Stil, exakter Text in Anführungszeichen, Typografie), fotorealistisch oder hochwertiger 3D-Look."""

PROMPT_SUFFIX = (
    " YouTube thumbnail, 16:9, ultra high contrast, vibrant saturated colors, "
    "sharp focus, cinematic lighting, bold thick sans-serif text with outline and drop shadow, "
    "text perfectly spelled, rule of thirds, uncluttered background, keep bottom-right corner free, "
    "readable at small sizes, professional, viral, eye-catching."
)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def slugify(text, maxlen=50):
    text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    return re.sub(r"[\s_-]+", "-", text).strip("-")[:maxlen] or "thumbnail"


def with_retry(fn, what, max_retries=8):
    """Führt fn aus; wartet bei Rate-Limit/Serverfehlern und versucht es erneut."""
    for attempt in range(max_retries):
        try:
            return fn()
        except (RateLimitError, APIConnectionError, APIStatusError) as e:
            status = getattr(e, "status_code", None)
            if isinstance(e, APIStatusError) and not isinstance(e, RateLimitError) \
                    and status is not None and status < 500:
                raise  # z.B. 400 (Prompt abgelehnt) -> kein Retry
            wait = None
            resp = getattr(e, "response", None)
            if resp is not None:
                ra = resp.headers.get("retry-after")
                if ra:
                    try:
                        wait = float(ra)
                    except ValueError:
                        pass
            wait = wait or min(60, 2 ** attempt) + random.uniform(0, 1.5)
            log(f"  {what}: {type(e).__name__} ({status}) – warte {wait:.1f}s "
                f"(Versuch {attempt + 1}/{max_retries})")
            time.sleep(wait)
    raise RuntimeError(f"{what}: zu viele Fehlversuche")


class ThumbnailGenerator:
    def __init__(self, workers=4, size="1536x1024", quality="high", style=""):
        self.client = OpenAI()
        self.workers = workers
        self.size = size
        self.quality = quality
        self.style = style
        self.lock = threading.Lock()

    # ---------- Schritt 1: Konzepte ----------
    def concepts(self, source, n, is_script=False):
        kind = "Video-Skript" if is_script else "Video-Thema"
        user = (f"{kind}:\n\"\"\"\n{source[:12000]}\n\"\"\"\n\n"
                f"Erstelle genau {n} unterschiedliche Thumbnail-Konzepte.")
        if self.style:
            user += f"\nGewünschter Stil / Vorgaben: {self.style}"

        def call():
            r = self.client.chat.completions.create(
                model=TEXT_MODEL,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": CONCEPT_SYSTEM},
                          {"role": "user", "content": user}],
            )
            return json.loads(r.choices[0].message.content)["concepts"]

        result = with_retry(call, "Konzepte")
        return result[:n]

    # ---------- Schritt 2: Bild ----------
    def render(self, concept, path):
        prompt = concept["image_prompt"] + PROMPT_SUFFIX

        def call():
            return self.client.images.generate(
                model=IMAGE_MODEL, prompt=prompt, size=self.size,
                quality=self.quality, n=1,
            )

        r = with_retry(call, path.name)
        path.write_bytes(base64.b64decode(r.data[0].b64_json))
        return path

    # ---------- Orchestrierung ----------
    def run(self, jobs, out_dir, prompts_only=False):
        """jobs: Liste von (name, quelle, anzahl, is_script)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        tasks, manifest = [], []

        # Konzepte parallel erzeugen
        with ThreadPoolExecutor(self.workers) as ex:
            futs = {ex.submit(self.concepts, src, n, sc): name for name, src, n, sc in jobs}
            for f in as_completed(futs):
                name = futs[f]
                try:
                    cs = f.result()
                except Exception as e:
                    log(f"FEHLER Konzepte für '{name}': {e}")
                    continue
                log(f"{len(cs)} Konzepte für '{name}' erstellt")
                for i, c in enumerate(cs, 1):
                    p = out_dir / f"{slugify(name)}_{i:02d}_{slugify(c.get('hook_text', ''), 25)}.png"
                    tasks.append((c, p))
                    manifest.append({"source": name, "file": p.name, **c,
                                     "full_prompt": c["image_prompt"] + PROMPT_SUFFIX})

        (out_dir / "prompts.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        if prompts_only:
            txt = out_dir / "chatgpt_prompts.txt"
            txt.write_text("\n\n".join(
                f"### {m['file']}  ({m['hook_text']})\nErstelle ein Bild im Querformat 16:9:\n{m['full_prompt']}"
                for m in manifest), encoding="utf-8")
            log(f"Nur Prompts erzeugt -> {txt}")
            return []

        # Bilder parallel rendern
        done, failed = [], 0
        log(f"Rendere {len(tasks)} Thumbnails mit {IMAGE_MODEL} ({self.workers} parallel) ...")
        with ThreadPoolExecutor(self.workers) as ex:
            futs = {ex.submit(self.render, c, p): p for c, p in tasks}
            for f in as_completed(futs):
                try:
                    done.append(f.result())
                    log(f"  ✔ {futs[f].name}  ({len(done)}/{len(tasks)})")
                except Exception as e:
                    failed += 1
                    log(f"  ✘ {futs[f].name}: {e}")
        log(f"Fertig: {len(done)} erstellt, {failed} fehlgeschlagen -> {out_dir.resolve()}")
        return done


def load_scripts(path):
    p = Path(path)
    files = [p] if p.is_file() else sorted(
        f for f in p.iterdir() if f.suffix.lower() in {".txt", ".md"})
    return [(f.stem, f.read_text(encoding="utf-8", errors="ignore")) for f in files]


def main():
    ap = argparse.ArgumentParser(description="YouTube-Thumbnails mit GPT Image erzeugen")
    ap.add_argument("--topic", "-t", action="append", help="Thema (mehrfach möglich)")
    ap.add_argument("--topics-file", help="Textdatei, ein Thema pro Zeile")
    ap.add_argument("--scripts", "-s", help="Ordner/Datei mit Skripten (.txt/.md)")
    ap.add_argument("-n", "--count", type=int, default=4, help="Thumbnails pro Thema (Standard 4)")
    ap.add_argument("--per-script", type=int, default=1, help="Thumbnails pro Skript (Standard 1)")
    ap.add_argument("--workers", "-w", type=int, default=int(os.getenv("WORKERS", 4)),
                    help="Parallele Anfragen (an dein Rate-Limit anpassen)")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    ap.add_argument("--size", default="1536x1024")
    ap.add_argument("--style", default="", help="Zusätzliche Stilvorgaben, z.B. Kanal-Branding")
    ap.add_argument("--out", default=None, help="Ausgabeordner")
    ap.add_argument("--prompts-only", action="store_true",
                    help="Keine API-Bilder, nur Prompts zum Einfügen in ChatGPT")
    a = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY fehlt (export OPENAI_API_KEY=sk-... oder .env-Datei).")

    jobs = [(t, t, a.count, False) for t in (a.topic or [])]
    if a.topics_file:
        jobs += [(l.strip(), l.strip(), a.count, False)
                 for l in Path(a.topics_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.scripts:
        jobs += [(name, txt, a.per_script, True) for name, txt in load_scripts(a.scripts)]
    if not jobs:
        topic = input("Thema eingeben: ").strip()
        if not topic:
            sys.exit("Kein Thema angegeben.")
        jobs = [(topic, topic, a.count, False)]

    out = Path(a.out) if a.out else OUTPUT_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ThumbnailGenerator(a.workers, a.size, a.quality, a.style).run(jobs, out, a.prompts_only)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()
