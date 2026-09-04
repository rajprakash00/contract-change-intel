"""Unit tests for clause-level alignment + pure diff (W4·C).

Pure logic per PLAN's engineering policy: no database, no LLM, no parsing —
detect_changes takes two canonical parsed texts and returns Changes whose
spans index into exactly those strings. The `diff` golden task grades the
same logic against the CUAD fixture style.
"""

from app.services.diffing import ChangeKind, detect_changes


def spans(text: str, excerpt: str) -> tuple[int, int]:
    start = text.index(excerpt)
    return (start, start + len(excerpt))


def changes_by_ref(changes, ref: str | None):
    return [c for c in changes if c.clause_ref == ref]


class TestDetectChanges:
    def test_identical_texts_produce_no_changes(self) -> None:
        text = "1. Definitions\n\nThe Agreement means this contract."

        assert detect_changes(text, text) == []

    def test_renumbered_clause_aligns_instead_of_removed_plus_added(self) -> None:
        # "8.02" and "8.2" are the same clause: normalization aligns them, so
        # a renumbering surfaces as one modified change — never removed+added.
        base = "8.02 Indemnification\n\nSupplier shall indemnify Buyer."
        amended = "8.2 Indemnification\n\nSupplier shall indemnify Buyer."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.modified
        assert changes[0].clause_ref == "8.2"

    def test_child_clause_number_does_not_collide_with_parent(self) -> None:
        # (8, 2) and (8, 2, 1) are different keys: an inserted 8.2.1 must
        # surface as an addition, never silently merge into 8.2.
        base = "8.2 Liability cap\n\nLiability is capped at the fees paid."
        amended = (
            "8.2 Liability cap\n\nLiability is capped at the fees paid.\n\n"
            "8.2.1 Carve-outs\n\nThe cap does not apply to willful misconduct."
        )

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        change = changes[0]
        assert change.kind is ChangeKind.added
        assert change.clause_ref == "8.2.1"
        assert change.base_span is None
        assert change.amended_span is not None
        assert amended[change.amended_span.char_start : change.amended_span.char_end] == (
            "8.2.1 Carve-outs\n\nThe cap does not apply to willful misconduct."
        )

    def test_reworded_clause_is_modified_with_spans_into_both_texts(self) -> None:
        base = "2.1 Delivery\n\nLICENSOR shall deliver within 14 days."
        amended = "2.1 Delivery\n\nLICENSOR shall deliver within 30 days."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        change = changes[0]
        assert change.kind is ChangeKind.modified
        assert change.clause_ref == "2.1"
        assert change.base_span is not None
        assert change.amended_span is not None
        assert base[change.base_span.char_start : change.base_span.char_end] == (
            "2.1 Delivery\n\nLICENSOR shall deliver within 14 days."
        )
        assert amended[change.amended_span.char_start : change.amended_span.char_end] == (
            "2.1 Delivery\n\nLICENSOR shall deliver within 30 days."
        )

    def test_clause_present_only_in_base_is_removed(self) -> None:
        base = "2.1 Delivery\n\nShip promptly.\n\n2.2 Penalties\n\nPay late fees."
        amended = "2.1 Delivery\n\nShip promptly."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        change = changes[0]
        assert change.kind is ChangeKind.removed
        assert change.clause_ref == "2.2"
        assert change.base_span is not None
        assert base[change.base_span.char_start : change.base_span.char_end] == (
            "2.2 Penalties\n\nPay late fees."
        )
        assert change.amended_span is None

    def test_clause_present_only_in_amendment_is_added(self) -> None:
        base = "2.1 Delivery\n\nShip promptly."
        amended = "2.1 Delivery\n\nShip promptly.\n\n2.2 Penalties\n\nPay late fees."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.added
        assert changes[0].clause_ref == "2.2"
        assert changes[0].base_span is None

    def test_unnumbered_preamble_change_is_a_modified_change_without_clause_ref(self) -> None:
        base = "This Agreement is between A and B.\n\n1. Definitions\n\nAs set out herein."
        amended = "This Agreement is between A and C.\n\n1. Definitions\n\nAs set out herein."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        change = changes[0]
        assert change.kind is ChangeKind.modified
        assert change.clause_ref is None
        assert change.base_span is not None
        assert change.amended_span is not None
        assert base[change.base_span.char_start : change.base_span.char_end] == (
            "This Agreement is between A and B."
        )
        assert amended[change.amended_span.char_start : change.amended_span.char_end] == (
            "This Agreement is between A and C."
        )

    def test_unnumbered_continuation_paragraphs_extend_the_previous_clause(self) -> None:
        # A clause body flowing over several paragraphs is one section, not a
        # change per paragraph.
        base = "2.1 Delivery\n\nLICENSOR shall deliver Content\n\nto plan_b within 14 days."
        amended = "2.1 Delivery\n\nLICENSOR shall deliver Content\n\nto plan_b within 30 days."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.modified
        assert changes[0].clause_ref == "2.1"

    def test_top_level_number_with_caps_title_starts_a_section(self) -> None:
        # "3 OBLIGATIONS OF PLAN_B" (CUAD style) is a clause boundary; body
        # prose like "30 days after delivery" is not.
        base = "2.1 Duty\n\nDeliver.\n\n3 OBLIGATIONS OF PLAN_B\n\nplan_b will distribute."
        amended = (
            "2.1 Duty\n\nDeliver promptly.\n\n3 OBLIGATIONS OF PLAN_B\n\nplan_b will distribute."
        )

        changes = detect_changes(base, amended)

        assert changes_by_ref(changes, "2.1")[0].kind is ChangeKind.modified
        assert changes_by_ref(changes, "3") == []

    def test_changes_are_ordered_by_base_position_then_additions(self) -> None:
        base = "1. A\n\nText a.\n\n2. B\n\nText b.\n\n3. C\n\nText c."
        amended = "1. A\n\nText a changed.\n\n2. B\n\nText b.\n\n4. D\n\nText d."

        changes = detect_changes(base, amended)

        assert [(c.clause_ref, c.kind) for c in changes] == [
            ("1", ChangeKind.modified),
            ("3", ChangeKind.removed),
            ("4", ChangeKind.added),
        ]

    def test_empty_amended_text_reports_every_base_clause_removed(self) -> None:
        base = "1. A\n\nText a.\n\n2. B\n\nText b."

        changes = detect_changes(base, "")

        assert [c.kind for c in changes] == [ChangeKind.removed, ChangeKind.removed]
        assert [c.clause_ref for c in changes] == ["1", "2"]

    def test_empty_base_text_reports_every_amended_clause_added(self) -> None:
        amended = "1. A\n\nText a."

        changes = detect_changes("", amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.added
        assert changes[0].amended_span is not None
        assert amended[changes[0].amended_span.char_start : changes[0].amended_span.char_end] == (
            "1. A\n\nText a."
        )

    def test_identical_empty_texts_produce_no_changes(self) -> None:
        assert detect_changes("", "") == []

    def test_bare_number_before_lowercase_prose_is_not_a_clause_boundary(self) -> None:
        # "14 days after the signing…" begins a body paragraph, not a clause.
        base = "2.1 Delivery\n\nDeliver within\n\n14 days after the signing."
        amended = "2.1 Delivery\n\nDeliver within\n\n21 days after the signing."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].clause_ref == "2.1"

    def test_all_caps_line_starts_a_heading_keyed_section(self) -> None:
        base = "1. Term\n\nTwo years.\n\nWARRANTIES\n\nNo warranties given."
        amended = "1. Term\n\nTwo years.\n\nWARRANTIES\n\nAll warranties disclaimed."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.modified
        assert changes[0].clause_ref == "warranties"

    def test_named_prefix_clause_refs_normalize(self) -> None:
        base = "Section 8.02 Liability\n\nCapped."
        amended = "Section 8.2 Liability\n\nCapped."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.modified
        assert changes[0].clause_ref == "8.2"

    def test_duplicate_clause_keys_match_in_order(self) -> None:
        base = "1. Annex\n\nAlpha.\n\n1. Annex\n\nBeta."
        amended = "1. Annex\n\nAlpha.\n\n1. Annex\n\nBeta changed."

        changes = detect_changes(base, amended)

        assert len(changes) == 1
        assert changes[0].kind is ChangeKind.modified
        assert changes[0].amended_span is not None
        span = changes[0].amended_span
        assert amended[span.char_start : span.char_end].endswith("Beta changed.")
