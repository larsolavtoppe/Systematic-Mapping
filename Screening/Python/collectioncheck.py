import re
from pathlib import Path

# --- KONFIG (relativt til prosjektrot) ---
# Prosjektrot = mappa som inneholder "Python", "3.Unique", "Reports", "4.Remove collections", ...
ROOT = Path(__file__).resolve().parent.parent

IN_DIR = ROOT / "3.Unique"              # input: resultatet fra merged/unique
COLLECTIONS_DIR = ROOT / "Reports"      # samme report-mappe som i de andre scriptene
DISCIPLINE_DIR = ROOT / "4.Remove collections"  # ny mappe for renset/disiplin-fil
# --------------

HIGHLIGHT_PREFIX = "% === HIGHLIGHT: title gjentar journal-delen etter bindestrek ===\n"

def split_bib_entries(text: str):
    """Del opp BibTeX-tekst i entries ved linjer som starter med '@'."""
    parts = re.split(r'(?m)^(?=@)', text)
    return [p for p in parts if p.strip()]

def extract_field(entry_text: str, field_name: str):
    """
    Hent ut et felt (f.eks. journal/title) som kan stå i {...}, "..." eller som råtekst.
    Tåler moderat nivå av nestede klammer.
    """
    pattern = re.compile(
        rf'(?mi)^\s*{re.escape(field_name)}\s*=\s*(\{{(?:[^{{}}]|\{{[^{{}}]*\}})*\}}|"[^"]*"|[^,\n]+)'
    )
    m = pattern.search(entry_text)
    if not m:
        return None
    raw = m.group(1).strip()
    # Fjern ytre { } eller " "
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    elif raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw.strip()

def normalize_text(s: str) -> str:
    """Robust sammenlikning: lower, fjern ikke-alfanumerisk, kollaps mellomrom."""
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def extract_collection_tail(journal: str):
    """
    Prøv å hente delen av journal etter bindestrek/en dash/em dash/kolon,
    men kun i tilfeller hvor 'collection' finnes i journal.
    Eksempel:
      'Collection of Technical Papers - AIAA/ASME/...' -> 'AIAA/ASME/...'
    """
    if not journal or "collection" not in journal.lower():
        return None

    m = re.search(r'collection[^-–—:]*[-–—:]\s*(.+)$', journal, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Fallback: bruk siste dash/kolon hvis finnes
    parts = re.split(r'[-–—:]', journal)
    if len(parts) >= 2:
        tail = parts[-1].strip()
        return tail if tail else None

    return None

def title_repeats_tail(title, tail) -> bool:
    if not title or not tail:
        return False
    nt = normalize_text(title)
    nh = normalize_text(tail)
    if len(nh) < 5:  # unngå kortord/falske treff
        return False
    return nh in nt

def process_file(bib_path: Path, collections_dir: Path, discipline_dir: Path):
    text = bib_path.read_text(encoding="utf-8", errors="ignore")
    entries = split_bib_entries(text)

    # Prepare output-containere
    collections_entries = []   # kun collection-entries (med highlight-kommentar der aktuelt)
    discipline_entries = []    # hele filen, men uten de highlightede collection-entryene

    total_collection_entries = 0
    highlighted_count = 0

    for e in entries:
        journal = extract_field(e, "journal")
        title = extract_field(e, "title")
        is_collection = bool(journal and "collection" in journal.lower())

        is_highlight = False
        if is_collection:
            total_collection_entries += 1
            tail = extract_collection_tail(journal)
            is_highlight = title_repeats_tail(title, tail)

            # Skriv til collections-filen (alltid hvis collection)
            if is_highlight:
                collections_entries.append(HIGHLIGHT_PREFIX)
                highlighted_count += 1
            collections_entries.append(e.rstrip() + "\n\n")

        # Skriv til discipline-filen dersom IKKE highlightet collection-entry
        if not (is_collection and is_highlight):
            discipline_entries.append(e.rstrip() + "\n\n")

    # Skriv ut filer
    collections_dir.mkdir(parents=True, exist_ok=True)
    discipline_dir.mkdir(parents=True, exist_ok=True)

    collections_out_path = collections_dir / f"collectioncheck_{bib_path.name}"
    collections_out_path.write_text("".join(collections_entries), encoding="utf-8")

    discipline_out_path = discipline_dir / bib_path.name
    discipline_out_path.write_text("".join(discipline_entries), encoding="utf-8")

    return {
        "file": bib_path.name,
        "total_collection_entries": total_collection_entries,
        "highlighted": highlighted_count,
        "collections_out": collections_out_path,
        "discipline_out": discipline_out_path,
    }

def main():
    if not IN_DIR.exists():
        raise FileNotFoundError(f"Inndirmappe finnes ikke: {IN_DIR}")

    total_files = 0
    total_collection_entries = 0
    total_highlighted = 0

    for bib_path in IN_DIR.glob("*.bib"):
        total_files += 1
        stats = process_file(bib_path, COLLECTIONS_DIR, DISCIPLINE_DIR)
        print(
            f"{stats['file']}: collection-entries={stats['total_collection_entries']}, "
            f"highlightet={stats['highlighted']} -> "
            f"{stats['collections_out'].name}; 4.Disipline -> {stats['discipline_out'].name}"
        )
        total_collection_entries += stats["total_collection_entries"]
        total_highlighted += stats["highlighted"]

    if total_files == 0:
        print(f"Ingen .bib-filer funnet i {IN_DIR}")
    else:
        print(
            f"Ferdig. Prosesserte {total_files} filer. "
            f"Collection-entries totalt: {total_collection_entries}, "
            f"highlightet (og fjernet fra 4.Disipline): {total_highlighted}."
        )

if __name__ == "__main__":
    main()
