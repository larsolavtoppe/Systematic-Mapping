"""
Legg til 'type' i BibTeX-entries som mangler det, basert på entry-typen.

- Leser alle .bib fra SRC_DIR (ikke rekursivt)
- For hver entry som mangler 'type=', settes feltet:
    - via MAPPING nedenfor for kjente typer
    - ellers lik entry-typen i lowercase
- Skriver nye filer til DST_DIR med samme filnavn

Optimalisert for fart og uten uønsket innrykk på 'type'-linjen.
"""

import os
import glob
import re
from datetime import datetime
from pathlib import Path

# >>>>>>>>>>>>>>>>>>>>>> KONFIG (relativt til prosjektrot) <<<<<<<<<<<<<<<<<<<<<<
# Prosjektrot = mappa som inneholder "Python", "4.Remove collections", "5.Add Type", osv.
ROOT_DIR = Path(__file__).resolve().parent.parent

SRC_DIR = ROOT_DIR / "4.Remove collections"  # input: forrige steg
DST_DIR = ROOT_DIR / "5.Add Type"            # output: neste steg

# Mapping fra BibTeX entry-type -> ønsket 'type'-verdi.
# Ukjente typer får 'type' = entry-type i lowercase.
MAPPING = {
    "article": "article",
    "inproceedings": "conference paper",
    "conference": "conference paper",
    "proceedings": "proceedings",
    "incollection": "book-chapter",
    "inbook": "book-chapter",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "manual": "manual",
    "online": "webpage",
    "www": "webpage",
    "dataset": "dataset",
    "software": "software",
    "booklet": "booklet",
    "unpublished": "unpublished",
    "patent": "patent",
    "misc": "generic",
}
# <<<<<<<<<<<<<<<<<<<<<<<<<<>>>>>>>>>>>>>>>>>>>>>>>>>>

# Prekompilerte regex for fart
RE_ENTRY_HEAD = re.compile(r'@\s*([A-Za-z][A-Za-z_-]*)\s*([{\(])', re.A)
RE_TYPE_FIELD = re.compile(r'(?im)(^|[,\s])type\b\s*=')
RE_INDENT_FIELD = re.compile(r'\n([ \t]*)[A-Za-z][A-Za-z0-9_-]*\s*=')


def read_text_with_fallback(path, encodings=("utf-8-sig", "utf-8", "cp1252", "latin-1")):
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except Exception:
            pass
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_bibtex_entries(text):
    """
    Returnerer liste av (entry_type, raw_entry, start, end) ved å balansere { } / ( )
    """
    entries = []
    i, n = 0, len(text)
    while True:
        m = RE_ENTRY_HEAD.search(text, i)
        if not m:
            break
        entry_type = m.group(1)
        open_delim = m.group(2)
        close_delim = '}' if open_delim == '{' else ')'
        # finn startpos for åpningstegn
        k = m.start(2)
        # balanser
        depth = 0
        p = k
        while p < n:
            ch = text[p]
            if ch == open_delim:
                depth += 1
            elif ch == close_delim:
                depth -= 1
                if depth == 0:
                    p += 1
                    break
            p += 1
        if depth != 0:
            # ubalansert, hopp én char videre
            i = m.end()
            continue
        raw_entry = text[m.start():p]
        entries.append((entry_type, raw_entry, m.start(), p))
        i = p
    return entries


def has_type_field(raw_entry):
    # Søk etter 'type =' kun i felt-delen (etter første '{'/'(' )
    head = RE_ENTRY_HEAD.search(raw_entry)
    if not head:
        return False
    body = raw_entry[head.end():]
    return RE_TYPE_FIELD.search(body) is not None


def derive_type_value(entry_type):
    t = (entry_type or "").strip().lower()
    return MAPPING.get(t, t if t else "generic")


def insert_type_field(raw_entry, type_value):
    """
    Sett inn 'type = {<verdi>}' etter første komma, på ny linje, uten ekstra innrykk
    (eller med samme innrykk som øvrige felt hvis vi finner det).
    """
    head = RE_ENTRY_HEAD.search(raw_entry)
    if not head:
        return raw_entry

    # finn første komma etter '{'/'('
    open_pos = head.start(2)  # pos for '{' eller '('
    comma_pos = raw_entry.find(',', open_pos + 1)
    if comma_pos == -1:
        # ingen komma (uvanlig) -> sett rett før sluttklamme
        close_delim = '}' if raw_entry[open_pos] == '{' else ')'
        close_pos = raw_entry.rfind(close_delim)
        if close_pos == -1:
            return raw_entry
        return raw_entry[:close_pos] + ",\n" + f"type = {{{type_value}}}" + "\n" + raw_entry[close_pos:]

    after = raw_entry[comma_pos+1:]

    # Finn innrykk brukt av andre felt (hvis noen). Default: ingen innrykk.
    indent = ""
    m_ind = RE_INDENT_FIELD.search(after)
    if m_ind:
        indent = m_ind.group(1)  # eksakt samme innrykk som øvrige felt

    insertion = "\n" + indent + f"type = {{{type_value}}},"
    return raw_entry[:comma_pos+1] + insertion + raw_entry[comma_pos+1:]


def process_text_add_type(text):
    entries = extract_bibtex_entries(text)
    if not entries:
        return text, 0

    parts = []
    cursor = 0
    changes = 0

    for entry_type, raw_entry, start, end in entries:
        parts.append(text[cursor:start])

        etype = (entry_type or "").lower()
        if etype in {"comment", "preamble", "string"} or has_type_field(raw_entry):
            parts.append(raw_entry)
        else:
            type_value = derive_type_value(etype)
            fixed = insert_type_field(raw_entry, type_value)
            if fixed != raw_entry:
                changes += 1
            parts.append(fixed)

        cursor = end

    parts.append(text[cursor:])
    return "".join(parts), changes


def ensure_outdir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def main():
    src = SRC_DIR
    dst = DST_DIR

    if not src.is_dir():
        raise FileNotFoundError(f"Finner ikke mappen: {src}")
    ensure_outdir(dst)

    bib_files = sorted(src.glob("*.bib"))
    if not bib_files:
        print(f"Ingen .bib-filer funnet i: {src}")
        return

    total_entries_changed = 0
    started = datetime.now()
    print(f"Starter: {started:%Y-%m-%d %H:%M:%S}")
    print(f"Kilde: {src}")
    print(f"Mål  : {dst}\n")

    for path in bib_files:
        text = read_text_with_fallback(path)
        new_text, changes = process_text_add_type(text)

        out_path = dst / path.name
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_text)

        print(f"{path.name}: la til 'type' i {changes} entries")
        total_entries_changed += changes

    print("\nFerdig.")
    print(f"Totalt endrede entries: {total_entries_changed}")
    print(f"Filer skrevet til: {dst}")
    print(f"Slutt: {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()
