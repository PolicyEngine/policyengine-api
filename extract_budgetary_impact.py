#!/usr/bin/env python3

import json
import argparse
from pathlib import Path


def is_number(value):
    """
    Check if a value is a number (int or float)
    
    Args:
        value: Value to check
        
    Returns:
        bool: True if the value is a number, False otherwise
    """
    return isinstance(value, (int, float))


def calculate_percent_difference(v1_value, v2_value):
    """
    Calculate the absolute percentage difference between two values
    
    Args:
        v1_value: First value
        v2_value: Second value (denominator)
        
    Returns:
        float: Absolute percentage difference, or float('inf') if v2_value is 0
    """
    if v2_value == 0:
        if v1_value == 0:
            return 0.0
        return float('inf')  # Handle division by zero
    return abs((v1_value - v2_value) / v2_value) * 100


def extract_and_sort_budgetary_impact_objects(data_array):
    """
    Extract objects that have a specific message and meet certain criteria for budgetary impact,
    then sort them by the absolute percentage difference
    
    Args:
        data_array (list): Array of objects to process
        
    Returns:
        list: Array of objects that match the criteria, sorted by percentage difference
    """
    matching_objects = []
    same_version_count = 0
    different_version_count = 0
    
    for obj in data_array:
        # Check if the object has the specific message
        if obj.get("message") == "APIv2 job comparison with APIv1 completed":
            # Extract v1_impact and v2_impact values
            v1_impact = obj.get("v1_impact", {})
            v2_impact = obj.get("v2_impact", {})
            
            # Check if both are dictionaries
            if not isinstance(v1_impact, dict) or not isinstance(v2_impact, dict):
                continue
            
            # Get budget dictionaries
            v1_budget = v1_impact.get("budget", {})
            v2_budget = v2_impact.get("budget", {})
            
            # Check if both are dictionaries
            if not isinstance(v1_budget, dict) or not isinstance(v2_budget, dict):
                continue
            
            # Get budgetary_impact values
            v1_budgetary_impact = v1_budget.get("budgetary_impact")
            v2_budgetary_impact = v2_budget.get("budgetary_impact")

            # Track if this object will be included in the output
            will_include = False

            # Case 1: Either value is not a number
            if not is_number(v1_budgetary_impact) or not is_number(v2_budgetary_impact):
                # Assign a sorting key for non-numeric values (highest priority)
                obj_copy = obj.copy()
                
                # Clean up the impact objects - keep only budget keys
                if isinstance(obj_copy.get("v1_impact"), dict):
                    obj_copy["v1_impact"] = {"budget": obj_copy["v1_impact"].get("budget", {})}
                
                if isinstance(obj_copy.get("v2_impact"), dict):
                    obj_copy["v2_impact"] = {"budget": obj_copy["v2_impact"].get("budget", {})}
                
                if isinstance(obj_copy.get("v1_v2_diff"), dict):
                    obj_copy["v1_v2_diff"] = {"budget": obj_copy["v1_v2_diff"].get("budget", {})}
                
                percent_diff = float('inf')
                obj_copy['_percent_diff'] = percent_diff
                obj_copy['percent_difference'] = percent_diff  # Add the percent difference to the output
                matching_objects.append(obj_copy)
                will_include = True
                
            else:
                # Case 2: Calculate percentage difference
                percent_diff = calculate_percent_difference(v1_budgetary_impact, v2_budgetary_impact)
                
                # Check if difference is at least 5%
                # if float(percent_diff) >= 5:
                if float(percent_diff) >= 5:
                    # Create a copy of the object to modify
                    obj_copy = obj.copy()
                    
                    # Clean up the impact objects - keep only budget keys
                    if isinstance(obj_copy.get("v1_impact"), dict):
                        obj_copy["v1_impact"] = {"budget": obj_copy["v1_impact"].get("budget", {})}
                    
                    if isinstance(obj_copy.get("v2_impact"), dict):
                        obj_copy["v2_impact"] = {"budget": obj_copy["v2_impact"].get("budget", {})}
                    
                    if isinstance(obj_copy.get("v1_v2_diff"), dict):
                        obj_copy["v1_v2_diff"] = {"budget": obj_copy["v1_v2_diff"].get("budget", {})}
                    
                    # Store the percentage difference for sorting
                    obj_copy['_percent_diff'] = percent_diff
                    obj_copy['percent_difference'] = percent_diff  # Add the percent difference to the output
                    matching_objects.append(obj_copy)
                    will_include = True
            
            # Only count version differences for objects that will be included
            if will_include:
                # Compare country package versions for included objects
                v1_version = obj.get("v1_country_package_version")
                v2_version = obj.get("v2_country_package_version")
                
                if v1_version == v2_version:
                    same_version_count += 1
                else:
                    different_version_count += 1
    
    # Sort objects by percentage difference (descending order)
    matching_objects.sort(key=lambda x: x['_percent_diff'], reverse=True)
    
    # Remove the temporary sorting key from the objects
    for obj in matching_objects:
        if '_percent_diff' in obj:
            del obj['_percent_diff']
    
    return matching_objects, same_version_count, different_version_count


def save_to_file(matching_objects, output_file_path):
    """
    Save the matching objects to a new file
    
    Args:
        matching_objects (list): Array of objects to save
        output_file_path (str): Path to save the output
    """
    try:
        # Convert the array to a JSON string with pretty formatting
        json_content = json.dumps(matching_objects, indent=2)
        
        # Write to the file
        with open(output_file_path, 'w') as f:
            f.write(json_content)
        
        print(f"Successfully saved {len(matching_objects)} matching objects to {output_file_path}")
    except Exception as e:
        print(f"Error saving to file: {e}")


def process_data(input_file_path, output_file_path):
    """
    Main function to process input data and extract matching objects
    
    Args:
        input_file_path (str): Path to the input JSON file
        output_file_path (str): Path to save the output
        
    Returns:
        list: The matching objects
    """
    try:
        # Read the input file
        with open(input_file_path, 'r') as f:
            raw_data = f.read()
        
        # Parse the JSON data
        data_array = json.loads(raw_data)
        
        # Extract and sort the matching objects
        matching_objects, same_version_count, different_version_count = extract_and_sort_budgetary_impact_objects(data_array)
        
        # Save the results to a file
        save_to_file(matching_objects, output_file_path)
        
        # Log version comparison statistics for the matched objects
        print(f"\nCountry package version comparison for output objects:")
        print(f"  Same versions: {same_version_count}")
        print(f"  Different versions: {different_version_count}")
        
        return matching_objects
    except Exception as e:
        print(f"Error processing data: {e}")
        return []


def main():
    """Command line interface setup"""
    parser = argparse.ArgumentParser(
        description='Extract objects with budgetary impact discrepancies from a JSON file.'
    )
    parser.add_argument(
        '-i', '--input',
        default='input_data.json',
        help='Path to the input JSON file (default: input_data.json)'
    )
    parser.add_argument(
        '-o', '--output',
        default='budgetary_impact_results.json',
        help='Path to save the output (default: budgetary_impact_results.json)'
    )
    
    args = parser.parse_args()
    
    process_data(args.input, args.output)


if __name__ == "__main__":
    main()