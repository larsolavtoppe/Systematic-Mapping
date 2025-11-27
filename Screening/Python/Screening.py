# screening_filter.py
# -*- coding: utf-8 -*-
"""
Filtrerer BibTeX-entries basert på en modulær liste av filtre (FILTERS).
- Leser EN .bib-fil fra INPUT_DIR (automatisk valg: foretrekker *_with_searchword.bib, ellers nyeste .bib)
- Skriver KUN entries som passerer alle filtre til OUTPUT_DIR som <navn>_screened.bib
- Lager BIBTEX-rapporter over entries som ble fjernet (og språk-annotering), delt opp per "bucket" (år, språk, type, searchWord, felt, regex, logikk)

Språk:
- Når by_language({...}) er satt:
  - language i settet  => beholdes.
  - language ikke i settet => fjernes og legges i språk-rapport (REMOVED).
  - manglende language => beholdes, men legges i språk-rapport (INCLUDED (missing language)).

Viktig endring:
- by_types({...}) sjekker NÅ feltet `type = {...}` (ikke @entry-typen). Bruk verdier som finnes i feltet, f.eks.
  {"journal-article", "conference paper"}.
"""

from pathlib import Path

# === KONFIGURASJON (relativ til prosjektrot) ===
# Prosjektrot = mappa som inneholder "Python", "6.utvidet søk", "7.Screening", "Reports", ...
ROOT_DIR   = Path(__file__).resolve().parent.parent
INPUT_DIR   = ROOT_DIR / "6.Keywords"
OUTPUT_DIR  = ROOT_DIR / "7.Screening"
REPORTS_DIR = ROOT_DIR / "Reports"

# --- Slå av/på filtre her: (tomme set/str/list => blir ignorert) ---
def active_filters():
    return [
        by_year_range(2015, 2026),
        # NB: Sjekker feltet `type = {...}`:
        by_types({"article"}),  # behold kun disse typene; tomt sett ignoreres
        by_language({"english"}),           # behold kun english; MISSING language beholdes, men logges
        by_searchword_min_len(2),
        by_field_not_equal("searchWord", "NoMatch"),
       
    ]


# === HJELPEFUNKSJONER ===
import os, re, sys
from typing import Callable, Dict, Iterable, List, Optional

_entry_start_re = re.compile(r'^\s*@([A-Za-z]+)\s*\{\s*([^,]*)\s*,?', re.UNICODE | re.MULTILINE)

def normalize_value(v: str) -> str:
    """Fjerner {…} eller "…" rundt enkeltverdi og trimmer. Tar første linje."""
    v = v.strip()
    first_line = v.splitlines()[0].strip()
    if (first_line.startswith('{') and first_line.endswith('}')) or \
       (first_line.startswith('"') and first_line.endswith('"')):
        first_line = first_line[1:-1].strip()
    return first_line

def extract_all_fields(entry_text: str) -> Dict[str, str]:
    """
    Grov parser: henter første forekomst av hvert felt (case-insensitivt navn).
    Legger også til 'searchword_list' = splittet på ';'
    """
    fields: Dict[str, str] = {}
    for m in re.finditer(r'(?im)^[ \t]*([A-Za-z0-9_:\-]+)[ \t]*=[ \t]*(".*?"|\{.*?\}|[^,\r\n]+)', entry_text, flags=re.DOTALL):
        name = m.group(1).strip().lower()
        if name in fields:
            continue
        fields[name] = normalize_value(m.group(2))
    if 'language' not in fields and 'langid' in fields:
        fields['language'] = fields['langid']
    sw = fields.get('searchword')
    fields['searchword_list'] = [p.strip() for p in sw.split(';') if p.strip()] if sw is not None else []
    return fields

def iter_entries_with_raw(text: str):
    """Yielder (raw_block, entry_type, entry_key) for hver @entry."""
    i = 0; n = len(text)
    while i < n:
        m = _entry_start_re.search(text, i)
        if not m: break
        start = m.start(); etype = m.group(1)
        brace_pos = text.find('{', m.end(1))
        if brace_pos == -1: i = m.end(); continue
        depth = 0; j = brace_pos
        while j < n:
            c = text[j]
            if c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    yield text[start:end], etype, m.group(2)
                    i = end; break
            j += 1
        else:
            i = n; break

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def choose_input_file(folder):
    """Foretrekker *_with_searchword.bib, ellers nyeste .bib i mappen."""
    folder = str(folder)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Fant ikke mappe: {folder}")
    bibs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.bib')]
    if not bibs:
        raise FileNotFoundError(f"Ingen .bib-filer i: {folder}")
    if len(bibs) == 1:
        return bibs[0]
    prefer = [p for p in bibs if p.lower().endswith('_with_searchword.bib')]
    if prefer:
        prefer.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return prefer[0]
    bibs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return bibs[0]

def make_output_path(input_file: str, out_dir) -> str:
    base = os.path.splitext(os.path.basename(input_file))[0]
    return os.path.join(str(out_dir), base + "_screened.bib")

# --- Bevar "type = {entrytype}" ved behov (gjøres ETTER filtrering) ---
def has_type_field(raw_entry: str) -> bool:
    return re.search(r'(?im)^[ \t]*type[ \t]*=', raw_entry) is not None

def _detect_newline_style(lines):
    for ln in reversed(lines):
        if ln.endswith('\r\n'): return '\r\n'
        if ln.endswith('\n'):  return '\n'
    return '\n'

def _last_significant_before_closing(lines, close_idx):
    for idx in range(close_idx - 1, -1, -1):
        s = lines[idx].strip()
        if not s or s.startswith('%'): continue
        return idx
    return None

def _ensure_trailing_comma_on_line(line: str) -> str:
    if line.endswith('\r\n'): nl = '\r\n'; core = line[:-2]
    elif line.endswith('\n'): nl = '\n'; core = line[:-1]
    else: nl = ''; core = line
    p = core.find('%')
    main = core[:p] if p >= 0 else core
    comment = core[p:] if p >= 0 else ''
    main_r = main.rstrip()
    return (main + comment + nl) if main_r.endswith(',') else (main_r + ',' + (comment or '') + nl)

def ensure_type_field_as_class(raw_entry: str, entry_type: str) -> str:
    if has_type_field(raw_entry): return raw_entry
    class_value = entry_type.lower()
    trimmed = raw_entry.rstrip()
    if not trimmed.endswith('}'): return raw_entry
    lines = trimmed.splitlines(keepends=True)
    close_idx = None
    for idx in range(len(lines)-1, -1, -1):
        if re.match(r'^[ \t]*}\s*$', lines[idx]): close_idx = idx; break
    if close_idx is None: return raw_entry
    newline = _detect_newline_style(lines)
    last_sig_idx = _last_significant_before_closing(lines, close_idx)
    indent = "  "
    if last_sig_idx is not None:
        m = re.match(r'^([ \t]*)', lines[last_sig_idx])
        if m: indent = m.group(1) or indent
        lines[last_sig_idx] = _ensure_trailing_comma_on_line(lines[last_sig_idx])
    new_type_line = f"{indent}type = {{{class_value}}}{newline}"
    lines.insert(close_idx, new_type_line)
    result = ''.join(lines)
    if raw_entry.endswith('\n') and not result.endswith('\n'):
        result += '\n'
    return result


# === FILTER-KOMBINATORER + MERKING (for rapportering) ===
def _mark(f, bucket: str, label: str):
    try: f.__name__ = label
    except Exception: pass
    setattr(f, "label", label)
    setattr(f, "bucket", bucket)
    return f

def all_of(filters: Iterable[Callable[[str, Dict[str, str], str], bool]]):
    fl = [f for f in filters if f]
    if not fl: return _mark(lambda e,fd,r: True, "logic:all", "all_of[empty]")
    def _f(e,fd,r): return all(fn(e,fd,r) for fn in fl)
    label = "all_of[" + ",".join(getattr(fn,"label",getattr(fn,"__name__","filter")) for fn in fl) + "]"
    return _mark(_f, "logic:all", label)

def any_of(filters: Iterable[Callable[[str, Dict[str, str], str], bool]]):
    fl = [f for f in filters if f]
    if not fl: return _mark(lambda e,fd,r: True, "logic:any", "any_of[empty]")
    def _f(e,fd,r): return any(fn(e,fd,r) for fn in fl)
    label = "any_of[" + ",".join(getattr(fn,"label",getattr(fn,"__name__","filter")) for fn in fl) + "]"
    return _mark(_f, "logic:any", label)


# === FILTER-BYGGESTEINER (alle ignorerer når “tomme”) ===
def by_year_range(min_year: int, max_year: int):
    def _f(etype, fields, raw):
        y = fields.get('year')
        if not y: return False
        m = re.search(r'\d{4}', y)
        if not m: return False
        yi = int(m.group(0))
        return (min_year <= yi <= max_year)
    return _mark(_f, "year", f"by_year_range[{min_year}-{max_year}]")

def by_types(allowed: Iterable[str]):
    """
    Beholder entries hvor FELTET 'type' (case-insensitivt) er i allowed.
    Tomt sett => ignorer.
    """
    allowed = {t.strip().lower() for t in (allowed or []) if str(t).strip()}
    if not allowed:
        return _mark(lambda e,fd,r: True, "type", "by_types[ignored]")
    def _f(etype, fields, raw):
        return fields.get("type", "").strip().lower() in allowed
    f = _mark(_f, "type", f"by_types[type in {{{', '.join(sorted(allowed))}}}]")
    setattr(f, "allowed_types", sorted(allowed))
    return f

def by_language(langs: Iterable[str]):
    """
    Behold entries der language ∈ langs.
    VIKTIG: Manglende language (tom streng) **passerer** alltid (beholdes),
            men logges i språk-rapport som 'INCLUDED (missing language)'.
    """
    langs = {l.strip().lower() for l in (langs or []) if l and l.strip()}
    if not langs: return _mark(lambda e,fd,r: True, "language", "by_language[ignored]")
    def _f(etype, fields, raw):
        lang_val = fields.get('language','').strip().lower()
        if lang_val == "":   # behold manglende
            return True
        return lang_val in langs
    f = _mark(_f, "language", f"by_language[{', '.join(sorted(langs))}]")
    setattr(f, "allowed_langs", sorted(langs))
    return f

def by_field_not_equal(field: str, value: Optional[str]):
    f = (field or "").lower().strip()
    if not f or value is None or str(value).strip() == "":
        return _mark(lambda e,fd,r: True, f"field:{f or 'unknown'}", "by_field_not_equal[ignored]")
    v = str(value)
    def _f(etype, fields, raw): return fields.get(f) != v
    return _mark(_f, f"field:{f}", f"by_field_not_equal[{f}!={v}]")

def by_field_equals(field: str, value: Optional[str], case_insensitive: bool = True):
    f = (field or "").lower().strip()
    if not f or value is None or str(value).strip() == "":
        return _mark(lambda e,fd,r: True, f"field:{f or 'unknown'}", "by_field_equals[ignored]")
    if case_insensitive:
        vv = str(value).lower()
        def _f(etype, fields, raw): return fields.get(f, "").lower() == vv
        return _mark(_f, f"field:{f}", f"by_field_equals[{f}=={vv} (ci)]")
    else:
        vv = str(value)
        def _f(etype, fields, raw): return fields.get(f, "") == vv
        return _mark(_f, f"field:{f}", f"by_field_equals[{f}=={vv}]")

def by_field_contains(field: str, needle: Optional[str], case_insensitive: bool=True):
    f = (field or "").lower().strip()
    if not f or needle is None or str(needle).strip() == "":
        return _mark(lambda e,fd,r: True, f"field:{f or 'unknown'}", "by_field_contains[ignored]")
    nd = str(needle)
    def _f(etype, fields, raw):
        v = fields.get(f, "")
        return (nd.lower() in v.lower()) if case_insensitive else (nd in v)
    return _mark(_f, f"field:{f}", f"by_field_contains[{f}~={nd}]")

def by_regex(field: str, pattern: Optional[str], flags: int = 0):
    f = (field or "").lower().strip()
    if not f or pattern is None or str(pattern) == "":
        return _mark(lambda e,fd,r: True, f"regex:{f or 'unknown'}", "by_regex[ignored]")
    rx = re.compile(pattern, flags)
    def _f(etype, fields, raw): return bool(rx.search(fields.get(f, "")))
    return _mark(_f, f"regex:{f}", f"by_regex[{f}/{pattern}/]")

def by_has_field(field: Optional[str]):
    f = (field or "").lower().strip()
    if not f: return _mark(lambda e,fd,r: True, "has:unknown", "by_has_field[ignored]")
    def _f(etype, fields, raw): return bool(fields.get(f))
    return _mark(_f, f"has:{f}", f"by_has_field[{f}]")

def by_searchword_min_len(min_len: Optional[int]):
    if min_len is None or min_len <= 0: return _mark(lambda e,fd,r: True, "searchword", "by_searchword_min_len[ignored]")
    def _f(etype, fields, raw): return len(fields.get('searchword_list', [])) >= int(min_len)
    return _mark(_f, "searchword", f"by_searchword_min_len[{min_len}]")

def by_searchword_has(term: Optional[str]):
    if term is None or str(term).strip() == "": return _mark(lambda e,fd,r: True, "searchword", "by_searchword_has[ignored]")
    t = str(term).strip()
    def _f(etype, fields, raw): return t in fields.get("searchword_list", [])
    return _mark(_f, "searchword", f"by_searchword_has[{t}]")

def by_searchword_in(terms: Optional[Iterable[str]]):
    termset = {str(t).strip() for t in (terms or []) if str(t).strip()}
    if not termset: return _mark(lambda e,fd,r: True, "searchword", "by_searchword_in[ignored]")
    def _f(etype, fields, raw):
        lst = fields.get("searchword_list", [])
        return any(t in lst for t in termset)
    return _mark(_f, "searchword", f"by_searchword_in[{', '.join(sorted(termset))}]")

def by_searchword_all(terms: Optional[Iterable[str]]):
    termset = {str(t).strip() for t in (terms or []) if str(t).strip()}
    if not termset: return _mark(lambda e,fd,r: True, "searchword", "by_searchword_all[ignored]")
    def _f(etype, fields, raw):
        lst = fields.get("searchword_list", [])
        return all(t in lst for t in termset)
    return _mark(_f, "searchword", f"by_searchword_all[{', '.join(sorted(termset))}]")

def by_custom(fn: Callable[[str, Dict[str, str], str], bool]) -> Callable[[str, Dict[str, str], str], bool]:
    """Egendefinert predicate: fn(etype, fields, raw) -> bool."""
    return _mark(fn, "custom", getattr(fn, "__name__", "by_custom"))


# === HOVEDLOGIKK (med rapportering + språk-spesial) ===
def main():
    # Velg inputfil
    try:
        input_file = choose_input_file(INPUT_DIR)
    except Exception as e:
        print(f"[FEIL] {e}")
        sys.exit(1)

    ensure_dir(OUTPUT_DIR)
    ensure_dir(REPORTS_DIR)
    output_file = make_output_path(input_file, OUTPUT_DIR)

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    filters = active_filters()

    kept_entries: List[str] = []
    removed_by_bucket: Dict[str, List[str]] = {}
    report_only_by_bucket: Dict[str, List[str]] = {}  # for "included" (ikke fjernet) meldinger

    # Finn evt. språkfilter-objekt for å logge manglende språk selv om entry beholdes
    language_filter = None
    for flt in filters:
        if getattr(flt, "bucket", "") == "language" and hasattr(flt, "allowed_langs"):
            language_filter = flt
            break

    total = 0

    for raw, etype, key in iter_entries_with_raw(content):
        total += 1
        fields = extract_all_fields(raw)

        keep = True
        failed_bucket = None
        failed_filter = None

        for flt in filters:
            try:
                if not flt(etype, fields, raw):
                    keep = False
                    failed_bucket = getattr(flt, "bucket", "other")
                    failed_filter = flt
                    break
            except Exception:
                keep = False
                failed_bucket = getattr(flt, "bucket", "other")
                failed_filter = flt
                break

        if keep:
            # Språk: hvis language mangler, behold men logg i rapporten
            if language_filter is not None:
                found_lang = fields.get('language', '').strip()
                if found_lang == "":
                    allowed = getattr(language_filter, "allowed_langs", [])
                    comment = f"% INCLUDED (missing language): allowed in {{{', '.join(allowed)}}}; found: <missing>\n"
                    report_only_by_bucket.setdefault("language", []).append(
                        comment + (raw if raw.endswith('\n') else raw + '\n')
                    )

            # Bevar 'type' = entrytype ved behov (etter filtrering)
            raw_out = ensure_type_field_as_class(raw, etype)
            kept_entries.append(raw_out if raw_out.endswith('\n') else (raw_out + '\n'))

        else:
            b = failed_bucket or "other"
            entry_txt = raw

            # Språk – fjernet pga. språk ikke i allowed sett
            if b == "language":
                allowed = getattr(failed_filter, "allowed_langs", [])
                found = fields.get('language', '').strip() or "<missing>"
                comment = f"% REMOVED by language: expected in {{{', '.join(allowed)}}}; found: {found}\n"
                entry_txt = comment + (raw if raw.startswith('@') else raw)

            removed_by_bucket.setdefault(b, []).append(entry_txt if entry_txt.endswith('\n') else (entry_txt + '\n'))

    # Skriv passerte entries (kun entries, uten mellomtekst)
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(kept_entries))

    # Skriv bib-rapporter per bucket (kombiner 'removed' + 'report-only')
    base = os.path.splitext(os.path.basename(input_file))[0]
    def safe_name(s: str) -> str:
        return re.sub(r'[^\w\-\+\.]+', '_', s).strip('_')

    all_buckets = set(removed_by_bucket.keys()) | set(report_only_by_bucket.keys())
    total_removed = sum(len(v) for v in removed_by_bucket.values())

    for bucket in sorted(all_buckets):
        entries = (removed_by_bucket.get(bucket, []) + report_only_by_bucket.get(bucket, []))
        out_path = os.path.join(str(REPORTS_DIR), f"{base}_removed_{safe_name(bucket)}+{len(entries)}.bib")
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(entries))
        print(f"[OK] Report ({bucket}): {len(entries)} -> {out_path}")

    print(f"[OK] Input:  {input_file}")
    print(f"[OK] Output (kept): {output_file}")
    print(f"[SUM] Total: {total} | Kept: {len(kept_entries)} | Removed: {total_removed} | Buckets: {len(all_buckets)}")

if __name__ == "__main__":
    main()
