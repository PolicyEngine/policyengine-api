import numpy as np


def check_for_nans(array: np.ndarray):
    """
    Check for NaNs in the array and log a warning if found
    """
    return True if np.isnan(array).any() else False
