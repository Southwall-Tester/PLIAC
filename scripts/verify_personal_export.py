"""Generate synthetic PDF fixtures and page images for manual visual review."""
import asyncio
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_personal_export import sample_material
from pliac.personal_export import render_pdf


async def main():
    output = ROOT / "outputs" / "verification" / "personal-export"
    output.mkdir(parents=True, exist_ok=True)
    material = sample_material()
    # Multiple pages exercise table continuation and the saved-source footer.
    material["proposal"]["blocks"][0]["text"] += "\n\n| 检查项 | 说明 |\n|---|---|\n" + "\n".join(
        f"| {index} | 核对原始记录、公式、来源与换页，不据此认定教学效果。 |" for index in range(1, 31))
    pdf = await render_pdf("material", material)
    (output / "synthetic-material.pdf").write_bytes(pdf)
    with fitz.open(stream=pdf, filetype="pdf") as document:
        for index, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(str(output / f"page-{index}.png"))
        print({"pages": len(document), "fonts": sorted({font[3] for page in document for font in page.get_fonts()}), "output": str(output)})


if __name__ == "__main__":
    asyncio.run(main())
