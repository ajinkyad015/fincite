from typing import Optional
from app.schema import (
    Document as DocumentSchema,
    DocumentMetadataKeysEnum,
    NSEDocumentMetadata,
)


def build_title_for_document(document: DocumentSchema) -> str:
    """
    Build a human-readable title for a document.

    Examples:
        "Reliance Industries (RELIANCE) Annual Report FY2025"
        "TCS Financial Results FY2024"
        "Uploaded Document"
    """
    if document.metadata_map is None:
        return _fallback_title(document)

    nse_key = DocumentMetadataKeysEnum.NSE_DOCUMENT
    if nse_key not in document.metadata_map:
        return _fallback_title(document)

    try:
        meta = NSEDocumentMetadata.model_validate(document.metadata_map[nse_key])
    except Exception:
        return _fallback_title(document)

    parts = [meta.company_name]
    if meta.company_symbol:
        parts[0] = f"{meta.company_name} ({meta.company_symbol})"

    doc_type_label = meta.document_type.value.replace("_", " ").title()
    parts.append(doc_type_label)

    if meta.financial_year:
        parts.append(f"FY{meta.financial_year}")

    return " ".join(parts)


def build_description_for_document(document: DocumentSchema) -> str:
    """
    Build a tool description string for an indexed document.

    Examples:
        "Annual report for Reliance Industries (RELIANCE), financial year 2025."
        "Uploaded financial document: reliance-report.pdf"
    """
    if document.metadata_map is None:
        return _fallback_description(document)

    nse_key = DocumentMetadataKeysEnum.NSE_DOCUMENT
    if nse_key not in document.metadata_map:
        return _fallback_description(document)

    try:
        meta = NSEDocumentMetadata.model_validate(document.metadata_map[nse_key])
    except Exception:
        return _fallback_description(document)

    doc_type_label = meta.document_type.value.replace("_", " ")
    company = meta.company_name
    if meta.company_symbol:
        company = f"{meta.company_name} ({meta.company_symbol})"

    desc = f"{doc_type_label.capitalize()} for {company}"
    if meta.financial_year:
        desc += f", financial year {meta.financial_year}"
    if meta.exchange:
        desc += f" (exchange: {meta.exchange})"
    desc += "."
    return desc


def _fallback_title(document: DocumentSchema) -> str:
    """Return a safe fallback title when metadata is missing."""
    if document.metadata_map:
        nse_data = document.metadata_map.get(DocumentMetadataKeysEnum.NSE_DOCUMENT, {})
        filename = nse_data.get("original_filename") if nse_data else None
        if filename:
            return f"Uploaded Document: {filename}"
    return "Uploaded Document"


def _fallback_description(document: DocumentSchema) -> str:
    """Return a safe fallback description when metadata is missing."""
    if document.metadata_map:
        nse_data = document.metadata_map.get(DocumentMetadataKeysEnum.NSE_DOCUMENT, {})
        filename = nse_data.get("original_filename") if nse_data else None
        if filename:
            return f"Uploaded financial document: {filename}"
    return "A financial document that the user pre-selected to discuss with the assistant."
