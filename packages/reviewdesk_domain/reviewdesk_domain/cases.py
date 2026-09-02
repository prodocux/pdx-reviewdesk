from __future__ import annotations

from typing import Any

from reviewdesk_domain.fixture import _doc, _evidence
from reviewdesk_domain.models import DocumentPage


def synthetic_dossier(
    *,
    slug: str,
    product: str,
    manufacturer: str,
    spec_revision: str,
    formula_revision: str,
    ph_min: float,
    ph_max: float,
    coa_ph: float,
    spec_batch: str,
    coa_batch: str,
    spec_product: str | None = None,
    formula_product: str | None = None,
    coa_product: str | None = None,
) -> dict[str, Any]:
    spec_name = spec_product or product
    formula_name = formula_product or product
    coa_name = coa_product or product
    ph_label = f"{ph_min:.1f}-{ph_max:.1f}"
    planted: list[str] = []
    if spec_revision != formula_revision:
        planted.append("formula-version")
    if coa_ph < ph_min or coa_ph > ph_max:
        planted.append("ph-range")
    if len({spec_name, formula_name, coa_name}) > 1:
        planted.append("product-identity")
    if spec_batch != coa_batch:
        planted.append("batch-identity")
    stem = slug.replace("_", "-")
    documents = [
        _doc(
            "product-spec",
            f"{stem}-specification.pdf",
            "product_specification",
            "subject",
            [
                DocumentPage(
                    page=1,
                    title="Product specification",
                    lines=[
                        f"Product: {spec_name}",
                        f"Manufacturer: {manufacturer}",
                        f"Formula revision: {spec_revision}",
                        "Intended use: leave-on cosmetic",
                    ],
                    highlight=f"Formula revision: {spec_revision}",
                ),
                DocumentPage(
                    page=2,
                    title="Finished-product limits",
                    lines=[
                        f"Reference batch: {spec_batch}",
                        f"Acceptable pH: {ph_label}",
                        "Appearance: recorded on certificate",
                        f"Manufacturer: {manufacturer}",
                    ],
                    highlight=f"Acceptable pH: {ph_label}",
                ),
            ],
        ),
        _doc(
            "formula",
            f"{stem}-formula.pdf",
            "ingredient_formula",
            "ref",
            [
                DocumentPage(
                    page=1,
                    title="Approved master formula",
                    lines=[
                        f"{formula_name} — Master Formula",
                        f"Formula revision: {formula_revision}",
                        "Status: approved for manufacture",
                        "Aqua q.s.",
                    ],
                    highlight=f"Formula revision: {formula_revision}",
                ),
                DocumentPage(
                    page=2,
                    title="Composition notes",
                    lines=[
                        "Glycerin 6.00%",
                        f"Prepared by {manufacturer}",
                        "This revision supersedes prior drafts.",
                    ],
                ),
            ],
        ),
        _doc(
            "coa",
            f"{stem}-coa.pdf",
            "certificate_of_analysis",
            "ref",
            [
                DocumentPage(
                    page=1,
                    title="Certificate of analysis",
                    lines=[
                        f"Certificate: {coa_name}",
                        f"Batch {coa_batch}",
                        "Test date: 2026-08-01",
                        f"{manufacturer} QC",
                    ],
                    highlight=f"Batch {coa_batch}",
                ),
                DocumentPage(
                    page=2,
                    title="Observed results",
                    lines=[
                        f"pH result {coa_ph}",
                        "Appearance: as specified",
                        "This certificate records observed batch facts.",
                    ],
                    highlight=f"pH result {coa_ph}",
                ),
            ],
        ),
    ]
    evidence = _evidence(
        [
            ("ev-spec-name", "product-spec", "product_name", "string", spec_name, 0.99, 1, f"Product: {spec_name}"),
            ("ev-spec-mfr", "product-spec", "manufacturer", "string", manufacturer, 0.97, 1, f"Manufacturer: {manufacturer}"),
            ("ev-spec-rev", "product-spec", "formula_revision", "version", spec_revision, 0.98, 1, f"Formula revision: {spec_revision}"),
            ("ev-spec-ph-min", "product-spec", "declared_ph_min", "number", ph_min, 0.97, 2, f"Acceptable pH: {ph_label}"),
            ("ev-spec-ph-max", "product-spec", "declared_ph_max", "number", ph_max, 0.97, 2, f"Acceptable pH: {ph_label}"),
            ("ev-spec-batch", "product-spec", "batch_number", "string", spec_batch, 0.99, 2, f"Reference batch: {spec_batch}"),
            ("ev-formula-name", "formula", "product_name", "string", formula_name, 0.99, 1, f"{formula_name} — Master Formula"),
            ("ev-formula-mfr", "formula", "manufacturer", "string", manufacturer, 0.97, 2, f"Prepared by {manufacturer}"),
            ("ev-formula-rev", "formula", "formula_revision", "version", formula_revision, 0.98, 1, f"Formula revision: {formula_revision}"),
            ("ev-coa-name", "coa", "product_name", "string", coa_name, 0.99, 1, f"Certificate: {coa_name}"),
            ("ev-coa-mfr", "coa", "manufacturer", "string", manufacturer, 0.97, 1, f"{manufacturer} QC"),
            ("ev-coa-batch", "coa", "batch_number", "string", coa_batch, 0.99, 1, f"Batch {coa_batch}"),
            ("ev-coa-ph", "coa", "coa_ph", "number", coa_ph, 0.96, 2, f"pH result {coa_ph}"),
        ]
    )
    return {
        "dossier_id": slug,
        "product_name": product,
        "judge_mode": False,
        "blurb": f"Planted: {', '.join(planted) or 'none'}",
        "planted": planted,
        "documents": documents,
        "evidence": evidence,
    }


EXTRA_BENCHMARK: list[dict[str, Any]] = [
    synthetic_dossier(
        slug="pine-mist-toner-2026",
        product="Pine Mist Toner",
        manufacturer="Northpine Labs",
        spec_revision="2",
        formula_revision="2",
        ph_min=5.0,
        ph_max=6.0,
        coa_ph=5.4,
        spec_batch="PMT-2601-01",
        coa_batch="PMT-2601-01",
    ),
    synthetic_dossier(
        slug="kelp-day-lotion-2026",
        product="Kelp Day Lotion",
        manufacturer="Tideform Co.",
        spec_revision="1",
        formula_revision="4",
        ph_min=4.5,
        ph_max=5.5,
        coa_ph=6.1,
        spec_batch="KDL-2602-08",
        coa_batch="KDL-2602-08",
    ),
    synthetic_dossier(
        slug="quartz-eye-gel-2026",
        product="Quartz Eye Gel",
        manufacturer="Clearstone",
        spec_revision="3",
        formula_revision="2",
        ph_min=5.2,
        ph_max=5.8,
        coa_ph=6.9,
        spec_batch="QEG-2604-03",
        coa_batch="QEG-2604-03",
    ),
    synthetic_dossier(
        slug="ember-lip-balm-2026",
        product="Ember Lip Balm",
        manufacturer="Hearth & Wax",
        spec_revision="1",
        formula_revision="1",
        ph_min=5.0,
        ph_max=7.0,
        coa_ph=5.8,
        spec_batch="ELB-2605-12",
        coa_batch="ELB-2605-12",
        formula_product="Ember Repair Balm",
    ),
    synthetic_dossier(
        slug="frost-hand-cream-2026",
        product="Frost Hand Cream",
        manufacturer="Winterwell",
        spec_revision="2",
        formula_revision="2",
        ph_min=5.0,
        ph_max=6.5,
        coa_ph=6.8,
        spec_batch="FHC-2606-09",
        coa_batch="FHC-2606-99",
    ),
    synthetic_dossier(
        slug="moss-body-oil-2026",
        product="Moss Body Oil",
        manufacturer="Greenwell",
        spec_revision="1",
        formula_revision="3",
        ph_min=4.8,
        ph_max=5.6,
        coa_ph=6.2,
        spec_batch="MBO-2607-02",
        coa_batch="MBO-2607-88",
    ),
    synthetic_dossier(
        slug="slate-cleanser-2026",
        product="Slate Cleanser",
        manufacturer="Basalt Soap Co.",
        spec_revision="2",
        formula_revision="5",
        ph_min=5.5,
        ph_max=6.5,
        coa_ph=7.1,
        spec_batch="SLC-2608-14",
        coa_batch="SLC-2608-14",
        coa_product="Slate Face Wash",
    ),
    synthetic_dossier(
        slug="dune-sunscreen-2026",
        product="Dune Sunscreen",
        manufacturer="Shoreline SPF",
        spec_revision="1",
        formula_revision="2",
        ph_min=6.0,
        ph_max=7.0,
        coa_ph=7.8,
        spec_batch="DSN-2609-04",
        coa_batch="DSN-2609-41",
        formula_product="Dune Mineral Screen",
    ),
]
