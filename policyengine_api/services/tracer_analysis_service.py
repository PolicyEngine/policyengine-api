from collections.abc import Callable
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from typing import Generator, Literal
import re
import anthropic
from policyengine_api.services.ai_analysis_service import AIAnalysisService
from werkzeug.exceptions import NotFound
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Household, Policy
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.ai_analyses import AIAnalysisCache
from policyengine_api.runtime_cache.household_traces import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
)


class TracerAnalysisService(AIAnalysisService):
    def __init__(
        self,
        primary_session_factory: sessionmaker[Session] | None = None,
        household_trace_cache: HouseholdTraceCache | None = None,
        analysis_cache: AIAnalysisCache | None = None,
        claude_client_factory: Callable[[], anthropic.Anthropic] | None = None,
    ) -> None:
        context = get_runtime_cache_context()
        super().__init__(
            analysis_cache=analysis_cache
            or AIAnalysisCache(context.client, context.namespace),
            claude_client_factory=claude_client_factory,
        )
        self._primary_session_factory = primary_session_factory
        self._household_trace_cache = household_trace_cache or HouseholdTraceCache(
            context.client,
            context.namespace,
        )

    @property
    def _primary_sessions(self) -> sessionmaker[Session]:
        return self._primary_session_factory or get_v1_session_factory()

    def execute_analysis(
        self,
        country_id: str,
        household_id: str,
        policy_id: str,
        variable: str,
    ) -> tuple[Generator[str, None, None] | str, Literal["static", "streaming"]]:
        """
        Executes tracer analysis for a variable in a household

        Returns a tuple of:
        - The AI analysis as either a streaming output (if new) or a string (if existing in database)
        - The return type (either "streaming" or "static")
        """

        api_version = COUNTRY_PACKAGE_VERSIONS[country_id]

        # Retrieve tracer record from table
        try:
            tracer: list[str] = self.get_tracer(
                country_id,
                household_id,
                policy_id,
                api_version,
            )
        except Exception as e:
            raise e

        # Parse the tracer output for our given variable
        try:
            tracer_segment: list[str] = self._parse_tracer_output(tracer, variable)
        except Exception as e:
            print(f"Error parsing tracer output: {str(e)}")
            raise e

        # Get the appropriate prompt template based on country
        prompt_template = self._get_prompt_template(country_id)

        # Add the parsed tracer output to the prompt
        prompt = prompt_template.format(
            variable=variable, tracer_segment=tracer_segment
        )

        # If a calculated record exists for this prompt, return it as a string
        existing_analysis = self.get_existing_analysis(prompt)
        if existing_analysis is not None:
            return existing_analysis.analysis, "static"

        # Otherwise, pass prompt to Claude, then return streaming function
        try:
            analysis: Generator = self.trigger_ai_analysis(prompt)
            return analysis, "streaming"
        except Exception as e:
            print(
                f"Error generating AI analysis within tracer analysis service: {str(e)}"
            )
            raise e

    def get_tracer(
        self,
        country_id: str,
        household_id: str,
        policy_id: str,
        api_version: str,
    ) -> list:
        try:
            with self._primary_sessions() as session:
                household = session.scalar(
                    select(Household).where(
                        Household.id == int(household_id),
                        Household.country_id == country_id,
                    )
                )
                policy = session.scalar(
                    select(Policy).where(
                        Policy.id == int(policy_id),
                        Policy.country_id == country_id,
                    )
                )
            if household is None or policy is None:
                raise NotFound("No household simulation tracer found")
            cached = self._household_trace_cache.get(
                HouseholdTraceIdentity(
                    country_id=country_id,
                    household_id=household.id,
                    policy_id=policy.id,
                    household_hash=household.household_hash,
                    policy_hash=policy.policy_hash,
                    country_package_version=api_version,
                    policyengine_version=POLICYENGINE_VERSION,
                )
            )
            if cached is None or not cached.tracer_output:
                raise NotFound("No household simulation tracer found")

            return cached.tracer_output

        except Exception as e:
            print(f"Error getting existing tracer analysis: {str(e)}")
            raise e

    def _parse_tracer_output(self, tracer_output, target_variable):
        result = []
        target_indent = None
        capturing = False

        # Input validation
        if not isinstance(target_variable, str) or not isinstance(tracer_output, list):
            return result

        # Create a regex pattern to match the exact variable name
        # This will match the variable name followed by optional whitespace,
        # then optional angle brackets with any content, then optional whitespace
        pattern = rf"^(\s*)({re.escape(target_variable)})(?!\w)\s*(?:<[^>]*>)?\s*"

        for line in tracer_output:
            # Count leading spaces to determine indentation level
            indent = len(line) - len(line.strip())

            # Check if this line matches our target variable
            match = re.match(pattern, line)
            if match and not capturing:
                target_indent = indent
                capturing = True
                result.append(line)
            elif capturing:
                # Stop capturing if we encounter a line with less indentation than the target
                if indent <= target_indent:
                    break
                # Capture dependencies (lines with greater indentation)
                result.append(line)

        return result

    def _get_prompt_template(self, country_id: str) -> str:
        """Get the appropriate prompt template with correct currency symbol based on country."""

        # Determine currency instruction based on country
        currency_instructions = {
            "uk": "The response will be rendered as markdown, so preface £ with \\.",
            "us": "The response will be rendered as markdown, so preface $ with \\.",
            "ca": "The response will be rendered as markdown, so preface $ with \\.",
            "il": "The response will be rendered as markdown, so preface ₪ with \\.",
            "ng": "The response will be rendered as markdown, so preface ₦ with \\.",
        }

        currency_note = currency_instructions.get(
            country_id, "The response will be rendered as markdown."
        )

        return f"""{anthropic.HUMAN_PROMPT} You are an AI assistant explaining policy calculations. 
  The user has run a simulation for the variable '{{variable}}'.
  Here's the tracer output:
  {{tracer_segment}}
      
  Please explain this result in clear, factual terms. Your explanation should:
  1. Briefly describe what {{variable}} is.
  2. Explain the main factors that led to this result.
  3. Mention any key thresholds or rules that affected the calculation.
  4. If relevant, suggest how changes in input might affect this result.
      
  Provide only factual explanations of the policy mechanics. Do not include commentary, opinions, quotes, or phrases like "Certainly!" or "Here's an explanation." {currency_note}"""
