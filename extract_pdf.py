from pathlib import Path
import pdfplumber

pdf_path = Path("Finz Data Engineering Challenge.pdf")
out_dir = Path("tmp/pdfs")
out_dir.mkdir(parents=True, exist_ok=True)

with pdfplumber.open(pdf_path) as pdf:
    chunks = []
    print(f"PAGES={len(pdf.pages)}")
    for index, page in enumerate(pdf.pages, start=1):
        text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        chunks.append(f"\n===== PAGE {index} =====\n{text}")
        print(f"PAGE={index} WIDTH={page.width} HEIGHT={page.height} CHARS={len(text)}")
        page.to_image(resolution=140).save(out_dir / f"page-{index}.png", format="PNG")

(out_dir / "extracted.txt").write_text("".join(chunks), encoding="utf-8")
