from app.services.discovery import _extraction_profile


def test_extraction_profiles_cover_noise_and_derived_indexing() -> None:
    assert _extraction_profile("/Notes/node_modules/pkg/index.js", content_type="text/javascript", size=128) == ("skip", "skipped_noise")
    assert _extraction_profile("/Notes/Areas/Budget/van-insurance.xlsx", content_type="application/vnd.ms-excel", size=4096) == (
        "spreadsheet",
        "deferred",
    )
    assert _extraction_profile("/Notes/Archive/2026-taxes.zip", content_type="application/zip", size=4096) == ("archive", "indexed_metadata")
    assert _extraction_profile("/Notes/Inbox/scan.png", content_type="image/png", size=4096) == ("image", "deferred")
    assert _extraction_profile("/Notes/Inbox/sermon-plan.md", content_type="text/markdown", size=4096) == ("text", "indexed")
    assert _extraction_profile("/Notes/Inbox/huge-discharge-summary.pdf", content_type="application/pdf", size=5 * 1024 * 1024) == (
        "text",
        "deferred",
    )
