# -*- coding: utf-8 -*-
import re
import unicodedata
from pathlib import Path

# --- Prosjektrot = mappa som inneholder "Python", "1. bib files", osv. ---
ROOT_DIR = Path(__file__).resolve().parent.parent

# --- Standardmapper relativt til prosjektrot ---
DEFAULT_INPUT_ROOT   = ROOT_DIR / "1.bib files"          # der .bib ligger
DEFAULT_OUTPUT_ROOT  = ROOT_DIR / "2.BibTex_clean_ISSN"   # rensede filer
DEFAULT_REPORTS_DIR  = ROOT_DIR / "Reports"               # rapporter
DEFAULT_REPORT_FILENAME = "check 1 clean ISSN.bib"        # samlet rapport

def normalize_issn(raw):
    if not raw:
        return None
    s = re.sub(r'[^0-9xX]', '', raw).upper()
    if len(s) != 8:
        return None
    return s[:4] + "-" + s[4:]

def strip_braces_quotes(s):
    if not s:
        return s
    s = s.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s

def normalize_title(title):
    if not title:
        return None
    t = strip_braces_quotes(title)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t or None

def extract_field(entry_text, field_name):
    # Fanger felt = { … } eller " … " (tolerant, multiline)
    pattern = re.compile(
        r'(?im)^\s*' + re.escape(field_name) + r'\s*=\s*([{"].*?[}"])',
        re.DOTALL | re.IGNORECASE | re.MULTILINE
    )
    m = pattern.search(entry_text)
    return m.group(1) if m else None

def split_entries(bib_text):
    # Splitt ved å balansere {} fra hver @type{ … }
    entries, i, n = [], 0, len(bib_text)
    while i < n:
        at = bib_text.find('@', i)
        if at == -1:
            break
        br = bib_text.find('{', at)
        if br == -1:
            break
        depth, j = 1, br + 1
        while j < n and depth > 0:
            c = bib_text[j]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            j += 1
        if depth == 0:
            entries.append(bib_text[at:j])
            i = j
        else:
            break
    if not entries:
        parts = re.split(r'(?=@\w+\s*\{)', bib_text)
        entries = [p for p in parts if p.strip()]
    return entries

def clean_bibtex_duplicates_with_report(
    input_path: str | Path | None = None,
    output_root: Path | None = None,
    reports_dir: Path | None = None,
    report_filename: str = DEFAULT_REPORT_FILENAME
):
    """
    Rens duplikater basert på (ISSN, tittel).

    - Leser .bib-filer fra input_path (standard: DEFAULT_INPUT_ROOT = <prosjektrot>/1. bib files)
    - Lagrer rensede filer i output_root (standard: <prosjektrot>/2.BibTex_clean_ISSN)
      * filnavn på output = samme som input, men i output-mappe
    - Lager ÉN samlet rapport i reports_dir / report_filename
      (standard: <prosjektrot>/Reports/check 1 clean ISSN.bib)
    """

    # Bestem input-rot
    if input_path is None:
        p = DEFAULT_INPUT_ROOT
    else:
        p = Path(input_path)

    # Finn inngangsfiler
    if p.is_dir():
        files = sorted([f for f in p.glob("*.bib") if f.is_file()])
    elif p.is_file() and p.suffix.lower() == ".bib":
        files = [p]
    else:
        raise FileNotFoundError(f"Fant ikke .bib på stien: {p}")

    if not files:
        raise FileNotFoundError(f"Ingen .bib-filer funnet i: {p}")

    # Output-mapper
    out_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    reports_path = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)

    # Samlerapport
    report_lines = []
    report_lines.append("% SAMLET RAPPORT: Check 1 – Clean ISSN")
    report_lines.append("% Generert av clean_bibtex_duplicates_with_report")
    report_lines.append("")

    all_stats = {}
    total_groups_all_files = 0
    total_removed_all_files = 0

    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        entries = split_entries(text)

        seen = set()     # (issn_norm, title_norm)
        kept_entries = []
        groups = {}      # key -> list[ {index, removed, entry} ]
        removed_count = 0

        for idx, e in enumerate(entries):
            raw_issn = extract_field(e, "issn")
            raw_title = extract_field(e, "title")
            norm_issn = normalize_issn(strip_braces_quotes(raw_issn) if raw_issn else None)
            norm_title = normalize_title(raw_title) if raw_title else None

            removed = False
            key = None
            if norm_issn and norm_title:
                key = (norm_issn, norm_title)
                if key in seen:
                    removed = True
                    removed_count += 1
                else:
                    seen.add(key)

            if not removed:
                kept_entries.append(e)

            if key:
                groups.setdefault(key, []).append({
                    "index": idx,
                    "removed": removed,
                    "entry": e
                })

        # Skriv renset fil til output-mappe
        cleaned_text = "\n\n".join(kept_entries) + "\n"
        out_clean_path = out_root / f"{f.name}"  # samme navn som inputfil
        out_clean_path.write_text(cleaned_text, encoding="utf-8")

        # Legg inn grupper i SAMLERAPPORTEN (kun grupper der minst én ble fjernet)
        group_no = 0
        for (issn, nt), lst in groups.items():
            if not any(it["removed"] for it in lst):
                continue
            group_no += 1
            total_groups_all_files += 1
            report_lines.append(f"% --- Fil: {f.name} | Gruppe #{group_no} ---")
            report_lines.append(f"% Nøkkel: ISSN={issn} | normalisert tittel='{nt}'")
            for it in lst:
                status = "REMOVED" if it["removed"] else "KEPT"
                report_lines.append(f"% {status} (index {it['index']})")
                report_lines.append(it["entry"])
                report_lines.append("")

        if group_no == 0:
            report_lines.append(f"% Fil: {f.name} – ingen duplikatgrupper (ingen poster ble fjernet).")
            report_lines.append("")

        total_removed_all_files += removed_count

        all_stats[str(f)] = {
            "total_entries": len(entries),
            "kept": len(kept_entries),
            "removed_duplicates": removed_count,
        }

    if total_groups_all_files == 0:
        report_lines.append("% Ingen duplikater funnet i noen filer.")

    report_text = "\n".join(report_lines).rstrip() + "\n"
    report_file = reports_path / report_filename
    # Sørg for .bib-ending selv om navnet mangler det
    if report_file.suffix.lower() != ".bib":
        report_file = report_file.with_suffix(".bib")
    report_file.write_text(report_text, encoding="utf-8")

    all_stats["_summary_"] = {
        "files_processed": len(files),
        "total_groups": total_groups_all_files,
        "total_removed": total_removed_all_files,
        "report_file": str(report_file),
        "output_root": str(out_root),
    }
    return all_stats

if __name__ == "__main__":
    stats = clean_bibtex_duplicates_with_report()  # bruker standard INPUT/OUTPUT-mapper
    print(stats)
