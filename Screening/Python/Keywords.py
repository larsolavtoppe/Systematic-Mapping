# searchwords_categorize.py
# -*- coding: utf-8 -*-
"""
- Leser alle .bib i INPUT_DIR (rekursivt)
- SØKER KUN I FELTENE: abstract, title, keywords (og "keyword" hvis brukt)
- Legger/oppdaterer searchWord = {...}
- Skriver <relativ_sti>/<original>_with_searchword.bib under OUTPUT_DIR
- Lager OUTPUT_DIR/searchWords/<Keyword>+<Antall>.bib (entry kan ligge i flere)
- Lager OUTPUT_DIR/searchWords/NoMatch+<Antall>.bib for oppføringer uten noen treff
"""

import os, re, sys
from collections import defaultdict
from pathlib import Path

# === KONFIG (relativ til prosjektrot) ===
# Prosjektrot = mappa som inneholder "Python", "5.Add Type", "6.utvidet søk", osv.
ROOT_DIR   = Path(__file__).resolve().parent.parent
INPUT_DIR  = ROOT_DIR / "5.Add Type"
OUTPUT_DIR = ROOT_DIR / "6.Keywords"

# Kun disse feltene brukes i søk (case-insensitiv sjekk på feltnavn)
SEARCH_FIELDS = {"abstract", "title", "keywords", "note", "author_keywords"}

KEYWORDS = [
    "FEM-design",
    "Artificial inteligence",   # bevisst stavevariant
    "digital fabrication",
    "Knowledge based design",
    "3D solid elements",
    "orthotropic",
    "Karamba3D",
    "Autodesk React",
    "Robot to Dynamo",
    "Finite element method",
    "Automation of FEM",
    "Conceptual design",
    "Architecture engineering construction",
    "AI-Driven",
    "Parametric design",
    "Algorithm aided design",
]

ALIASES = {
    "FEM-design": [
        "FEM design",
        "FEMdesign",
        "FEM-Design",
        "StruSoft FEM-Design",
    ],
    "Artificial inteligence": [
        "Artificial intelligence",
        "machine intelligence",
    ],
    "digital fabrication": [
        "digital-fabrication",
        "digitalfabrication",
        "computer-aided fabrication",
        "CAD/CAM fabrication",
    ],
    "Knowledge based design": [
        "knowledge-based design",
        "knowledgebased design",
        "knowledge driven design",
    ],
    "3D solid elements": [
        "3D-solid elements",
        "solid 3D elements",
        "solid-element model",
    ],
    "orthotropic": [
        "orthotropy",
        "orthotropic material",
        "orthotropic behaviour",
    ],
    "Karamba3D": [
        "Karamba",
        "Karamba 3D",
    ],
    "Autodesk React": [
        "Autodesk React",
        "React Autodesk",
    ],
    "Robot to Dynamo": [
        "Robot Structural Analysis to Dynamo",
        "Robot-Dynamo",
        "RSA to Dynamo",
    ],
    "Finite element method": [
        "finite element analysis",
        "finite-element method",
        "finite-element analysis",
    ],
    "Automation of FEM": [
        "automated FEM",
        "automation in FEM",
        "FEM automation",
        "automated finite element",
    ],
    "Conceptual design": [
        "concept design",
        "conceptual-design",
        "early-stage design",
    ],
    "Architecture engineering construction": [
        "AEC",
        "architecture, engineering and construction",
        "architecture engineering & construction",
    ],
    "AI-Driven": [
        "AI driven",
        "AI–driven",   # med en-dash
        "AI powered",
        "AI-based",
    ],
    "Parametric design": [
        "parametric-design",
        "parametrics",
        "parametric modelling",
        "parametric modeling",
    ],
    "Algorithm aided design": [
        "algorithm-aided design",
        "algorithmic design",
        "algorithmaided design",
        "AAD",
        "Computer aided design",
        "computer-aided design",
    ],
}


# === HJELPERE ===
def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def iter_bib_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".bib"):
                yield os.path.join(dirpath, fn)

def split_entries(bibtext):
    pieces = []; i = 0; n = len(bibtext)
    while i < n:
        at = bibtext.find('@', i)
        if at == -1:
            pieces.append(("non-entry", bibtext[i:])); break
        if at > i:
            pieces.append(("non-entry", bibtext[i:at]))
        j = at + 1
        while j < n and bibtext[j] not in '{(':
            j += 1
        if j >= n or bibtext[j] not in '{(':
            pieces.append(("non-entry", bibtext[at:j])); i = j; continue
        open_char = bibtext[j]; close_char = '}' if open_char == '{' else ')'
        depth = 0; k = j
        while k < n:
            c = bibtext[k]
            if c == open_char: depth += 1
            elif c == close_char:
                depth -= 1
                if depth == 0:
                    pieces.append(("entry", bibtext[at:k+1])); i = k + 1; break
            k += 1
        else:
            pieces.append(("entry", bibtext[at:])); i = n
    return pieces

def parse_entry_header(entry_text):
    m = re.match(r'@([A-Za-z]+)\s*([({])', entry_text, flags=re.S)
    if not m: return None, None, entry_text, '{', '}'
    entry_type = m.group(1); open_char = m.group(2)
    close_char = '}' if open_char == '{' else ')'
    start = m.end(0); depth = 1; i = start; n = len(entry_text)
    citekey_chars = []
    while i < n:
        c = entry_text[i]
        if c == open_char: depth += 1
        elif c == close_char: depth -= 1; break
        elif c == ',' and depth == 1: i += 1; break
        else: citekey_chars.append(c)
        i += 1
    citekey = ''.join(citekey_chars).strip()
    body = entry_text[i:n]
    body_inner = body[:-1] if body.endswith(close_char) else body
    return entry_type, citekey, body_inner, open_char, close_char

def parse_fields(body_text):
    i = 0; n = len(body_text); fields = []
    while i < n:
        while i < n and body_text[i] in " \t\r\n,":
            i += 1
        if i >= n: break
        name_start = i
        while i < n and re.match(r'[A-Za-z0-9_:\-]', body_text[i]):
            i += 1
        name = body_text[name_start:i].strip()
        while i < n and body_text[i].isspace():
            i += 1
        if i >= n or body_text[i] != '=':
            while i < n and body_text[i] != ',': i += 1
            if i < n: i += 1
            continue
        i += 1
        while i < n and body_text[i].isspace():
            i += 1
        val, _raw_seg, i = read_value(body_text, i)
        fields.append((name, val, _raw_seg))
    return fields

def read_value(s, i):
    n = len(s); start = i; parts = []; end_index = i
    while i < n:
        while i < n and s[i].isspace(): i += 1
        if i >= n: break
        if s[i] == '{':
            val, j = read_braced(s, i); parts.append(val); i = j
        elif s[i] == '"':
            val, j = read_quoted(s, i); parts.append(val); i = j
        else:
            j = i
            while j < n and s[j] not in ',#\r\n': j += 1
            parts.append(s[i:j].strip()); i = j
        while i < n and s[i].isspace(): i += 1
        if i < n and s[i] == '#': i += 1; continue
        if i < n and s[i] == ',': end_index = i + 1; break
        else: end_index = i; break
    return ''.join(parts).strip(), s[start:end_index], end_index

def read_braced(s, i):
    n = len(s); assert s[i] == '{'
    j = i + 1; depth = 1; out = []
    while j < n:
        c = s[j]
        if c == '{': depth += 1; out.append(c)
        elif c == '}':
            depth -= 1
            if depth == 0: return ''.join(out), j + 1
            out.append(c)
        else: out.append(c)
        j += 1
    return ''.join(out), n

def read_quoted(s, i):
    n = len(s); assert s[i] == '"'
    j = i + 1; out = []; esc = False
    while j < n:
        c = s[j]
        if esc: out.append(c); esc = False
        else:
            if c == '\\': esc = True
            elif c == '"': return ''.join(out), j + 1
            else: out.append(c)
        j += 1
    return ''.join(out), n

def rebuild_entry(entry_type, citekey, fields, open_char='{', close_char='}'):
    lines = [f"@{entry_type}{open_char}{citekey},"]
    for name, value, _raw in fields:
        lines.append(f"  {name} = {{{value}}},")
    lines.append(f"{close_char}")
    return "\n".join(lines)

def normalize(s):
    return ' '.join((s or "").lower().split())

def build_aliases(keywords, alias_map):
    """Bygger alias-ordbok og rydder KEYWORDS for duplikater/whitespace."""
    seen = set(); cleaned = []
    for k in keywords:
        k2 = k.strip()
        if not k2:
            continue
        if k2.lower() in seen:
            continue
        seen.add(k2.lower()); cleaned.append(k2)

    # Ta med alias-nøkler også (om de ikke allerede er i KEYWORDS)
    all_keys = list(cleaned)
    for k in alias_map.keys():
        k2 = k.strip()
        if k2 and k2.lower() not in seen:
            seen.add(k2.lower())
            all_keys.append(k2)

    aliases = defaultdict(list)
    for k in all_keys:
        aliases[k] = [k]  # alltid med hovedordet selv
        for a in alias_map.get(k, []):
            a2 = a.strip()
            if a2 and a2 not in aliases[k]:
                aliases[k].append(a2)
    return aliases, cleaned  # cleaned = stabil rekkefølge ved utskrift

def match_keywords(text, aliases):
    """Case-insensitiv delstrengsøk på normalisert tekst."""
    t = normalize(text); hits = []
    for canonical, alias_list in aliases.items():
        for a in alias_list:
            if normalize(a) in t:
                hits.append(canonical); break
    # unike i rekkefølge
    seen = set(); uniq = []
    for h in hits:
        key = h.lower()
        if key not in seen:
            seen.add(key); uniq.append(h)
    return uniq  # tom liste ved null treff

def process_bib_text(bibtext, aliases):
    pieces = split_entries(bibtext)
    rebuilt_pieces = []
    per_kw = defaultdict(list)
    nomatch_entries = []

    for kind, chunk in pieces:
        if kind == "non-entry":
            rebuilt_pieces.append(chunk); continue

        etype, key, body, o, c = parse_entry_header(chunk)
        if not etype:
            rebuilt_pieces.append(chunk); continue

        fields = parse_fields(body)

        # Bygg søketekst KUN fra ønskede felt (ignorér evt. eksisterende searchWord)
        search_values = []
        idx_sw = None
        for i, (name, val, _raw) in enumerate(fields):
            lname = name.lower()
            if lname == "searchword":
                idx_sw = i
                continue
            if lname in SEARCH_FIELDS:
                search_values.append(val)

        base_text = " ".join(v for v in search_values if v)

        hits = match_keywords(base_text, aliases)
        search_val = "; ".join(hits) if hits else "NoMatch"

        # sett/oppdater searchWord
        if idx_sw is None:
            fields.append(("searchWord", search_val, None))
        else:
            fields[idx_sw] = ("searchWord", search_val, None)

        rebuilt = rebuild_entry(etype, key, fields, o, c)
        rebuilt_pieces.append(rebuilt)

        if hits:
            for h in hits:
                per_kw[h].append(rebuilt)
        else:
            nomatch_entries.append(rebuilt)

    return "".join(rebuilt_pieces), per_kw, nomatch_entries

# === MAIN ===
def main():
    input_dir_str = str(INPUT_DIR)
    output_dir_str = str(OUTPUT_DIR)

    if not os.path.isdir(input_dir_str):
        print(f"[FEIL] Fant ikke INPUT_DIR: {input_dir_str}")
        sys.exit(1)

    aliases, ordered_keywords = build_aliases(KEYWORDS, ALIASES)

    outdir_kw = os.path.join(output_dir_str, "searchWords")
    os.makedirs(outdir_kw, exist_ok=True)

    aggregated_per_kw = defaultdict(list)
    aggregated_nomatch = []
    file_count = 0

    for bibpath in iter_bib_files(input_dir_str):
        file_count += 1
        try:
            bibtext = read_file(bibpath)
        except Exception as e:
            print(f"[ADVARSEL] Lese-feil {bibpath}: {e}")
            continue

        modified, per_kw, nomatch_entries = process_bib_text(bibtext, aliases)

        # Skriv modifisert fil under OUTPUT_DIR, speil relativ sti fra INPUT_DIR
        rel = os.path.relpath(bibpath, input_dir_str)
        base, ext = os.path.splitext(rel)
        out_bib = os.path.join(output_dir_str, f"{base}_with_searchword{ext}")

        try:
            write_file(out_bib, modified)
            print(f"[OK] Skrev: {out_bib}")
        except Exception as e:
            print(f"[FEIL] Skrive-feil {out_bib}: {e}")

        for k, entries in per_kw.items():
            aggregated_per_kw[k].extend(entries)
        aggregated_nomatch.extend(nomatch_entries)

    if file_count == 0:
        print("[ADVARSEL] Ingen .bib-filer funnet i INPUT_DIR.")
        sys.exit(0)

    # Skriv per-keyword filer i stabil rekkefølge
    for kw in ordered_keywords:
        entries = aggregated_per_kw.get(kw, [])
        safe_kw = re.sub(r'[^\w\s\-\+\.]', '_', kw).strip().replace(" ", "_")
        path = os.path.join(outdir_kw, f"{safe_kw}+{len(entries)}.bib")
        write_file(path, "\n\n".join(entries) + ("\n" if entries else ""))
        print(f"[OK] Kategori '{kw}': {len(entries)} -> {path}")

    # Skriv NoMatch KUN for oppføringer uten noen treff
    path_nomatch = os.path.join(outdir_kw, f"NoMatch+{len(aggregated_nomatch)}.bib")
    write_file(path_nomatch, "\n\n".join(aggregated_nomatch) + ("\n" if aggregated_nomatch else ""))
    print(f"[OK] Kategori 'NoMatch': {len(aggregated_nomatch)} -> {path_nomatch}")

    print(f"[FERDIG] Prosesserte {file_count} .bib-fil(er). Resultater i: {output_dir_str}")

if __name__ == "__main__":
    main()
