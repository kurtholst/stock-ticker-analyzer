"""Patent search (EPO OPS API) and AI analysis (Gemini 2.5 Flash)."""

import base64
import json
import logging
import os
import re
import time
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PatentResult(BaseModel):
    patent_number: str
    title: str
    applicant: str
    filing_date: str | None = None
    status: str | None = None


class PatentScore(BaseModel):
    patent_number: str
    title: str
    score: str  # "POSITIVE" | "INSIGNIFICANT" | "NEGATIVE"
    reasoning: str


class PatentSearchRequest(BaseModel):
    ticker: str


class PatentAnalyzeRequest(BaseModel):
    ticker: str
    company_name: str
    patents: list[PatentResult]


class PatentSearchResponse(BaseModel):
    ticker: str
    company_name: str
    patents: list[PatentResult]
    total_found: int
    source: str
    error: str | None = None


class PatentAnalyzeResponse(BaseModel):
    ticker: str
    company_name: str
    scores: list[PatentScore]
    summary: str
    model: str


# ---------------------------------------------------------------------------
# Ticker -> company name resolution
# ---------------------------------------------------------------------------

# Manual overrides for tickers where yfinance name is too verbose or wrong
_TICKER_OVERRIDES: dict[str, str] = {
    "AAPL": "Apple",
    "AMZN": "Amazon",
}

# Cache resolved names so yfinance is only called once per ticker
_name_cache: dict[str, str] = {}


def _clean_company_name(raw_name: str) -> str:
    """Strip common suffixes like 'A/S', 'B A/S', 'Inc.', 'SE' for better EPO search."""
    import re
    # Remove trailing stock class indicators and legal suffixes
    cleaned = re.sub(
        r'\s*\b(A/S|B\s+A/S|Inc\.?|Corp\.?|Ltd\.?|SE|AG|plc|NV|SA|GmbH|Co\.?|& Co\.?|Group)\s*$',
        '', raw_name, flags=re.IGNORECASE,
    ).strip()
    # Remove trailing commas or dots
    cleaned = cleaned.rstrip(',. ')
    return cleaned or raw_name


def _company_name_for_ticker(ticker: str) -> str:
    """Resolve ticker to company name for patent search.

    Uses manual overrides first, then yfinance shortName, with caching.
    """
    if ticker in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[ticker]

    if ticker in _name_cache:
        return _name_cache[ticker]

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        raw_name = info.get("shortName") or info.get("longName") or ticker
        name = _clean_company_name(raw_name)
        _name_cache[ticker] = name
        return name
    except Exception:
        logger.warning("Could not resolve company name for %s via yfinance", ticker)
        _name_cache[ticker] = ticker
        return ticker


# ---------------------------------------------------------------------------
# In-memory cache (10-min TTL)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600  # seconds


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _set_cached(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# EPO OPS API - OAuth2 + Patent Search
# ---------------------------------------------------------------------------

_EPO_TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
_EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"

# XML namespaces used by EPO OPS responses
_NS = {
    "ops": "http://ops.epo.org",
    "xlink": "http://www.w3.org/1999/xlink",
    "epo": "http://www.epo.org/exchange",
}


def _get_epo_credentials() -> tuple[str, str] | None:
    """Get EPO OPS Consumer Key + Secret from environment."""
    key = os.environ.get("EPO_OPS_KEY")
    secret = os.environ.get("EPO_OPS_SECRET")
    if key and secret:
        return key, secret
    return None


async def _get_epo_access_token() -> str | None:
    """Get OAuth2 access token from EPO OPS (cached)."""
    cached_token = _get_cached("epo_token")
    if cached_token:
        return cached_token

    creds = _get_epo_credentials()
    if not creds:
        return None

    key, secret = creds
    auth_string = base64.b64encode(f"{key}:{secret}".encode()).decode()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _EPO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth_string}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        # Cache for slightly less than the token lifetime (20 min default)
        _cache["epo_token"] = (time.time(), token)
        return token


def _parse_epo_search_results(xml_bytes: bytes) -> list[PatentResult]:
    """Parse EPO OPS XML search results into PatentResult list."""
    patents: list[PatentResult] = []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        logger.warning("Failed to parse EPO XML response")
        return patents

    # Find all exchange-document elements (each is a patent publication)
    for doc in root.iter("{http://www.epo.org/exchange}exchange-document"):
        patent_number = ""
        title = ""
        applicant = ""
        filing_date = None
        status = doc.attrib.get("kind", "")

        # Build patent number from country + doc-number + kind
        country = doc.attrib.get("country", "")
        doc_number = doc.attrib.get("doc-number", "")
        kind = doc.attrib.get("kind", "")
        if country and doc_number:
            patent_number = f"{country}{doc_number}{kind}"

        # Title - prefer English, fall back to any
        for title_el in doc.iter("{http://www.epo.org/exchange}invention-title"):
            lang = title_el.attrib.get("lang", "")
            text = (title_el.text or "").strip()
            if text:
                if lang == "en" or not title:
                    title = text

        # Applicant(s)
        applicants = []
        for app_el in doc.iter("{http://www.epo.org/exchange}applicant"):
            data_format = app_el.attrib.get("data-format", "")
            if data_format == "epodoc":
                name_el = app_el.find("{http://www.epo.org/exchange}applicant-name/{http://www.epo.org/exchange}name")
                if name_el is not None and name_el.text:
                    applicants.append(name_el.text.strip())
        applicant = "; ".join(applicants) if applicants else ""

        # Filing date
        for app_ref in doc.iter("{http://www.epo.org/exchange}application-reference"):
            date_el = app_ref.find("{http://www.epo.org/exchange}document-id/{http://www.epo.org/exchange}date")
            if date_el is not None and date_el.text:
                raw = date_el.text.strip()
                # Format YYYYMMDD -> YYYY-MM-DD
                if len(raw) == 8:
                    filing_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
                else:
                    filing_date = raw
                break

        if patent_number:
            patents.append(PatentResult(
                patent_number=patent_number,
                title=title or "No title available",
                applicant=applicant,
                filing_date=filing_date,
                status=kind or None,
            ))

    return patents


async def search_epo_patents(company_name: str) -> tuple[list[PatentResult], str | None]:
    """Search EPO OPS API for patents by applicant name.

    Returns (patents, error_message).
    Requires EPO_OPS_KEY and EPO_OPS_SECRET in environment.
    """
    cache_key = f"epo:{company_name.lower()}"
    cached = _get_cached(cache_key)
    if cached is not None:
        logger.info("Returning cached EPO results for %s", company_name)
        return cached, None

    # Check credentials
    if not _get_epo_credentials():
        return [], (
            "EPO OPS credentials not configured. "
            "Register for free at https://developers.epo.org/ and set "
            "EPO_OPS_KEY and EPO_OPS_SECRET in .env"
        )

    try:
        token = await _get_epo_access_token()
        if not token:
            return [], "Failed to obtain EPO OPS access token."

        # CQL query: search by applicant, sorted by publication date
        cql = f'pa="{company_name}"'

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                _EPO_SEARCH_URL,
                params={"q": cql, "Range": "1-25"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/xml",
                },
            )

            if resp.status_code == 404:
                # No results found
                return [], None

            if resp.status_code == 403:
                # Token expired or rate limited, clear cache and retry once
                _cache.pop("epo_token", None)
                token = await _get_epo_access_token()
                if not token:
                    return [], "EPO OPS authentication failed."
                resp = await client.get(
                    _EPO_SEARCH_URL,
                    params={"q": cql, "Range": "1-25"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/xml",
                    },
                )

            if resp.status_code != 200:
                return [], f"EPO OPS returned status {resp.status_code}."

            # Now fetch bibliographic data for the results
            # The search response contains document IDs - we need to fetch biblio
            search_xml = resp.content
            root = ET.fromstring(search_xml)

            # Extract publication references from search results
            pub_refs = []
            for ref in root.iter("{http://ops.epo.org}publication-reference"):
                doc_id = ref.find("{http://www.epo.org/exchange}document-id")
                if doc_id is not None:
                    country = ""
                    doc_num = ""
                    kind = ""
                    for child in doc_id:
                        tag = child.tag.split("}")[-1]
                        if tag == "country":
                            country = (child.text or "").strip()
                        elif tag == "doc-number":
                            doc_num = (child.text or "").strip()
                        elif tag == "kind":
                            kind = (child.text or "").strip()
                    if country and doc_num:
                        pub_refs.append(f"{country}.{doc_num}.{kind}" if kind else f"{country}.{doc_num}")

            if not pub_refs:
                return [], None

            # Fetch bibliographic data for up to 20 patents at a time
            biblio_refs = ",".join(pub_refs[:20])
            biblio_url = (
                f"https://ops.epo.org/3.2/rest-services/"
                f"published-data/publication/epodoc/{biblio_refs}/biblio"
            )
            biblio_resp = await client.get(
                biblio_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/xml",
                },
            )

            if biblio_resp.status_code != 200:
                # Fall back to basic search results without full biblio
                patents = []
                for ref in pub_refs[:25]:
                    parts = ref.split(".")
                    patents.append(PatentResult(
                        patent_number=ref.replace(".", ""),
                        title="(title unavailable)",
                        applicant=company_name,
                        filing_date=None,
                        status=parts[-1] if len(parts) > 2 else None,
                    ))
                _set_cached(cache_key, patents)
                return patents, None

            patents = _parse_epo_search_results(biblio_resp.content)

            # Sort by filing date (newest first)
            patents.sort(key=lambda p: p.filing_date or "", reverse=True)

            _set_cached(cache_key, patents)
            return patents, None

    except httpx.TimeoutException:
        return [], "EPO OPS timed out. Try again in a moment."
    except Exception as e:
        logger.exception("EPO patent search failed")
        return [], f"EPO patent search failed: {str(e)}"


# ---------------------------------------------------------------------------
# Gemini 2.5 Flash AI analysis
# ---------------------------------------------------------------------------

def _get_gemini_api_key() -> str | None:
    """Get Gemini API key from environment."""
    return os.environ.get("GEMINI_API_KEY")


async def analyze_patents_with_gemini(
    patents: list[PatentResult],
    company_name: str,
    ticker: str,
) -> PatentAnalyzeResponse:
    """Send patent list to Gemini 2.5 Flash for investment-relevance scoring."""
    api_key = _get_gemini_api_key()
    if not api_key:
        return PatentAnalyzeResponse(
            ticker=ticker,
            company_name=company_name,
            scores=[],
            summary="Gemini API key not configured. Set GEMINI_API_KEY in .env",
            model="gemini-2.5-flash",
        )

    if not patents:
        return PatentAnalyzeResponse(
            ticker=ticker,
            company_name=company_name,
            scores=[],
            summary="No patents to analyze.",
            model="gemini-2.5-flash",
        )

    # Build the patent list text for the prompt
    patent_text = "\n".join(
        f"- {p.patent_number}: \"{p.title}\" (applicant: {p.applicant}, "
        f"date: {p.filing_date or 'N/A'}, status: {p.status or 'N/A'})"
        for p in patents
    )

    system_prompt = (
        "You are a financial analyst specializing in patent analysis for stock investors. "
        "You evaluate patent applications and assess their potential impact on the company's "
        "stock value and competitive position.\n\n"
        "For each patent, provide:\n"
        "1. A score: POSITIVE (strengthens competitive moat, new revenue potential), "
        "INSIGNIFICANT (routine/incremental, minimal market impact), or "
        "NEGATIVE (defensive filing, potential legal issues, signals weakness)\n"
        "2. A brief reasoning (1-2 sentences) in Danish\n\n"
        "Also provide an overall summary assessment in Danish (2-3 sentences) covering "
        "the patent portfolio's impact on the investment thesis for this company.\n\n"
        "IMPORTANT: Respond in valid JSON format with this structure:\n"
        "{\n"
        '  "scores": [\n'
        '    {"patent_number": "...", "title": "...", "score": "POSITIVE|INSIGNIFICANT|NEGATIVE", "reasoning": "..."}\n'
        "  ],\n"
        '  "summary": "Overall assessment..."\n'
        "}"
    )

    user_prompt = (
        f"Company: {company_name} (ticker: {ticker})\n\n"
        f"Recent patent applications:\n{patent_text}\n\n"
        "Analyze each patent's potential impact on the company's stock value."
    )

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]},
            ],
        )

        # Parse the JSON response
        text = response.text or ""
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text.strip())

        data: dict[str, Any] = json.loads(text)

        scores = [
            PatentScore(
                patent_number=s.get("patent_number", ""),
                title=s.get("title", ""),
                score=s.get("score", "INSIGNIFICANT"),
                reasoning=s.get("reasoning", ""),
            )
            for s in data.get("scores", [])
        ]

        return PatentAnalyzeResponse(
            ticker=ticker,
            company_name=company_name,
            scores=scores,
            summary=data.get("summary", "No summary available."),
            model="gemini-2.5-flash",
        )

    except ImportError:
        return PatentAnalyzeResponse(
            ticker=ticker,
            company_name=company_name,
            scores=[],
            summary="google-genai package not installed. Run: pip install google-genai",
            model="gemini-2.5-flash",
        )
    except Exception as e:
        logger.exception("Gemini analysis failed")
        return PatentAnalyzeResponse(
            ticker=ticker,
            company_name=company_name,
            scores=[],
            summary=f"AI analysis failed: {str(e)}",
            model="gemini-2.5-flash",
        )
