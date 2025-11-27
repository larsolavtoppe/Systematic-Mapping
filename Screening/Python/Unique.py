# -*- coding: utf-8 -*-
"""
BibTeX merger & deduper (DOI -> Title(+Year) -> Abstract) + BibTeX-rapport:
- Bevarer original rekkefølge/format i hver entry.
- Legger `source` (hvis mangler) og alltid `actualSearch` nederst i hver entry,
  med samme innrykk som de andre feltene.
- Deduper i prioritert rekkefølge:
  1) Normalisert DOI
  2) Normalisert Title + Year (eller Title alene hvis Year mangler)
  3) Normalisert Abstract
- Skriver ut: totalt før, fjernet, igjen.
- Lager en BibTeX-rapport med grupper pr. strategi; grupper og status markeres med kommentarer (%),
  og hver entry skrives i sin helhet.
"""

import os
import glob
from pathlib import Path
import re
import html
import unicodedata
from urllib.parse import unquote
from collections import Counter, defaultdict

# -------- PROSJEKTSTIER (relativt til denne fila) --------
# Prosjektrot = mappa som inneholder "Python", "2.BibTex_clean_ISSN", "3.Unique", "Reports", ...
ROOT_DIR = Path(__file__).resolve().parent.parent

# Leser fra output-mappa til forrige steg:
INPUT_DIR   = ROOT_DIR / "2.BibTex_clean_ISSN"
# Skriver merged/unik fil til ny mappe:
OUTPUT_DIR  = ROOT_DIR / "3.Unique"
OUTPUT_FILE = "merged_unique.bib"

# Rapporter til samme Reports-mappe som forrige script:
REPORT_DIR  = ROOT_DIR / "Reports"
REPORT_FILE = "unique_report.bib"  # BibTeX-rapport

ENTRY_START_RE = re.compile(r'@(?P<type>[A-Za-z]+)\s*\{', re.M)
DOI_RE = re.compile(r'\b10\.\d{4,9}/\S+\b', re.I)

# ---------- Hjelpefunksjoner ----------
def split_filename_parts(fp: str):
    """
    Returnerer (actual_search, source_val) fra filnavn uten extension.
    'før "-"' -> actualSearch, 'etter "-"' -> source.
    Hvis '-' mangler: source_val=None.
    """
    base = os.path.splitext(os.path.basename(fp))[0]
    if "-" in base:
        left, right = base.split("-", 1)
        return (left.strip() or "unknown"), (right.strip() or "unknown")
    return (base.strip() or "unknown"), None

def extract_entries(text: str):
    """
    Del rå BibTeX-tekst i komplette entries ved balansering av klammer.
    Returnerer liste med entry-tekster.
    """
    entries = []
    i = 0
    n = len(text)
    while True:
        m = ENTRY_START_RE.search(text, i)
        if not m:
            break
        start = m.start()
        brace_open = text.find("{", m.end() - 1)
        if brace_open == -1:
            break
        depth = 0
        j = brace_open
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    entries.append(text[start:end])
                    i = end
                    break
            j += 1
        else:
            entries.append(text[start:n])
            i = n
    return entries

def get_field(entry_text: str, field: str) -> str | None:
    """
    Robust feltleser som tåler CRLF, trailing komma, linebreaks i verdien, {…} eller "…".
    """
    m = re.search(rf'(?im)^\s*{re.escape(field)}\s*=\s*\{{(.*?)\}}\s*,?', entry_text, flags=re.S)
    if m:
        return m.group(1).strip()
    m = re.search(rf'(?im)^\s*{re.escape(field)}\s*=\s*"(.*?)"\s*,?', entry_text, flags=re.S)
    if m:
        return m.group(1).strip()
    return None

def _strip_latex(s: str) -> str:
    s = re.sub(r'\\[a-zA-Z]+(\{[^{}]*\})?', ' ', s)
    s = s.replace(r'\&', '&').replace(r'\/', '/').replace(r'\%', '%')
    return s

def _fold_accents(s: str) -> str:
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(ch for ch in nfkd if not unicodedata.combining(ch))

def _norm_text(s: str) -> str:
    """
    Robust normalisering for tittel/abstract/år:
    - HTML-unescape, URL-decode
    - fjern BibTeX-klammer og HTML-tags
    - fjern LaTeX-kommandoer og diakritika
    - lowercase, fjern skilletegn, komprimer whitespace
    """
    if s is None:
        return ""
    s = html.unescape(s)
    s = unquote(s)
    s = re.sub(r'\{|\}', '', s)
    s = re.sub(r'<[^>]*>', ' ', s)
    s = _strip_latex(s)
    s = _fold_accents(s)
    s = s.lower()
    s = re.sub(r'[\.,;:\-\–\—\(\)\[\]\"\'`´’“”/\\_~!?\|\+&^%$#@*=<>]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _normalize_doi(raw: str) -> str | None:
    """
    Normaliser DOI:
    - trekk ut DOI (fra verdi eller doi.org-lenke)
    - lowercase, trim, fjern trailing punktuering
    - fjern evt. http(s)://(dx.)doi.org/ og 'doi:'-prefiks
    - valider mot 10.xxxx/...
    """
    if not raw:
        return None
    raw = html.unescape(raw)
    raw = unquote(raw)
    m = DOI_RE.search(raw)
    if m:
        doi = m.group(0)
    else:
        m = re.search(r'(?:https?://)?(?:dx\.)?doi\.org/([^?\s]+)', raw, re.I)
        if m:
            doi = m.group(1)
        else:
            doi = raw
    doi = doi.strip().lower()
    doi = doi.rstrip(' .;,')
    doi = re.sub(r'^(https?://)?(dx\.)?doi\.org/', '', doi)
    doi = re.sub(r'^\s*doi:\s*', '', doi)
    doi = doi.replace(' ', '')
    return doi if DOI_RE.match(doi) else None

def _find_normalized_doi(entry_text: str) -> str | None:
    doi_field = _normalize_doi(get_field(entry_text, 'doi'))
    if doi_field:
        return doi_field
    url_field = _normalize_doi(get_field(entry_text, 'url'))
    return url_field

def has_source_field(entry_text: str) -> bool:
    try:
        first_brace = entry_text.index("{")
        after_header = entry_text.index(",", first_brace + 1) + 1
    except ValueError:
        after_header = 0
    body = entry_text[after_header:]
    return re.search(r'(?im)^\s*source\s*=', body) is not None

def detect_common_field_indent(entry_text: str) -> str:
    """
    Finn mest brukte innrykk (whitespace) blant feltlinjene i body.
    Fallback: "" (ingen innrykk).
    """
    try:
        first_brace = entry_text.index("{")
        after_header = entry_text.index(",", first_brace + 1) + 1
    except ValueError:
        after_header = 0
    last_brace = entry_text.rfind("}")
    if last_brace == -1:
        last_brace = len(entry_text)
    body = entry_text[after_header:last_brace]
    lines = body.splitlines()
    indents = []
    for line in lines:
        if not line.strip():
            continue
        if "=" in line:
            m = re.match(r'^(\s*)', line)
            indents.append(m.group(1) if m else "")
    if not indents:
        return ""
    counts = Counter(indents)
    max_count = max(counts.values())
    candidates = [i for i, c in counts.items() if c == max_count]
    return min(candidates, key=len)

def append_fields(entry_text: str, actual_search: str, source_val: str | None) -> str:
    """
    Legg til 'source' (hvis mangler) og alltid 'actualSearch' nederst rett før '}'.
    """
    last_brace = entry_text.rfind("}")
    if last_brace == -1:
        last_brace = len(entry_text)
        closing = ""
    else:
        closing = "}"

    indent = detect_common_field_indent(entry_text)
    newline = "\n" if "\n" in entry_text else "\r\n"

    to_insert = ""
    if source_val and not has_source_field(entry_text):
        to_insert += f"{indent}source = {{{source_val}}},{newline}"
    to_insert += f"{indent}actualSearch = {{{actual_search}}}{newline}"

    return entry_text[:last_brace] + to_insert + closing + entry_text[last_brace+1:]

def get_bibtex_id(entry_text: str) -> str:
    """
    Henter BibTeX-ID fra header: @type{ID, ...
    """
    try:
        first_brace = entry_text.index("{")
        comma = entry_text.index(",", first_brace + 1)
        return entry_text[first_brace+1:comma].strip()
    except ValueError:
        return ""

# ---------- Dedup-nøkkel ----------
def build_dedupe_key(entry_text: str) -> tuple[str, str]:
    """
    Returnerer (strategi, nøkkel) i prioritert rekkefølge:
      'DOI'         -> normalisert DOI
      'TITLE_YEAR'  -> "<norm_title>::<year>"
      'TITLE'       -> "<norm_title>"
      'ABSTRACT'    -> "<norm_abstract>"
      'FALLBACK'    -> "<norm_body>"
    """
    doi = _find_normalized_doi(entry_text)
    if doi:
        return ('DOI', doi)

    title = get_field(entry_text, 'title')
    if title:
        t_norm = _norm_text(title)
        year = get_field(entry_text, 'year')
        if year:
            y = re.search(r'\d{4}', year)
            if y:
                return ('TITLE_YEAR', f"{t_norm}::{y.group(0)}")
        return ('TITLE', t_norm)

    abstract = get_field(entry_text, 'abstract')
    if abstract:
        return ('ABSTRACT', _norm_text(abstract))

    # Siste utvei (bør sjelden skje dersom tittel/abstract finnes)
    return ('FALLBACK', _norm_text(entry_text))

# ---------- Prosessering + rapport ----------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    bib_files = sorted(glob.glob(str(INPUT_DIR / "*.bib")))
    if not bib_files:
        print(f"Fant ingen .bib-filer i: {INPUT_DIR}")
        return

    # Telle totalt før fjerning
    total_before = 0
    raw_entries_per_file: dict[str, list[str]] = {}
    for fp in bib_files:
        with open(fp, "r", encoding="utf-8-sig") as f:
            text = f.read()
        entries = extract_entries(text)
        raw_entries_per_file[fp] = entries
        total_before += len(entries)

    # Prosess: legg til felter, bygg grupper etter dedup-nøkkel, og behold kun første pr. nøkkel
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)  # (strategy, key) -> list of items
    seen_keys: set[tuple[str, str]] = set()
    merged_entries: list[str] = []

    for fp in bib_files:
        actual_search, source_from_name = split_filename_parts(fp)
        for entry_text in raw_entries_per_file[fp]:
            # legg til felter nederst (beholder rekkefølge ellers)
            updated = append_fields(entry_text, actual_search, source_from_name)

            strategy, key = build_dedupe_key(updated)
            title_raw = get_field(updated, 'title') or ""
            year = get_field(updated, 'year') or ""
            source_field = get_field(updated, 'source') or (source_from_name or "")
            bib_id = get_bibtex_id(updated)

            item = {
                "kept": False,           # settes under
                "file": os.path.basename(fp),
                "bib_id": bib_id,
                "title_raw": title_raw,
                "year": year,
                "source": source_field,
                "actualSearch": actual_search,
                "strategy": strategy,
                "key": key,
                "entry_text": updated,   # FULL entry-tekst (etter felttillegg)
            }

            if (strategy, key) in seen_keys:
                item["kept"] = False
            else:
                item["kept"] = True
                seen_keys.add((strategy, key))
                merged_entries.append(updated)

            groups[(strategy, key)].append(item)

    total_after = len(merged_entries)
    removed = total_before - total_after

    # Skriv ut merged
    out_path = OUTPUT_DIR / OUTPUT_FILE
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(("\n\n").join(merged_entries))
        f.write("\n")

    print(f"Totalt før fjerning: {total_before}")
    print(f"Fjernet som duplikater: {removed}")
    print(f"Gikk igjennom (unik): {total_after}")
    print(f"Lagret som: {out_path}")

    # Bygg BibTeX-rapport: kun grupper med >1 element (faktiske duplikater)
    dup_groups = [ (k, v) for k, v in groups.items() if len(v) > 1 ]
    # sorter: først etter strategi (i prioritert rekkefølge), så etter gruppestørrelse synkende
    strat_order = {'DOI': 0, 'TITLE_YEAR': 1, 'TITLE': 2, 'ABSTRACT': 3, 'FALLBACK': 4}
    dup_groups.sort(key=lambda kv: (strat_order.get(kv[0][0], 9), -len(kv[1])))

    report_lines = []
    report_lines.append("% UNIQUE REPORT – grupper av like (dedupe-strategi) (BibTeX-format)")
    report_lines.append(f"% Input-mappe : {INPUT_DIR}")
    report_lines.append(f"% Antall entries totalt: {total_before}")
    report_lines.append(f"% Fjernet som duplikater: {removed}")
    report_lines.append(f"% Antall unike (beholdt): {total_after}")
    report_lines.append(f"% Antall duplikat-grupper: {len(dup_groups)}")
    report_lines.append("% ---------------------------------")

    for idx, ((strategy, key), items) in enumerate(dup_groups, start=1):
        # Vis et eksempel på tittel hvis finnes
        example_title = next((it["title_raw"] for it in items if it["title_raw"]), "")
        report_lines.append(f"% Gruppe {idx}  (antall: {len(items)})  [Strategi: {strategy}]")
        if strategy == 'DOI':
            report_lines.append(f"% Nøkkel (DOI): {key}")
        elif strategy == 'TITLE_YEAR':
            tpart, ypart = key.split("::", 1) if "::" in key else (key, "")
            report_lines.append(f"% Nøkkel (TITLE_YEAR): <normalisert tittel> + år={ypart}")
        elif strategy == 'TITLE':
            report_lines.append(f"% Nøkkel (TITLE): <normalisert tittel>")
        elif strategy == 'ABSTRACT':
            report_lines.append(f"% Nøkkel (ABSTRACT): <normalisert abstract>")
        else:
            report_lines.append(f"% Nøkkel (FALLBACK)")
        if example_title:
            report_lines.append(f"% Tittel (eksempel): {example_title}")

        for j, it in enumerate(items, start=1):
            status = "BEHOLDT" if it["kept"] else "FJERNET"
            report_lines.append(
                f"% --- {j:02d}. [{status}]  ID={it['bib_id']}  År={it['year']}  "
                f"Kilde={it['source']}  Fil={it['file']}"
            )
            # Hele BibTeX-entryen (etter felttillegg):
            report_lines.append(it["entry_text"].rstrip())
            report_lines.append("")  # tom linje mellom entries i samme gruppe

        report_lines.append("% ---------------------------------")  # separator mellom grupper

    # Skriv rapport
    report_path = REPORT_DIR / REPORT_FILE
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    print(f"Rapport lagret som: {report_path}")

if __name__ == "__main__":
    main()
