from oguk.calibrate import Calibration
from ogcore.parameters import Specifications
from policyengine_core.reforms import Reform
from policyengine_core.periods import instant
from distributed import Client
import multiprocessing
import time
from ogcore import SS
import json


def get_steady_state(reform):
    client = Client()
    num_workers = min(multiprocessing.cpu_count(), 7)
    p = Specifications(
        baseline=True,
        num_workers=num_workers,
    )
    p.update_specifications(
        json.load(
            open(
                "/Users/nikhil/policyengine/OG-UK/oguk/oguk_default_parameters.json",
            )
        )
    )
    p.update_specifications(
        {
            "tax_func_type": "linear",
            "age_specific": False,
            "start_year": 2022,
        }
    )
    c = Calibration(
        p, estimate_tax_functions=True, client=client, iit_reform=reform
    )
    d = c.get_dict()
    updated_params = {
        "etr_params": d["etr_params"],
        "mtrx_params": d["mtrx_params"],
        "mtry_params": d["mtry_params"],
        "mean_income_data": d["mean_income_data"],
        "frac_tax_payroll": d["frac_tax_payroll"],
    }
    p.update_specifications(updated_params)
    steady_state = SS.run_SS(p, client=client)
    return steady_state
