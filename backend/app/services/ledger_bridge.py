"""Application orchestration for the API-facing ledger workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Mapping
from uuid import uuid4

from app.domain.classification import (
    ApprovalStatus,
    ClassificationDecision,
    DecisionSource,
    TransactionType,
)
from app.domain.demo import (
    PipelineContext,
    ReconciliationRunRecord,
    SyncRunRecord,
    UploadRecord,
)
from app.repositories.protocols import (
    AuditEvent,
    InvalidStateTransitionError,
    TransactionContextConflictError,
    UnitOfWork,
)
from app.services.classification import (
    AccountingInvariantError,
    ClassificationContext,
    classify_transaction,
    validate_accounting_decision,
)
from app.services.deduplication import deduplicate
from app.services.ingestion import MAX_FILE_BYTES, IngestionMapping, ingest_rows
from app.services.pnl import build_pnl
from app.services.qbo_sync import SyncCandidate, plan_sync
from app.services.reconciliation import parse_qbo_pnl, reconcile
from app.services.transfers import match_transfers


SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


class LedgerBridgeError(Exception):
    """A safe application error intended for transport translation."""

    code = "ledger_bridge_error"
    status_code = 400
    retryable = False

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ResourceNotFoundError(LedgerBridgeError):
    code = "not_found"
    status_code = 404


class InvalidStateError(LedgerBridgeError):
    code = "invalid_state"
    status_code = 409


class InvalidUploadError(LedgerBridgeError):
    code = "invalid_upload"
    status_code = 422


class InvalidReconciliationError(LedgerBridgeError):
    code = "invalid_reconciliation"
    status_code = 422


class LedgerBridgeService:
    """Coordinate domain services and repositories without transport concerns."""

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    async def create_upload(
        self, *, filename: str, media_type: str, data: bytes
    ) -> dict[str, object]:
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        if normalized_media_type not in SUPPORTED_MEDIA_TYPES:
            raise InvalidUploadError(
                "Only CSV and XLSX uploads are supported.",
                details={"media_type": normalized_media_type},
            )
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        expected_suffixes = (
            {".csv"}
            if normalized_media_type in {"text/csv", "application/csv"}
            else {".xlsx"}
        )
        if suffix not in expected_suffixes:
            raise InvalidUploadError(
                "The filename extension does not match the media type.",
                details={"media_type": normalized_media_type},
            )
        if not data:
            raise InvalidUploadError("The uploaded file is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise InvalidUploadError(
                "The uploaded file exceeds the size limit.",
                details={"max_bytes": MAX_FILE_BYTES},
            )
        upload_id = uuid4().hex
        upload = UploadRecord(
            id=upload_id,
            original_filename=filename,
            media_type=normalized_media_type,
            data=bytes(data),
            sha256=sha256(data).hexdigest(),
            created_at=datetime.now(timezone.utc),
        )
        async with self.unit_of_work as uow:
            await uow.uploads.add(upload)
            await self._append_audit_best_effort(
                uow,
                AuditEvent(
                    "upload.created",
                    {"upload_id": upload_id, "sha256": upload.sha256},
                    datetime.now(timezone.utc),
                )
            )
        return self._upload_view(upload)

    async def get_upload(self, upload_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            upload = await self._require_upload(uow, upload_id)
            context = await uow.pipeline_contexts.get(upload_id)
        published_context = (
            context
            if upload.status == "completed"
            and context is not None
            and context.status == "completed"
            else None
        )
        return self._upload_view(upload, published_context)

    async def process_upload(
        self, upload_id: str, mapping: IngestionMapping
    ) -> dict[str, object]:
        async with self.unit_of_work as uow:
            upload = await self._require_upload(uow, upload_id)
            if upload.status == "completed":
                raise InvalidStateError("The upload has already been processed.")
            processing_upload = replace(
                upload,
                status="processing",
                completed_at=None,
                error_summary=(),
            )
            try:
                await uow.uploads.transition_status(
                    processing_upload,
                    expected_status=upload.status,
                )
            except InvalidStateTransitionError as error:
                raise InvalidStateError(
                    "The upload is already being processed or has completed."
                ) from error
        upload = processing_upload
        try:
            batch = ingest_rows(upload.data, upload.original_filename, mapping)
            normalized = tuple(
                result.transaction
                for result in batch.normalization_results
                if result.transaction is not None
            )
            deduplication = deduplicate(normalized)
            transfers = match_transfers(deduplication.canonical_transactions)
            transactions_by_id = {
                transaction.id: transaction
                for transaction in deduplication.canonical_transactions
            }
            transaction_statuses = {
                transaction.id: {
                    "duplicate_status": deduplication.status_by_id[
                        transaction.id
                    ].value
                }
                for transaction in deduplication.canonical_transactions
            }
            transfer_pairs = {
                pair.id: {
                    "id": pair.id,
                    "transaction_ids": list(pair.transaction_ids),
                    "outflow_transaction_id": pair.outflow_transaction_id,
                    "inflow_transaction_id": pair.inflow_transaction_id,
                    "paired_transaction": self._sync_transaction_view(
                        transactions_by_id[pair.inflow_transaction_id]
                    ),
                }
                for pair in transfers.pairs
            }
            transfer_ids = frozenset(
                transaction_id
                for pair in transfers.pairs
                for transaction_id in pair.transaction_ids
            )
            unmatched_transfer_ids = frozenset(
                transaction_id
                for group in transfers.needs_review
                for transaction_id in group
            ) | frozenset(
                transaction.id
                for transaction in deduplication.canonical_transactions
                if transaction.id not in transfer_ids
                and "TRANSFER" in transaction.description_normalized
            )
            decisions = tuple(
                classify_transaction(
                    transaction,
                    ClassificationContext(
                        matched_transfer_ids=transfer_ids,
                        unmatched_transfer_ids=unmatched_transfer_ids,
                        possible_duplicate_ids=frozenset(
                            item.id for item in deduplication.possible_duplicates
                        ),
                    ),
                )
                for transaction in deduplication.canonical_transactions
            )
            counts = {
                "raw": len(batch.raw_records),
                "unique": len(deduplication.canonical_transactions),
                "duplicates": len(deduplication.duplicate_to_canonical),
                "transfer_pairs": len(transfers.pairs),
                "classified": len(decisions),
            }
            completed_at = datetime.now(timezone.utc)
            context = PipelineContext(
                id=upload.id,
                upload_id=upload.id,
                status="completed",
                transaction_statuses=transaction_statuses,
                transfer_pairs=transfer_pairs,
                counts=counts,
                created_at=upload.created_at,
                updated_at=completed_at,
            )
            completed_upload = replace(
                upload,
                status="completed",
                mapping_version=1,
                row_count=len(batch.raw_records),
                completed_at=completed_at,
            )
            async with self.unit_of_work as uow:
                for raw_record in batch.raw_records:
                    await uow.raw_records.add(raw_record)
                for transaction in deduplication.canonical_transactions:
                    await uow.transactions.add(transaction)
                for decision in decisions:
                    await uow.classifications.append(decision)
                await uow.pipeline_contexts.upsert(context)
                await uow.uploads.transition_status(
                    completed_upload,
                    expected_status="processing",
                )
                await self._append_audit_best_effort(
                    uow,
                    AuditEvent(
                        "upload.processed",
                        {"upload_id": upload.id, "counts": counts},
                        datetime.now(timezone.utc),
                    ),
                )
            return {"id": upload.id, "status": completed_upload.status, "counts": counts}
        except Exception as error:
            async with self.unit_of_work as uow:
                try:
                    await uow.uploads.transition_status(
                        replace(
                            upload,
                            status="failed",
                            completed_at=datetime.now(timezone.utc),
                            error_summary=(type(error).__name__,),
                        ),
                        expected_status="processing",
                    )
                except InvalidStateTransitionError:
                    pass
            if isinstance(error, TransactionContextConflictError):
                raise InvalidStateError(
                    "One or more transactions already belong to another upload."
                ) from error
            if isinstance(error, InvalidStateTransitionError):
                raise InvalidStateError(
                    "The upload state changed before processing could publish."
                ) from error
            raise

    async def list_transactions(
        self,
        *,
        month: str | None = None,
        approval: str | None = None,
        account: str | None = None,
        duplicate: str | None = None,
        risk: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, object]:
        async with self.unit_of_work as uow:
            transactions = await uow.transactions.list()
            enriched = []
            for transaction in transactions:
                context = await self._published_context(uow, transaction.id)
                if context is None:
                    continue
                decision = await uow.classifications.latest(transaction.id)
                if month and transaction.transaction_date.strftime("%Y-%m") != month:
                    continue
                if decision is None:
                    continue
                if approval and decision.approval_status.value != approval:
                    continue
                if account and decision.account_number != account:
                    continue
                duplicate_status = self._duplicate_status(context, transaction.id)
                if duplicate and duplicate_status != duplicate:
                    continue
                item_risk = "high" if decision.needs_review else "low"
                if risk and item_risk != risk:
                    continue
                if search:
                    needle = search.casefold()
                    if needle not in transaction.description_original.casefold() and needle not in transaction.bank_transaction_id.casefold():
                        continue
                enriched.append(
                    self._transaction_view(
                        transaction,
                        decision,
                        duplicate_status=duplicate_status,
                        risk=item_risk,
                    )
                )
        enriched.sort(key=lambda item: (item["transaction_date"], item["id"]))
        return {
            "items": enriched[offset : offset + limit],
            "total": len(enriched),
            "offset": offset,
            "limit": limit,
        }

    async def get_transaction(self, transaction_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            transaction = await uow.transactions.get(transaction_id)
            context = await self._published_context(uow, transaction_id)
            if transaction is None or context is None:
                raise ResourceNotFoundError("Transaction not found.")
            decision = await uow.classifications.latest(transaction_id)
        return self._transaction_view(
            transaction,
            decision,
            duplicate_status=self._duplicate_status(context, transaction_id),
            risk="high" if decision is not None and decision.needs_review else "low",
        )

    async def get_lineage(self, transaction_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            transaction = await uow.transactions.get(transaction_id)
            context = await self._published_context(uow, transaction_id)
            if transaction is None or context is None:
                raise ResourceNotFoundError("Transaction not found.")
            raw = await uow.raw_records.get(transaction.raw_record_id)
            history = await uow.classifications.history(transaction_id)
        return {
            "transaction_id": transaction_id,
            "raw_record": self._raw_view(raw) if raw is not None else None,
            "classification_history": [
                self._decision_view(decision) for decision in history
            ],
            "transfer_pair_id": self._transfer_pair_id(context, transaction_id),
        }

    async def approve_transaction(self, transaction_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            transaction = await uow.transactions.get(transaction_id)
            context = await self._published_context(uow, transaction_id)
            decision = await uow.classifications.latest(transaction_id)
            if transaction is None or context is None or decision is None:
                raise ResourceNotFoundError("Transaction not found.")
            if decision.approval_status is ApprovalStatus.APPROVED:
                raise InvalidStateError("The classification is already approved.")
            approved = await uow.classifications.append(
                replace(
                    decision,
                    id=uuid4().hex,
                    source=DecisionSource.HUMAN,
                    approval_status=ApprovalStatus.APPROVED,
                    needs_review=False,
                    reviewed_at=datetime.now(timezone.utc),
                    created_at=datetime.now(timezone.utc),
                )
            )
            await self._append_audit_best_effort(
                uow,
                AuditEvent(
                    "classification.approved",
                    {
                        "transaction_id": transaction_id,
                        "decision_id": approved.id,
                        "version": approved.version,
                    },
                    datetime.now(timezone.utc),
                )
            )
        return self._decision_view(approved)

    async def correct_transaction(
        self,
        transaction_id: str,
        *,
        account_number: str,
        transaction_type: TransactionType,
        explanation: str,
    ) -> dict[str, object]:
        async with self.unit_of_work as uow:
            transaction = await uow.transactions.get(transaction_id)
            context = await self._published_context(uow, transaction_id)
            current = await uow.classifications.latest(transaction_id)
            if transaction is None or context is None or current is None:
                raise ResourceNotFoundError("Transaction not found.")
            try:
                validate_accounting_decision(
                    transaction,
                    account_number,
                    transaction_type,
                )
            except AccountingInvariantError as error:
                raise InvalidUploadError(str(error)) from error
            corrected = ClassificationDecision(
                id=uuid4().hex,
                transaction_id=transaction_id,
                account_number=account_number,
                transaction_type=transaction_type,
                source=DecisionSource.HUMAN,
                confidence_basis_points=10000,
                approval_status=ApprovalStatus.APPROVED,
                needs_review=False,
                explanation=explanation,
                created_at=datetime.now(timezone.utc),
                reviewed_at=datetime.now(timezone.utc),
            )
            saved = await uow.classifications.append(corrected)
            await self._append_audit_best_effort(
                uow,
                AuditEvent(
                    "classification.corrected",
                    {
                        "transaction_id": transaction_id,
                        "decision_id": saved.id,
                        "version": saved.version,
                        "account_number": saved.account_number,
                        "transaction_type": saved.transaction_type.value,
                    },
                    datetime.now(timezone.utc),
                )
            )
        return self._decision_view(saved)

    async def bulk_approve(self, transaction_ids: list[str]) -> dict[str, object]:
        approved = []
        for transaction_id in transaction_ids:
            approved.append(await self.approve_transaction(transaction_id))
        return {"items": approved, "approved": len(approved)}

    async def pnl(self, start_date: date, end_date: date) -> dict[str, object]:
        if start_date > end_date:
            raise InvalidUploadError("start_date must not be after end_date.")
        report = await self._build_pnl_domain(start_date, end_date)
        return self._pnl_view(report)

    async def pnl_account_transactions(
        self, account_number: str, start_date: date, end_date: date
    ) -> dict[str, object]:
        report = await self.pnl(start_date, end_date)
        transaction_ids = []
        for section in ("revenue_lines", "cogs_lines", "operating_expense_lines"):
            for line in report[section]:
                if line["account_number"] == account_number:
                    transaction_ids.extend(line["transaction_ids"])
        items = [await self.get_transaction(transaction_id) for transaction_id in transaction_ids]
        return {"account_number": account_number, "items": items, "total": len(items)}

    async def plan_qbo_sync(
        self, *, realm_id: str, transaction_ids: list[str] | None
    ) -> dict[str, object]:
        async with self.unit_of_work as uow:
            explicitly_selected = transaction_ids is not None
            if transaction_ids is None:
                transactions = await uow.transactions.list()
            else:
                selected = []
                for transaction_id in transaction_ids:
                    transaction = await uow.transactions.get(transaction_id)
                    if transaction is None:
                        raise ResourceNotFoundError("Transaction not found.")
                    selected.append(transaction)
                transactions = tuple(selected)
            candidates = []
            for transaction in transactions:
                context = await self._published_context(uow, transaction.id)
                if context is None:
                    if explicitly_selected:
                        raise ResourceNotFoundError("Transaction not found.")
                    continue
                decision = await uow.classifications.latest(transaction.id)
                if decision is None or decision.approval_status is not ApprovalStatus.APPROVED:
                    continue
                if decision.transaction_type is TransactionType.TRANSFER:
                    transfer_context = self._transfer_sync_context(
                        context, transaction.id
                    )
                    if transfer_context is None:
                        continue
                    candidates.append(
                        SyncCandidate(
                            transaction=transaction,
                            approved=decision,
                            transfer_pair=transfer_context,
                        )
                    )
                    continue
                candidates.append(SyncCandidate(transaction=transaction, approved=decision))
            items = await plan_sync(tuple(candidates), realm_id, uow)
            run_id = uuid4().hex
            run = {
                "id": run_id,
                "status": "planned",
                "planned_items": len(items),
                "item_ids": [item.id for item in items],
                "execution_authorized": False,
            }
            record = SyncRunRecord(
                id=run_id,
                status="planned",
                item_views={"view": run},
                started_at=datetime.now(timezone.utc),
            )
            await uow.sync_runs.add(record)
            await self._append_audit_best_effort(
                uow,
                AuditEvent(
                    "qbo.sync_planned",
                    {"run_id": run_id, "planned_items": len(items)},
                    datetime.now(timezone.utc),
                )
            )
        return run

    async def get_sync_run(self, run_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            record = await uow.sync_runs.get(run_id)
        if record is None:
            raise ResourceNotFoundError("Sync run not found.")
        return self._mutable_view(record.item_views["view"])

    async def reconcile_local(
        self,
        *,
        start_date: date,
        end_date: date,
        qbo_report: Mapping[str, object],
    ) -> dict[str, object]:
        internal_view = await self.pnl(start_date, end_date)
        internal_report = await self._build_pnl_domain(start_date, end_date)
        try:
            qbo = parse_qbo_pnl(
                qbo_report,
                expected_start_date=start_date,
                expected_end_date=end_date,
                require_cash=True,
            )
        except (TypeError, ValueError) as error:
            raise InvalidReconciliationError(str(error)) from error
        result = reconcile(internal_report, qbo)
        run_id = uuid4().hex
        view = {
            "id": run_id,
            "status": result.status.value,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "lines": [
                {
                    "account_number": line.account_number,
                    "internal_minor": line.internal_minor,
                    "qbo_minor": line.qbo_minor,
                    "difference_minor": line.difference_minor,
                    "status": line.status.value,
                    "diagnostic_candidates": list(line.diagnostic_candidates),
                }
                for line in result.lines
            ],
            "internal_totals": internal_view["totals"],
        }
        async with self.unit_of_work as uow:
            await uow.reconciliation_runs.add(
                ReconciliationRunRecord(
                    id=run_id,
                    status=result.status.value,
                    account_views={"view": view},
                    created_at=datetime.now(timezone.utc),
                )
            )
            await self._append_audit_best_effort(
                uow,
                AuditEvent(
                    "reconciliation.completed",
                    {
                        "run_id": run_id,
                        "status": result.status.value,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                    datetime.now(timezone.utc),
                ),
            )
        return view

    async def get_reconciliation(self, run_id: str) -> dict[str, object]:
        async with self.unit_of_work as uow:
            record = await uow.reconciliation_runs.get(run_id)
        if record is None:
            raise ResourceNotFoundError("Reconciliation not found.")
        return self._mutable_view(record.account_views["view"])

    async def _build_pnl_domain(self, start_date: date, end_date: date):
        async with self.unit_of_work as uow:
            stored_transactions = await uow.transactions.list(
                start_date=start_date, end_date=end_date
            )
            published = []
            for transaction in stored_transactions:
                if await self._published_context(uow, transaction.id) is not None:
                    published.append(transaction)
            transactions = tuple(published)
            decisions = {
                transaction.id: await uow.classifications.latest(transaction.id)
                for transaction in transactions
            }
        return build_pnl(
            transactions,
            {
                transaction_id: decision
                for transaction_id, decision in decisions.items()
                if decision is not None
            },
            start_date,
            end_date,
        )

    @staticmethod
    async def _require_upload(uow: UnitOfWork, upload_id: str) -> UploadRecord:
        upload = await uow.uploads.get(upload_id)
        if upload is None:
            raise ResourceNotFoundError("Upload not found.")
        return upload

    @staticmethod
    async def _published_context(
        uow: UnitOfWork, transaction_id: str
    ) -> PipelineContext | None:
        context = await uow.pipeline_contexts.get_for_transaction(transaction_id)
        if context is None or context.status != "completed":
            return None
        upload = await uow.uploads.get(context.upload_id)
        if upload is None or upload.status != "completed":
            return None
        return context

    @staticmethod
    async def _append_audit_best_effort(
        uow: UnitOfWork, event: AuditEvent
    ) -> None:
        try:
            await uow.audit.append(event)
        except Exception:
            return None

    @staticmethod
    def _duplicate_status(
        context: PipelineContext | None, transaction_id: str
    ) -> str:
        if context is None:
            return "unique"
        status = context.transaction_statuses.get(transaction_id)
        if not isinstance(status, Mapping):
            return "unique"
        return str(status.get("duplicate_status", "unique"))

    @staticmethod
    def _transfer_pair(
        context: PipelineContext | None, transaction_id: str
    ) -> Mapping[str, object] | None:
        if context is None:
            return None
        for pair in context.transfer_pairs.values():
            if (
                isinstance(pair, Mapping)
                and transaction_id in pair.get("transaction_ids", ())
            ):
                return pair
        return None

    @classmethod
    def _transfer_pair_id(
        cls, context: PipelineContext | None, transaction_id: str
    ) -> str | None:
        pair = cls._transfer_pair(context, transaction_id)
        return str(pair["id"]) if pair is not None else None

    @classmethod
    def _transfer_sync_context(
        cls, context: PipelineContext | None, transaction_id: str
    ) -> Mapping[str, object] | None:
        pair = cls._transfer_pair(context, transaction_id)
        if pair is None or pair.get("outflow_transaction_id") != transaction_id:
            return None
        return pair

    @staticmethod
    def _sync_transaction_view(transaction) -> dict[str, object]:
        return {
            "id": transaction.id,
            "amount_minor": transaction.amount_minor,
            "bank_account_number": transaction.bank_account_number,
        }

    @classmethod
    def _mutable_view(cls, value):
        if isinstance(value, Mapping):
            return {key: cls._mutable_view(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [cls._mutable_view(item) for item in value]
        return value

    @staticmethod
    def _decision_view(decision: ClassificationDecision) -> dict[str, object]:
        return {
            "id": decision.id,
            "transaction_id": decision.transaction_id,
            "account_number": decision.account_number,
            "transaction_type": decision.transaction_type.value,
            "source": decision.source.value,
            "confidence_basis_points": decision.confidence_basis_points,
            "approval_status": decision.approval_status.value,
            "needs_review": decision.needs_review,
            "explanation": decision.explanation,
            "version": decision.version,
            "created_at": decision.created_at.isoformat(),
            "reviewed_at": (
                decision.reviewed_at.isoformat()
                if decision.reviewed_at is not None
                else None
            ),
        }

    @classmethod
    def _transaction_view(
        cls, transaction, decision, *, duplicate_status: str, risk: str
    ) -> dict[str, object]:
        return {
            "id": transaction.id,
            "raw_record_id": transaction.raw_record_id,
            "bank_transaction_id": transaction.bank_transaction_id,
            "transaction_date": transaction.transaction_date.isoformat(),
            "posted_date": transaction.posted_date.isoformat(),
            "description": transaction.description_original,
            "description_normalized": transaction.description_normalized,
            "amount_minor": transaction.amount_minor,
            "currency": transaction.currency,
            "direction": transaction.direction.value,
            "bank_account_number": transaction.bank_account_number,
            "duplicate_status": duplicate_status,
            "risk": risk,
            "classification": (
                cls._decision_view(decision) if decision is not None else None
            ),
        }

    @staticmethod
    def _raw_view(raw) -> dict[str, object]:
        return {
            "id": raw.id,
            "source_filename": raw.source_filename,
            "source_file_sha256": raw.source_file_sha256,
            "source_sheet": raw.source_sheet,
            "source_row_number": raw.source_row_number,
            "raw_values": dict(raw.raw_values),
            "raw_row_sha256": raw.raw_row_sha256,
            "ingested_at": raw.ingested_at.isoformat(),
        }

    @staticmethod
    def _pnl_view(report) -> dict[str, object]:
        def lines(values) -> list[dict[str, object]]:
            return [
                {
                    "account_number": line.account_number,
                    "account_name": line.account_name,
                    "total_minor": line.total_minor,
                    "transaction_count": line.transaction_count,
                    "transaction_ids": list(line.transaction_ids),
                }
                for line in values
            ]

        return {
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "revenue_lines": lines(report.revenue_lines),
            "cogs_lines": lines(report.cogs_lines),
            "operating_expense_lines": lines(report.operating_expense_lines),
            "account_totals": dict(report.account_totals),
            "totals": {
                "revenue_minor": report.total_revenue_minor,
                "cogs_minor": report.total_cogs_minor,
                "gross_profit_minor": report.gross_profit_minor,
                "operating_expenses_minor": report.total_operating_expenses_minor,
                "net_profit_minor": report.net_profit_minor,
            },
        }

    @staticmethod
    def _upload_view(
        upload: UploadRecord, context: PipelineContext | None = None
    ) -> dict[str, object]:
        view: dict[str, object] = {
            "id": upload.id,
            "filename": upload.original_filename,
            "media_type": upload.media_type,
            "sha256": upload.sha256,
            "size_bytes": len(upload.data),
            "status": upload.status,
            "created_at": upload.created_at.isoformat(),
        }
        if context is not None and context.counts:
            view["counts"] = dict(context.counts)
        return view
