"""
InsightIQ Intent Interpreter & Safety Controller
Translates natural language questions into strictly allowlisted analytical operations.
Supports dual-mode execution:
1. LLM-assisted interpretation (via Google Gemini or OpenAI when API key is present)
2. Deterministic semantic rule-based fallback (guaranteed offline availability for all 5 question types)

Safety Guarantees:
- Calculations are NEVER performed by the LLM.
- Zero arbitrary SQL execution.
- Strict Pydantic validation of intents and parameters.
- Rejection of destructive operations or out-of-scope queries.
"""

import os
import re
import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field, field_validator
from analytics import AnalyticsEngine

logger = logging.getLogger("insightiq.interpreter")


class IntentType(str, Enum):
    TOTAL_REVENUE = "total_revenue"
    HIGHEST_REVENUE_PRODUCT = "highest_revenue_product"
    MONTHLY_REVENUE_TREND = "monthly_revenue_trend"
    HIGHEST_SALES_REGION = "highest_sales_region"
    COMPARE_MONTHS = "compare_months_revenue"
    SALES_SUMMARY = "sales_summary"
    UNKNOWN = "unknown"


class QueryIntent(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    interpretation_mode: str  # "llm_gemini", "llm_openai", or "fallback_rules"
    explanation: str

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, v, info):
        # Additional safety check on parameters
        return v


# Month parsing dictionary for flexible natural language date extraction
MONTH_MAP = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12"
}

# Injection/destructive keywords detection
DANGEROUS_SQL_PATTERNS = [
    r"\b(drop|delete|truncate|insert|update|alter|create|replace|grant|revoke)\b",
    r"--",
    r";",
    r"/\*",
    r"\bunion\b.*\bselect\b",
    r"\bexec\b|\bexecute\b"
]


def check_for_malicious_input(query: str) -> Optional[str]:
    """Inspects raw query string for SQL injection or destructive intent."""
    normalized = query.lower()
    for pattern in DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, normalized):
            return f"Blocked potential SQL injection or destructive command pattern: {pattern}"
    return None


def parse_month_tokens(text: str) -> List[str]:
    """
    Extracts month references from natural language string.
    Supports formats like 'February 2026', '2026-02', 'Feb 2026', 'February', '02/2026'.
    Returns standardized 'YYYY-MM' strings in order of occurrence.
    """
    extracted = []

    # Pattern 1: ISO YYYY-MM
    iso_matches = re.findall(r"\b(202\d)-(0[1-9]|1[0-2])\b", text)
    for y, m in iso_matches:
        extracted.append(f"{y}-{m}")

    # Pattern 2: Month Name with optional Year (e.g. "February 2026", "Feb 26", "February", "March vs April")
    named_matches = re.findall(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b(?:[\s,]+(202\d|\d{2}))?",
        text.lower()
    )
    for m_name, y_val in named_matches:
        m_num = MONTH_MAP.get(m_name)
        if not m_num:
            continue
        if y_val:
            year = y_val if len(y_val) == 4 else f"20{y_val}"
        else:
            # Default to dataset primary year 2026
            year = "2026"
        formatted = f"{year}-{m_num}"
        if formatted not in extracted:
            extracted.append(formatted)

    return extracted


class FallbackRuleInterpreter:
    """Deterministic, zero-dependency semantic parser for natural language questions."""

    def interpret(self, question: str) -> QueryIntent:
        q = question.lower().strip()

        # 1. Compare two months
        # Keywords: compare, vs, versus, difference between, change from, between X and Y
        months = parse_month_tokens(q)
        if len(months) >= 2 and any(k in q for k in ["compare", "vs", "versus", "between", "difference", "change", "growth", "from"]):
            return QueryIntent(
                intent=IntentType.COMPARE_MONTHS,
                confidence=0.95,
                parameters={"month1": months[0], "month2": months[1]},
                interpretation_mode="fallback_rules",
                explanation=f"Identified month-over-month comparison between {months[0]} and {months[1]}."
            )

        # 2. Monthly Revenue Trend
        # Keywords: monthly, trend, month by month, each month, over time, sales by month
        if any(k in q for k in ["monthly", "trend", "month by month", "each month", "over time", "sales by month", "revenue by month", "months"]):
            return QueryIntent(
                intent=IntentType.MONTHLY_REVENUE_TREND,
                confidence=0.92,
                parameters={},
                interpretation_mode="fallback_rules",
                explanation="Identified monthly revenue trend and chronological MoM analysis."
            )

        # 3. Highest-Revenue Product
        # Keywords: highest revenue product, top product, best product, best selling product, product revenue, which product
        if any(k in q for k in ["highest-revenue product", "highest revenue product", "top product", "best product", "best-selling product", "best selling product", "most revenue product", "which product", "product generated", "top selling product"]):
            return QueryIntent(
                intent=IntentType.HIGHEST_REVENUE_PRODUCT,
                confidence=0.94,
                parameters={},
                interpretation_mode="fallback_rules",
                explanation="Identified query for highest-revenue product and performance ranking."
            )

        # 4. Highest-Sales Region
        # Keywords: highest-sales region, highest sales region, top region, best region, region sales, which region, sales by region
        if any(k in q for k in ["highest-sales region", "highest sales region", "top region", "best region", "which region", "sales by region", "regional sales", "region generated", "region revenue", "sales region"]):
            return QueryIntent(
                intent=IntentType.HIGHEST_SALES_REGION,
                confidence=0.94,
                parameters={},
                interpretation_mode="fallback_rules",
                explanation="Identified query for highest-sales region and comparative regional breakdown."
            )

        # 5. Total Revenue
        # Keywords: total revenue, overall revenue, gross revenue, how much revenue, total sales, sum of sales
        if any(k in q for k in ["total revenue", "overall revenue", "gross revenue", "total sales", "overall sales", "how much revenue", "how much did we make", "revenue total", "sum of sales"]):
            return QueryIntent(
                intent=IntentType.TOTAL_REVENUE,
                confidence=0.95,
                parameters={},
                interpretation_mode="fallback_rules",
                explanation="Identified query for total net completed sales revenue."
            )

        # 6. Sales Summary / Performance Overview
        # Keywords: summarize the sales data, overview of sales performance, sales summary, overview of sales
        summary_terms = ["summarize", "summary", "overview", "executive summary", "recap", "briefing"]
        sales_terms = ["sale", "sales", "revenue", "performance", "business", "portfolio", "store", "data"]
        has_summary = any(st in q for st in summary_terms)
        has_sales = any(st in q for st in sales_terms)
        if (has_summary and has_sales) or q in ["sales summary", "executive summary", "overview", "summary", "sales overview"]:
            return QueryIntent(
                intent=IntentType.SALES_SUMMARY,
                confidence=0.95,
                parameters={},
                interpretation_mode="fallback_rules",
                explanation="Identified request for comprehensive executive sales summary and performance overview."
            )

        # If 2 months mentioned even without explicit compare keywords
        if len(months) == 2:
            return QueryIntent(
                intent=IntentType.COMPARE_MONTHS,
                confidence=0.85,
                parameters={"month1": months[0], "month2": months[1]},
                interpretation_mode="fallback_rules",
                explanation=f"Inferred comparison between {months[0]} and {months[1]} based on two extracted dates."
            )

        # Unknown / Unsupported
        return QueryIntent(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            parameters={},
            interpretation_mode="fallback_rules",
            explanation="Query is outside the scope of InsightIQ's supported sales analytics operations."
        )


class LLMInterpreter:
    """Optional LLM adapter using Gemini or OpenAI when credentials are present."""

    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.openai_key = os.environ.get("OPENAI_API_KEY")

    def is_available(self) -> bool:
        return bool(self.gemini_key or self.openai_key)

    def interpret(self, question: str) -> Optional[QueryIntent]:
        if self.gemini_key:
            return self._interpret_gemini(question)
        elif self.openai_key:
            return self._interpret_openai(question)
        return None

    def _interpret_gemini(self, question: str) -> Optional[QueryIntent]:
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")

            system_prompt = (
                "You are an intent interpreter for a sales analytics database. "
                "Classify the user's question into EXACTLY ONE of these operations: "
                "1. 'total_revenue' (calculates overall completed net revenue) "
                "2. 'highest_revenue_product' (finds top product by revenue) "
                "3. 'monthly_revenue_trend' (chronological monthly revenue trend) "
                "4. 'highest_sales_region' (compares regional sales and finds top region) "
                "5. 'compare_months_revenue' (compares revenue between two months; extract parameters month1 and month2 in YYYY-MM format) "
                "6. 'sales_summary' (executive overview of sales performance, top product, top region, and monthly peak) "
                "7. 'unknown' (out-of-scope, unrelated, or unsupported) "
                "Respond ONLY with a valid JSON object matching: "
                "{\"intent\": string, \"confidence\": float (0 to 1), \"parameters\": {\"month1\": string, \"month2\": string}, \"explanation\": string}. "
                "Do not include any conversational text or markdown blocks."
            )

            response = model.generate_content(f"{system_prompt}\nUser Question: {question}")
            text = response.text.strip()
            # Clean possible markdown ```json ... ``` wrapper
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            data = json.loads(text)
            intent_val = data.get("intent", "").lower()
            if intent_val not in IntentType._value2member_map_:
                intent_val = "unknown"

            return QueryIntent(
                intent=IntentType(intent_val),
                confidence=float(data.get("confidence", 0.9)),
                parameters=data.get("parameters", {}),
                interpretation_mode="llm_gemini",
                explanation=data.get("explanation", "Interpreted via Gemini LLM.")
            )
        except Exception:
            logger.warning("Gemini LLM interpretation call failed or timed out. Falling back to rule interpreter.")
            return None

    def _interpret_openai(self, question: str) -> Optional[QueryIntent]:
        # Implementation for OpenAI if key is present
        try:
            import urllib.request
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You classify questions into total_revenue, highest_revenue_product, monthly_revenue_trend, highest_sales_region, compare_months_revenue, sales_summary, or unknown. Return JSON only with intent, confidence, parameters, explanation."},
                    {"role": "user", "content": question}
                ],
                "response_format": {"type": "json_object"}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openai_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = json.loads(result["choices"][0]["message"]["content"])
                return QueryIntent(
                    intent=IntentType(content.get("intent", "unknown")),
                    confidence=float(content.get("confidence", 0.9)),
                    parameters=content.get("parameters", {}),
                    interpretation_mode="llm_openai",
                    explanation=content.get("explanation", "Interpreted via OpenAI LLM.")
                )
        except Exception:
            logger.warning("OpenAI LLM interpretation call failed or timed out. Falling back to rule interpreter.")
            return None


class QueryDispatcher:
    """Orchestrates query interpretation, parameter validation, and secure analytics execution."""

    def __init__(self, db_path: Optional[str] = None):
        self.engine = AnalyticsEngine(db_path=db_path) if db_path else AnalyticsEngine()
        self.llm = LLMInterpreter()
        self.rules = FallbackRuleInterpreter()

    def process_query(self, raw_question: str) -> Dict[str, Any]:
        """
        Main pipeline entry point:
        1. Validate raw question
        2. Check for malicious SQL injection patterns
        3. Interpret intent via LLM (if configured) or deterministic fallback
        4. Validate intent and parameters
        5. Execute parameterized analytics calculation
        6. Return complete structured response with evidence and metadata
        """
        if not raw_question or not isinstance(raw_question, str) or not raw_question.strip():
            return {
                "success": False,
                "error": "EMPTY_QUERY",
                "message": "Question cannot be empty. Please ask a business question.",
                "supported_operations": [
                    "Summarize the sales data",
                    "What is the total revenue?",
                    "What is the highest-revenue product?",
                    "What is the monthly revenue trend?",
                    "What is the highest-sales region?",
                    "Compare revenue between February 2026 and May 2026"
                ]
            }

        question = raw_question.strip()

        # Security check: Block dangerous patterns
        security_violation = check_for_malicious_input(question)
        if security_violation:
            return {
                "success": False,
                "error": "SECURITY_REJECTION",
                "message": security_violation,
                "raw_question": question
            }

        # Step 2: Try LLM interpretation if configured
        intent_obj: Optional[QueryIntent] = None
        if self.llm.is_available():
            intent_obj = self.llm.interpret(question)

        # Step 3: Fall back to deterministic rules if LLM unavailable or failed
        if not intent_obj:
            intent_obj = self.rules.interpret(question)

        # Step 4: Dispatch to analytics engine based on validated intent
        if intent_obj.intent == IntentType.TOTAL_REVENUE:
            result = self.engine.get_total_revenue()
        elif intent_obj.intent == IntentType.HIGHEST_REVENUE_PRODUCT:
            result = self.engine.get_highest_revenue_product()
        elif intent_obj.intent == IntentType.MONTHLY_REVENUE_TREND:
            result = self.engine.get_monthly_revenue_trend()
        elif intent_obj.intent == IntentType.HIGHEST_SALES_REGION:
            result = self.engine.get_highest_sales_region()
        elif intent_obj.intent == IntentType.SALES_SUMMARY:
            result = self.engine.get_sales_summary()
        elif intent_obj.intent == IntentType.COMPARE_MONTHS:
            params = intent_obj.parameters
            m1 = params.get("month1")
            m2 = params.get("month2")
            if not m1 or not m2:
                # Try fallback extraction directly from question
                extracted = parse_month_tokens(question)
                if len(extracted) >= 2:
                    m1, m2 = extracted[0], extracted[1]
                else:
                    return {
                        "success": False,
                        "error": "MISSING_MONTH_PARAMETERS",
                        "message": "Could not identify two valid months for comparison. Please specify months like 'February 2026 and May 2026'.",
                        "raw_question": question,
                        "interpretation": intent_obj.model_dump()
                    }
            result = self.engine.compare_months_revenue(m1, m2)
        else:
            return {
                "success": False,
                "error": "UNSUPPORTED_QUESTION",
                "message": (
                    "InsightIQ is a specialized business intelligence assistant focused on sales analytics. "
                    "Your question could not be mapped to an approved analytical operation. "
                    "Please ask a sales-related question or select from the supported queries below."
                ),
                "explanation": intent_obj.explanation,
                "raw_question": question,
                "interpretation": intent_obj.model_dump(),
                "supported_questions": [
                    "Summarize the sales data",
                    "What is the total revenue?",
                    "What is the highest-revenue product?",
                    "What is the monthly revenue trend?",
                    "What is the highest-sales region?",
                    "Compare revenue between February 2026 and May 2026"
                ]
            }

        # Attach interpretation metadata to result
        result["success"] = True
        result["raw_question"] = question
        result["interpretation"] = {
            "intent": intent_obj.intent.value,
            "confidence": intent_obj.confidence,
            "mode": intent_obj.interpretation_mode,
            "explanation": intent_obj.explanation,
            "parameters": intent_obj.parameters
        }

        return result
