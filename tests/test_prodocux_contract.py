from __future__ import annotations

from reviewdesk_adapter_prodocux import LocalProDocuXVerifier
from reviewdesk_domain.fixture import demo_documents, demo_evidence
from reviewdesk_domain.policy import compile_pif_checks


def test_published_prodocux_flags_revision_and_ph(tmp_path) -> None:
    documents = [item.model_dump(mode="json") for item in demo_documents()]
    request = compile_pif_checks(demo_evidence(), documents, "contract-test")
    result = LocalProDocuXVerifier().verify(request)
    failed = {item["check_id"] for item in result["results"] if item["status"] == "fail"}
    passed = {item["check_id"] for item in result["results"] if item["status"] == "pass"}
    assert result["schema_version"] == "prodocux_evidence_bundle_result_v1"
    assert failed == {"formula-version", "ph-range"}
    assert "product-identity" in passed
    assert "batch-identity" in passed
    assert "required-manufacturer" in passed
