"""
preprocess.py — Convert raw EDGAR .htm filings into clean .txt files for the pipeline.

Usage:
    python3 preprocess.py

Reads all .htm files from source_docs/, extracts relevant sections,
and writes clean plain-text files to data_room/.

Section extraction rules:
  - HP Product Purchase Agreement: keeps Sections 14–19 (software license,
    IP warranty, indemnification, liability cap) and Exhibit L.
    Skips financial exhibits, ordering/pricing/delivery sections.
  - Dot Hill 10-K / annual report: keeps Item 1 Business, Item 1A Risk Factors,
    and the Intellectual Property subsection.
    Skips financial statements, MD&A tables, quarterly data.
"""

import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Installing beautifulsoup4...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
    from bs4 import BeautifulSoup

SOURCE_DIR = Path(__file__).parent / "source_docs"
OUTPUT_DIR = Path(__file__).parent / "data_room"

# ── Section filters ───────────────────────────────────────────────────────────

# HP agreement: keep sections 14-19 and Exhibit L
HP_KEEP_PATTERNS = [
    r"14\.\s+Marketing and Licenses",
    r"14\.4",
    r"15\.\s+Intellectual Property",
    r"16\.\s+Delaying",
    r"17\.\s+Events of Default",
    r"18\.\s+General Indemnity",
    r"19\.\s+Limitation of Liability",
    r"20\.\s+Termination",
    r"EXHIBIT L",
]

HP_STOP_PATTERNS = [
    r"EXHIBIT [A-K]\b",
    r"EXHIBIT [M-Q]\b",
    r"^\s*1\.\s+Scope of Agreement",
    r"^\s*2\.\s+Ordering",
    r"^\s*3\.\s+Prices",
    r"^\s*4\.\s+Competitive",
    r"^\s*5\.\s+Inspection",
    r"^\s*6\.\s+Engineering",
    r"^\s*7\.\s+Warranties\b",
    r"^\s*8\.\s+Epidemic",
    r"^\s*9\.\s+Safety",
    r"^\s*10\.\s+Product Returns",
    r"^\s*11\.\s+Support",
    r"^\s*12\.\s+Business Recovery",
    r"^\s*13\.\s+Confidential",
]

# 10-K: keep Item 1 Business narrative + Item 1A Risk Factors
TENK_KEEP_PATTERNS = [
    r"Item\s+1[.\s]+Business",
    r"Item\s+1A[.\s]+Risk Factor",
    r"Intellectual Property",
    r"Research and Development",
    r"Our Solutions",
    r"Our Strategy",
    r"Our Products",
    r"Competition",
    r"Industry Background",
]

TENK_STOP_PATTERNS = [
    r"Item\s+[2-9][.\s]",
    r"Item\s+1[0-9][.\s]",
    r"FINANCIAL STATEMENTS",
    r"CONSOLIDATED BALANCE",
    r"CONSOLIDATED STATEMENTS OF OPERATIONS",
    r"CONSOLIDATED STATEMENTS OF CASH",
    r"NOTES TO CONSOLIDATED",
    r"SCHEDULE II",
    r"F-\d+",
    r"Management.s Discussion and Analysis",
    r"Selected Financial Data",
    r"Market for Registrant",
    r"Quantitative and Qualitative",
]


def html_to_text(html_content: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove script, style, and hidden elements
    for tag in soup(["script", "style", "meta", "link", "head"]):
        tag.decompose()

    text = soup.get_text(separator="\n")

    # Normalize whitespace
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    # Collapse runs of blank lines to single blank
    result = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False

    return "\n".join(result)


def detect_filing_type(text: str, filename: str) -> str:
    """Return 'hp_agreement', 'dot_hill_10k', or 'unknown'."""
    fname = filename.lower()
    text_lower = text[:3000].lower()

    if "product purchase agreement" in text_lower and "dot hill" in text_lower:
        return "hp_agreement"
    if "form 10-k" in text_lower and "dot hill" in text_lower:
        return "dot_hill_10k"
    if "10-k" in fname and "hill" in text_lower:
        return "dot_hill_10k"
    if "exv10" in fname or "exhibit 10" in text_lower:
        return "hp_agreement"
    return "unknown"


def extract_hp_agreement(text: str) -> str:
    """Extract IP warranty, software license, liability cap sections."""
    lines = text.splitlines()
    output = []
    capturing = False

    keep_re = [re.compile(p, re.IGNORECASE) for p in HP_KEEP_PATTERNS]
    stop_re = [re.compile(p, re.IGNORECASE) for p in HP_STOP_PATTERNS]

    for line in lines:
        # Check if we should start capturing
        if any(r.search(line) for r in keep_re):
            capturing = True

        # Check stop signals (only if already past the intro)
        if capturing and len(output) > 50:
            if any(r.search(line) for r in stop_re):
                capturing = False
                continue

        if capturing:
            # Skip heavily redacted lines that are pure placeholders
            if re.match(r"^\s*\[\.\.\.\*\*\*\.\.\.\]\s*$", line):
                continue
            # Skip lines that are just table formatting artifacts
            if re.match(r"^[\s\-\*]+$", line):
                continue
            output.append(line)

    # If extraction caught nothing useful, fall back to full text
    # (truncated to avoid overwhelming the pipeline)
    if len(output) < 200:
        print("  [warn] Section extraction found little content — using full text")
        return text[:40000]

    return "\n".join(output)


def extract_dot_hill_10k(text: str) -> str:
    """Extract Item 1 (Business) and Item 1A (Risk Factors), stop before Item 7."""
    lines = text.splitlines()
    MAX_CHARS = 90000

    def norm(s):
        return s.replace("\xa0", " ").strip()

    # Find all occurrences of "Item 1." followed by "Business" nearby
    item1_indices = []
    for i, line in enumerate(lines):
        c = norm(line)
        if re.match(r"Item\s+1[.\s]", c, re.IGNORECASE):
            window = " ".join(norm(l) for l in lines[i:i+15])
            if re.search(r"Business", window, re.IGNORECASE):
                item1_indices.append(i)

    if not item1_indices:
        print("  [warn] Could not locate Item 1 — using first 40,000 chars")
        return text[:MAX_CHARS]

    # Use the last occurrence — the actual content section, not table of contents
    start_idx = item1_indices[-1]
    print(f"  Item 1 (Business) at line {start_idx} (of {len(item1_indices)} matches)")

    # Find stop: Item 7 or financial statements
    stop_idx = len(lines)
    for i, line in enumerate(lines[start_idx + 50:], start=start_idx + 50):
        c = norm(line)
        if re.search(r"^Item\s+7[.\s]", c, re.IGNORECASE):
            stop_idx = i
            break
        if re.search(r"FINANCIAL STATEMENTS|CONSOLIDATED BALANCE|^F-\d+\s*$", c):
            stop_idx = i
            break

    print(f"  Extracting lines {start_idx}–{stop_idx} ({stop_idx - start_idx} lines)")

    output = []
    chars = 0
    prev_blank = False
    for line in lines[start_idx:stop_idx]:
        c = norm(line)
        if not c:
            if not prev_blank:
                output.append("")
            prev_blank = True
            continue
        prev_blank = False
        clean = line.replace("\xa0", " ")
        output.append(clean)
        chars += len(clean)
        if chars >= MAX_CHARS:
            output.append("[... section truncated at 40,000 chars ...]")
            break

    if chars < 500:
        print("  [warn] Very little extracted — using first 40,000 chars")
        return text[:MAX_CHARS]

    return "\n".join(output)


def process_file(htm_path: Path) -> Path | None:
    """Process a single .htm file and write clean .txt to data_room/."""
    print(f"Processing: {htm_path.name}")

    html_content = htm_path.read_text(encoding="utf-8", errors="replace")
    text = html_to_text(html_content)

    filing_type = detect_filing_type(text, htm_path.name)
    print(f"  Detected type: {filing_type}")
    print(f"  Raw text length: {len(text):,} chars")

    if filing_type == "hp_agreement":
        extracted = extract_hp_agreement(text)
        stem = "hp_product_purchase_agreement"
    elif filing_type == "dot_hill_10k":
        extracted = extract_dot_hill_10k(text)
        stem = "dot_hill_10k_2006"
    else:
        print(f"  [warn] Unknown filing type — writing full stripped text")
        extracted = text[:40000]
        stem = htm_path.stem

    out_path = OUTPUT_DIR / f"{stem}.txt"

    # Add a header identifying the source
    header = (
        f"SOURCE DOCUMENT: {htm_path.name}\n"
        f"FILING TYPE: {filing_type}\n"
        f"EXTRACTED SECTIONS: {len(extracted):,} characters\n"
        f"{'=' * 60}\n\n"
    )

    out_path.write_text(header + extracted, encoding="utf-8")
    print(f"  -> Written: {out_path.name} ({len(extracted):,} chars)")
    return out_path


def main():
    htm_files = sorted(SOURCE_DIR.glob("*.htm")) + sorted(SOURCE_DIR.glob("*.html"))

    if not htm_files:
        print(f"No .htm files found in {SOURCE_DIR}")
        print("Save your EDGAR .htm files to source_docs/ and run again.")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Found {len(htm_files)} file(s) to process.\n")

    for htm_path in htm_files:
        try:
            process_file(htm_path)
        except Exception as e:
            print(f"  [ERROR] {htm_path.name}: {e}")

    print(f"\nDone. Processed files are in data_room/")
    print("Run: streamlit run app.py")


if __name__ == "__main__":
    main()
