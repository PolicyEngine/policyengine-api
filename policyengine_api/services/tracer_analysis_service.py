from policyengine_api.data import local_database
import json
from policyengine_api.country import COUNTRY_PACKAGE_VERSIONS
from typing import Generator
import re
import anthropic
from policyengine_api.services.ai_analysis_service import AIAnalysisService


class TracerAnalysisService(AIAnalysisService):
    def __init__(self):
        super().__init__()

    def execute_analysis(
        self,
        country_id: str,
        household_id: str,
        policy_id: str,
        variable: str,
    ):

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
            tracer_segment: list[str] = self._parse_tracer_output(
                tracer, variable
            )
        except Exception as e:
            print(f"Error parsing tracer output: {str(e)}")
            raise e

        # Add the parsed tracer output to the prompt
        prompt = self.prompt_template.format(
            variable=variable, tracer_segment=tracer_segment
        )

        # If a calculated record exists for this prompt, return it as a
        # streaming response
        existing_analysis: Generator = self.get_existing_analysis(prompt)
        if existing_analysis is not None:
            return existing_analysis

        # Otherwise, pass prompt to Claude, then return streaming function
        try:
            analysis: Generator = self.trigger_ai_analysis(prompt)
            return analysis
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
            # Retrieve from the tracers table in the local database
            row = local_database.query(
                """
            SELECT * FROM tracers 
            WHERE household_id = ? AND policy_id = ? AND country_id = ? AND api_version = ?
            """,
                (household_id, policy_id, country_id, api_version),
            ).fetchone()

            if row is None:
                raise KeyError("No tracer found for this household")

            tracer_output_list = json.loads(row["tracer_output"])
            return tracer_output_list

        except Exception as e:
            print(f"Error getting existing tracer analysis: {str(e)}")
            raise e

    def _parse_tracer_output(self, tracer_output, target_variable):
        result = []
        target_indent = None
        capturing = False

        # Create a regex pattern to match the exact variable name
        # This will match the variable name followed by optional whitespace,
        # then optional angle brackets with any content, then optional whitespace
        pattern = rf"^(\s*)({re.escape(target_variable)})\s*(?:<[^>]*>)?\s*"

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

    prompt_template = f"""{anthropic.HUMAN_PROMPT} You are an AI assistant explaining US policy calculations. 
  The user has run a simulation for the variable '{{variable}}'.
  Here's the tracer output:
  {{tracer_segment}}
      
  Please explain this result in simple terms. Your explanation should:
  1. Briefly describe what {{variable}} is.
  2. Explain the main factors that led to this result.
  3. Mention any key thresholds or rules that affected the calculation.
  4. If relevant, suggest how changes in input might affect this result.
      
  Keep your explanation concise but informative, suitable for a general audience. Do not start with phrases like "Certainly!" or "Here's an explanation. It will be rendered as markdown, so preface $ with \.
  
  {anthropic.AI_PROMPT}"""
