import pytest
import json
from policyengine_api.data import database
import time


# Test the query method using the db's policy table
class TestAnalysis:
    # Set shared variables
    prompt = "Print the word 'success' with no formatting, parentheses, periods, or any other modifiers"
    expected_output = "success"

    test_request = {"prompt": prompt}

    def test_post_prompt(self, rest_client):
        database.query(
            f"DELETE FROM analysis WHERE prompt = ?",
            (self.prompt,),
        )

        res = rest_client.post("/us/analysis", json=self.test_request)
        return_object = json.loads(res.text)

        assert return_object["status"] == "computing"
        prompt_id = return_object["result"]["prompt_id"]

        is_status_okay = False
        call_counter = 0

        while is_status_okay == False and call_counter < 25:
            call_counter += 1
            res = rest_client.get(f"/us/analysis/{prompt_id}")
            return_object = json.loads(res.text)

            if return_object["status"] == "ok":
                assert (
                    return_object["result"]["analysis"] == self.expected_output
                )
                is_status_okay = True

            time.sleep(1)

        database.query(
            f"DELETE FROM analysis WHERE prompt = ?",
            (self.prompt,),
        )
