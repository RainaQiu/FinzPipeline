from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.qbo_sync import SyncCandidate, plan_sync


class RecordingRepository:
    def __init__(self):
        self.items = []

    async def add(self, item):
        self.items.append(item)
        return item


def _candidate(kind, amount, *, bank="1000", direction=None, transfer_pair=None):
    transaction = SimpleNamespace(
        id=f"transaction-{kind}-{bank}",
        version=2,
        kind=kind,
        amount=Decimal(amount),
        bank_account=bank,
        direction=direction,
    )
    return SyncCandidate(
        transaction=transaction,
        approved=SimpleNamespace(
            id="decision-2", account="5000", version=2, approval_status="approved"
        ),
        transfer_pair=transfer_pair,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "direction", "expected_kind"),
    [
        ("operating_expense", None, "Purchase"),
        ("fixed_asset", None, "Purchase"),
        ("owner_activity", "outflow", "Purchase"),
        ("owner_activity", "inflow", "Deposit"),
    ],
)
async def test_non_revenue_payloads_use_the_expected_qbo_entity(kind, direction, expected_kind):
    repo = RecordingRepository()

    (item,) = await plan_sync([_candidate(kind, "-7.01", direction=direction)], "realm-1", repo)

    assert item.payload_kind == expected_kind
    assert "7.01" in repr(item.payload)
    with pytest.raises(TypeError):
        item.payload["token"] = "must-not-fit"


@pytest.mark.asyncio
async def test_transfer_pair_is_a_single_bank_to_bank_transfer_with_pair_key():
    repo = RecordingRepository()
    pair = SimpleNamespace(id="pair-8", bank_account="1010")

    (item,) = await plan_sync([_candidate("transfer", "-50.00", transfer_pair=pair)], "realm-1", repo)

    assert item.idempotency_key == "qbo:realm-1:transfer:pair-8"
    assert item.payload_kind == "Transfer"
    assert item.payload == {
        "FromAccountRef": {"value": "1000"},
        "ToAccountRef": {"value": "1010"},
        "Amount": "50.00",
    }


@pytest.mark.asyncio
async def test_explicit_owner_contribution_and_distribution_kinds_are_supported():
    repo = RecordingRepository()

    contribution, distribution = await plan_sync(
        [
            _candidate("owner_contribution", "21.00"),
            _candidate("owner_distribution", "-21.00", bank="1010"),
        ],
        "realm-1",
        repo,
    )

    assert contribution.payload_kind == "Deposit"
    assert distribution.payload_kind == "Purchase"


@pytest.mark.asyncio
@pytest.mark.parametrize("approval_status", ["suggested", "rejected"])
async def test_plan_sync_rejects_decisions_that_are_not_approved(approval_status):
    repo = RecordingRepository()
    candidate = _candidate("revenue", "10.00")
    candidate = SyncCandidate(
        transaction=candidate.transaction,
        approved=SimpleNamespace(account="4000", approval_status=approval_status),
    )

    with pytest.raises(ValueError, match="approved"):
        await plan_sync([candidate], "realm-1", repo)


@pytest.mark.asyncio
async def test_plan_sync_rejects_an_account_outside_the_chart_of_accounts():
    repo = RecordingRepository()
    candidate = _candidate("revenue", "10.00")
    candidate = SyncCandidate(
        transaction=candidate.transaction,
        approved=SimpleNamespace(account="0000", approval_status="approved"),
    )

    with pytest.raises(ValueError):
        await plan_sync([candidate], "realm-1", repo)


@pytest.mark.asyncio
async def test_refund_deposit_keeps_the_negative_exact_dollar_amount():
    repo = RecordingRepository()

    (item,) = await plan_sync([_candidate("refund", "-35.00")], "realm-1", repo)

    assert item.payload_kind == "Deposit"
    assert item.payload["DepositToAccountRef"] == {"value": "1000"}
    assert item.payload["Line"][0]["Amount"] == "-35.00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("amount", "bank"),
    [("50.00", "1000"), ("-50.00", "1010")],
)
async def test_transfer_requires_the_1000_outflow_leg(amount, bank):
    repo = RecordingRepository()
    pair = SimpleNamespace(id="pair-invalid", bank_account="1010")

    with pytest.raises(ValueError, match="outflow"):
        await plan_sync([_candidate("transfer", amount, bank=bank, transfer_pair=pair)], "realm-1", repo)


@pytest.mark.asyncio
async def test_transfer_rejects_a_non_equal_paired_amount():
    repo = RecordingRepository()
    pair = SimpleNamespace(id="pair-unequal", bank_account="1010", amount=Decimal("49.99"))

    with pytest.raises(ValueError, match="equal"):
        await plan_sync([_candidate("transfer", "-50.00", transfer_pair=pair)], "realm-1", repo)
