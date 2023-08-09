INSERT OR REPLACE INTO household (id, country_id, label, api_version, household_json, household_hash)
VALUES (
	-7,
	"uk",
	"Sample dataset - duplicate of UK household #33001 in live database",
	"0.54.0",
	'{
        "benunits": {
            "your immediate family": {
                "BRMA_LHA_rate": {
                    "2023": null
                },
                "CTC_child_element": {
                    "2023": null
                },
                "CTC_disabled_child_element": {
                    "2023": null
                },
                "CTC_family_element": {
                    "2023": null
                },
                "CTC_maximum_rate": {
                    "2023": null
                },
                "CTC_severely_disabled_child_element": {
                    "2023": null
                },
                "ESA_income": {
                    "2023": null
                },
                "ESA_income_eligible": {
                    "2023": null
                },
                "HB_non_dep_deductions": {
                    "2023": null
                },
                "JSA": {
                    "2023": null
                },
                "JSA_income": {
                    "2023": null
                },
                "JSA_income_applicable_amount": {
                    "2023": null
                },
                "JSA_income_applicable_income": {
                    "2023": null
                },
                "JSA_income_eligible": {
                    "2023": null
                },
                "LHA_allowed_bedrooms": {
                    "2023": null
                },
                "LHA_cap": {
                    "2023": null
                },
                "LHA_category": {
                    "2023": null
                },
                "LHA_eligible": {
                    "2023": null
                },
                "UC_LCWRA_element": {
                    "2023": null
                },
                "UC_carer_element": {
                    "2023": null
                },
                "UC_child_element": {
                    "2023": null
                },
                "UC_childcare_element": {
                    "2023": null
                },
                "UC_childcare_work_condition": {
                    "2023": null
                },
                "UC_claimant_type": {
                    "2023": null
                },
                "UC_disability_elements": {
                    "2023": null
                },
                "UC_earned_income": {
                    "2023": null
                },
                "UC_housing_costs_element": {
                    "2023": null
                },
                "UC_income_reduction": {
                    "2023": null
                },
                "UC_maximum_amount": {
                    "2023": null
                },
                "UC_maximum_childcare": {
                    "2023": null
                },
                "UC_non_dep_deductions": {
                    "2023": null
                },
                "UC_standard_allowance": {
                    "2023": null
                },
                "UC_unearned_income": {
                    "2023": null
                },
                "UC_work_allowance": {
                    "2023": null
                },
                "WTC_basic_element": {
                    "2023": null
                },
                "WTC_childcare_element": {
                    "2023": null
                },
                "WTC_couple_element": {
                    "2023": null
                },
                "WTC_disabled_element": {
                    "2023": null
                },
                "WTC_lone_parent_element": {
                    "2023": null
                },
                "WTC_maximum_rate": {
                    "2023": null
                },
                "WTC_severely_disabled_element": {
                    "2023": null
                },
                "WTC_worker_element": {
                    "2023": null
                },
                "additional_minimum_guarantee": {
                    "2023": null
                },
                "baseline_child_benefit_entitlement": {
                    "2023": 0
                },
                "baseline_ctc_entitlement": {
                    "2023": 0
                },
                "baseline_housing_benefit_entitlement": {
                    "2023": 0
                },
                "baseline_income_support_entitlement": {
                    "2023": 0
                },
                "baseline_pension_credit_entitlement": {
                    "2023": 0
                },
                "baseline_universal_credit_entitlement": {
                    "2023": 0
                },
                "baseline_wtc_entitlement": {
                    "2023": 0
                },
                "benefit_cap": {
                    "2023": null
                },
                "benefit_cap_reduction": {
                    "2023": null
                },
                "benefits_premiums": {
                    "2023": null
                },
                "benunit_has_carer": {
                    "2023": null
                },
                "benunit_id": {
                    "2023": 0
                },
                "benunit_is_renting": {
                    "2023": null
                },
                "benunit_rent": {
                    "2023": null
                },
                "benunit_tax": {
                    "2023": null
                },
                "benunit_tenure_type": {
                    "2023": null
                },
                "benunit_weekly_hours": {
                    "2023": null
                },
                "benunit_weight": {
                    "2023": null
                },
                "carer_minimum_guarantee_addition": {
                    "2023": null
                },
                "carer_premium": {
                    "2023": null
                },
                "child_benefit": {
                    "2023": null
                },
                "child_benefit_entitlement": {
                    "2023": null
                },
                "child_benefit_less_tax_charge": {
                    "2023": null
                },
                "child_minimum_guarantee_addition": {
                    "2023": null
                },
                "child_tax_credit": {
                    "2023": null
                },
                "child_tax_credit_pre_minimum": {
                    "2023": null
                },
                "claims_ESA_income": {
                    "2023": null
                },
                "claims_all_entitled_benefits": {
                    "2023": null
                },
                "claims_legacy_benefits": {
                    "2023": null
                },
                "council_tax_benefit": {
                    "2023": null
                },
                "count_children_and_qyp": {
                    "2023": null
                },
                "ctc_child_limit_affected": {
                    "2023": null
                },
                "ctc_entitlement": {
                    "2023": null
                },
                "disability_premium": {
                    "2023": null
                },
                "eldest_adult_age": {
                    "2023": null
                },
                "eldest_child_age": {
                    "2023": null
                },
                "enhanced_disability_premium": {
                    "2023": null
                },
                "families": {
                    "2023": 1
                },
                "family_rent": {
                    "2023": null
                },
                "family_type": {
                    "2023": null
                },
                "guarantee_credit": {
                    "2023": null
                },
                "housing_benefit": {
                    "2023": null
                },
                "housing_benefit_applicable_amount": {
                    "2023": null
                },
                "housing_benefit_applicable_income": {
                    "2023": null
                },
                "housing_benefit_eligible": {
                    "2023": null
                },
                "housing_benefit_entitlement": {
                    "2023": null
                },
                "housing_benefit_pre_benefit_cap": {
                    "2023": null
                },
                "income_support": {
                    "2023": null
                },
                "income_support_applicable_amount": {
                    "2023": null
                },
                "income_support_applicable_income": {
                    "2023": null
                },
                "income_support_eligible": {
                    "2023": null
                },
                "income_support_entitlement": {
                    "2023": null
                },
                "is_CTC_eligible": {
                    "2023": null
                },
                "is_UC_eligible": {
                    "2023": null
                },
                "is_UC_work_allowance_eligible": {
                    "2023": null
                },
                "is_WTC_eligible": {
                    "2023": null
                },
                "is_benefit_cap_exempt": {
                    "2023": null
                },
                "is_couple": {
                    "2023": null
                },
                "is_guarantee_credit_eligible": {
                    "2023": null
                },
                "is_lone_parent": {
                    "2023": null
                },
                "is_married": {
                    "2023": null
                },
                "is_pension_credit_eligible": {
                    "2023": null
                },
                "is_savings_credit_eligible": {
                    "2023": null
                },
                "is_single": {
                    "2023": null
                },
                "is_single_person": {
                    "2023": null
                },
                "legacy_benefits": {
                    "2023": null
                },
                "members": [
                    "you"
                ],
                "minimum_guarantee": {
                    "2023": null
                },
                "num_UC_eligible_children": {
                    "2023": null
                },
                "num_adults": {
                    "2023": null
                },
                "num_carers": {
                    "2023": null
                },
                "num_children": {
                    "2023": null
                },
                "num_disabled_adults": {
                    "2023": null
                },
                "num_disabled_children": {
                    "2023": null
                },
                "num_enhanced_disabled_adults": {
                    "2023": null
                },
                "num_enhanced_disabled_children": {
                    "2023": null
                },
                "num_severely_disabled_adults": {
                    "2023": null
                },
                "num_severely_disabled_children": {
                    "2023": null
                },
                "pension_credit": {
                    "2023": null
                },
                "pension_credit_entitlement": {
                    "2023": null
                },
                "pension_credit_income": {
                    "2023": null
                },
                "relation_type": {
                    "2023": null
                },
                "savings_credit": {
                    "2023": null
                },
                "savings_credit_income": {
                    "2023": null
                },
                "severe_disability_minimum_guarantee_addition": {
                    "2023": null
                },
                "severe_disability_premium": {
                    "2023": null
                },
                "standard_minimum_guarantee": {
                    "2023": null
                },
                "tax_credits": {
                    "2023": null
                },
                "tax_credits_applicable_income": {
                    "2023": null
                },
                "tax_credits_reduction": {
                    "2023": null
                },
                "uc_child_limit_affected": {
                    "2023": null
                },
                "uc_has_entitlement": {
                    "2023": null
                },
                "universal_credit": {
                    "2023": null
                },
                "universal_credit_entitlement": {
                    "2023": null
                },
                "universal_credit_pre_benefit_cap": {
                    "2023": null
                },
                "working_tax_credit": {
                    "2023": null
                },
                "working_tax_credit_pre_minimum": {
                    "2023": null
                },
                "would_claim_CTC": {
                    "2023": null
                },
                "would_claim_ESA_income": {
                    "2023": null
                },
                "would_claim_HB": {
                    "2023": null
                },
                "would_claim_IS": {
                    "2023": null
                },
                "would_claim_JSA": {
                    "2023": null
                },
                "would_claim_UC": {
                    "2023": null
                },
                "would_claim_WTC": {
                    "2023": null
                },
                "would_claim_child_benefit": {
                    "2023": null
                },
                "would_claim_pc": {
                    "2023": null
                },
                "wtc_entitlement": {
                    "2023": null
                },
                "youngest_adult_age": {
                    "2023": null
                },
                "youngest_child_age": {
                    "2023": null
                }
            }
        },
        "households": {
            "your household": {
                "BRMA": {
                    "2023": "MAIDSTONE"
                },
                "LVT": {
                    "2023": null
                },
                "accommodation_type": {
                    "2023": "UNKNOWN"
                },
                "additional_residential_property_purchased": {
                    "2023": null
                },
                "alcohol_and_tobacco_consumption": {
                    "2023": 0
                },
                "baseline_business_rates": {
                    "2023": null
                },
                "baseline_corporate_sdlt": {
                    "2023": null
                },
                "baseline_expected_lbtt": {
                    "2023": 0
                },
                "baseline_expected_ltt": {
                    "2023": 0
                },
                "baseline_expected_sdlt": {
                    "2023": 0
                },
                "baseline_fuel_duty": {
                    "2023": 0
                },
                "baseline_hbai_excluded_income": {
                    "2023": null
                },
                "baseline_vat": {
                    "2023": null
                },
                "business_rates": {
                    "2023": null
                },
                "business_rates_change_incidence": {
                    "2023": null
                },
                "carbon_consumption": {
                    "2023": null
                },
                "carbon_tax": {
                    "2023": null
                },
                "change_in_business_rates": {
                    "2023": null
                },
                "change_in_expected_lbtt": {
                    "2023": null
                },
                "change_in_expected_ltt": {
                    "2023": null
                },
                "change_in_expected_sdlt": {
                    "2023": null
                },
                "change_in_fuel_duty": {
                    "2023": null
                },
                "clothing_and_footwear_consumption": {
                    "2023": 0
                },
                "communication_consumption": {
                    "2023": 0
                },
                "consumption": {
                    "2023": null
                },
                "corporate_land_value": {
                    "2023": null
                },
                "corporate_sdlt": {
                    "2023": null
                },
                "corporate_sdlt_change_incidence": {
                    "2023": null
                },
                "corporate_tax_incidence": {
                    "2023": null
                },
                "corporate_wealth": {
                    "2023": 0
                },
                "cost_of_living_support_payment": {
                    "2023": null
                },
                "council_tax": {
                    "2023": 0
                },
                "council_tax_band": {
                    "2023": "D"
                },
                "council_tax_less_benefit": {
                    "2023": null
                },
                "country": {
                    "2023": null
                },
                "cumulative_non_residential_rent": {
                    "2023": 0
                },
                "cumulative_residential_rent": {
                    "2023": 0
                },
                "deep_poverty_gap": {
                    "2023": null
                },
                "deep_poverty_line": {
                    "2023": null
                },
                "diesel_litres": {
                    "2023": null
                },
                "diesel_price": {
                    "2023": null
                },
                "diesel_spending": {
                    "2023": 0
                },
                "domestic_energy_consumption": {
                    "2023": 0
                },
                "domestic_rates": {
                    "2023": null
                },
                "ebr_council_tax_rebate": {
                    "2023": null
                },
                "ebr_energy_bills_credit": {
                    "2023": null
                },
                "education_consumption": {
                    "2023": 0
                },
                "energy_bills_rebate": {
                    "2023": null
                },
                "epg_subsidy": {
                    "2023": null
                },
                "equiv_hbai_household_net_income": {
                    "2023": null
                },
                "equiv_hbai_household_net_income_ahc": {
                    "2023": null
                },
                "equiv_household_net_income": {
                    "2023": null
                },
                "expected_lbtt": {
                    "2023": null
                },
                "expected_ltt": {
                    "2023": null
                },
                "expected_sdlt": {
                    "2023": null
                },
                "food_and_non_alcoholic_beverages_consumption": {
                    "2023": 0
                },
                "fuel_duty": {
                    "2023": null
                },
                "full_rate_vat_consumption": {
                    "2023": null
                },
                "gross_financial_wealth": {
                    "2023": 0
                },
                "hbai_excluded_income": {
                    "2023": null
                },
                "hbai_excluded_income_change": {
                    "2023": null
                },
                "hbai_household_net_income": {
                    "2023": null
                },
                "hbai_household_net_income_ahc": {
                    "2023": null
                },
                "health_consumption": {
                    "2023": 0
                },
                "household_benefits": {
                    "2023": null
                },
                "household_count_people": {
                    "2023": null
                },
                "household_equivalisation_ahc": {
                    "2023": null
                },
                "household_equivalisation_bhc": {
                    "2023": null
                },
                "household_furnishings_consumption": {
                    "2023": 0
                },
                "household_gross_income": {
                    "2023": null
                },
                "household_id": {
                    "2023": 0
                },
                "household_income_decile": {
                    "2023": null
                },
                "household_land_value": {
                    "2023": null
                },
                "household_market_income": {
                    "2023": null
                },
                "household_net_income": {
                    "2023": null
                },
                "household_num_benunits": {
                    "2023": null
                },
                "household_owns_tv": {
                    "2023": null
                },
                "household_tax": {
                    "2023": null
                },
                "household_weight": {
                    "2023": 0
                },
                "households": {
                    "2023": 1
                },
                "housing_costs": {
                    "2023": null
                },
                "housing_service_charges": {
                    "2023": 0
                },
                "housing_water_and_electricity_consumption": {
                    "2023": 0
                },
                "in_deep_poverty": {
                    "2023": null
                },
                "in_deep_poverty_ahc": {
                    "2023": null
                },
                "in_deep_poverty_bhc": {
                    "2023": null
                },
                "in_original_frs": {
                    "2023": 0
                },
                "in_poverty": {
                    "2023": null
                },
                "in_poverty_ahc": {
                    "2023": null
                },
                "in_poverty_bhc": {
                    "2023": null
                },
                "in_relative_poverty_ahc": {
                    "2023": null
                },
                "is_renting": {
                    "2023": null
                },
                "is_shared_accommodation": {
                    "2023": false
                },
                "land_and_buildings_transaction_tax": {
                    "2023": null
                },
                "land_transaction_tax": {
                    "2023": null
                },
                "land_value": {
                    "2023": null
                },
                "lbtt_liable": {
                    "2023": null
                },
                "lbtt_on_non_residential_property_rent": {
                    "2023": null
                },
                "lbtt_on_non_residential_property_transactions": {
                    "2023": null
                },
                "lbtt_on_rent": {
                    "2023": null
                },
                "lbtt_on_residential_property_rent": {
                    "2023": null
                },
                "lbtt_on_residential_property_transactions": {
                    "2023": null
                },
                "lbtt_on_transactions": {
                    "2023": null
                },
                "local_authority": {
                    "2023": "MAIDSTONE"
                },
                "ltt_liable": {
                    "2023": null
                },
                "ltt_on_non_residential_property_rent": {
                    "2023": null
                },
                "ltt_on_non_residential_property_transactions": {
                    "2023": null
                },
                "ltt_on_rent": {
                    "2023": null
                },
                "ltt_on_residential_property_rent": {
                    "2023": null
                },
                "ltt_on_residential_property_transactions": {
                    "2023": null
                },
                "ltt_on_transactions": {
                    "2023": null
                },
                "main_residence_value": {
                    "2023": 0
                },
                "main_residential_property_purchased": {
                    "2023": null
                },
                "main_residential_property_purchased_is_first_home": {
                    "2023": null
                },
                "members": [
                    "you"
                ],
                "miscellaneous_consumption": {
                    "2023": 0
                },
                "mortgage": {
                    "2023": null
                },
                "mortgage_capital_repayment": {
                    "2023": 0
                },
                "mortgage_interest_repayment": {
                    "2023": 0
                },
                "net_financial_wealth": {
                    "2023": 0
                },
                "non_primary_residence_wealth_tax": {
                    "2023": null
                },
                "non_residential_property_purchased": {
                    "2023": null
                },
                "non_residential_property_value": {
                    "2023": 0
                },
                "non_residential_rent": {
                    "2023": 0
                },
                "num_bedrooms": {
                    "2023": 0
                },
                "ons_tenure_type": {
                    "2023": null
                },
                "original_weight": {
                    "2023": 0
                },
                "other_residential_property_value": {
                    "2023": 0
                },
                "owned_land": {
                    "2023": 0
                },
                "petrol_litres": {
                    "2023": null
                },
                "petrol_price": {
                    "2023": null
                },
                "petrol_spending": {
                    "2023": 0
                },
                "poverty_gap": {
                    "2023": null
                },
                "poverty_gap_ahc": {
                    "2023": null
                },
                "poverty_gap_bhc": {
                    "2023": null
                },
                "poverty_line": {
                    "2023": null
                },
                "poverty_line_ahc": {
                    "2023": null
                },
                "poverty_line_bhc": {
                    "2023": null
                },
                "poverty_threshold_bhc": {
                    "2023": null
                },
                "property_purchased": {
                    "2023": true
                },
                "property_wealth": {
                    "2023": null
                },
                "real_household_net_income": {
                    "2023": null
                },
                "recreation_consumption": {
                    "2023": 0
                },
                "reduced_rate_vat_consumption": {
                    "2023": null
                },
                "region": {
                    "2023": "LONDON"
                },
                "rent": {
                    "2023": 0
                },
                "residential_property_value": {
                    "2023": null
                },
                "restaurants_and_hotels_consumption": {
                    "2023": 0
                },
                "savings": {
                    "2023": 0
                },
                "sdlt_liable": {
                    "2023": null
                },
                "sdlt_on_non_residential_property_rent": {
                    "2023": null
                },
                "sdlt_on_non_residential_property_transactions": {
                    "2023": null
                },
                "sdlt_on_rent": {
                    "2023": null
                },
                "sdlt_on_residential_property_rent": {
                    "2023": null
                },
                "sdlt_on_residential_property_transactions": {
                    "2023": null
                },
                "sdlt_on_transactions": {
                    "2023": null
                },
                "shareholding": {
                    "2023": null
                },
                "spi_imputed": {
                    "2023": 0
                },
                "stamp_duty_land_tax": {
                    "2023": null
                },
                "tenure_type": {
                    "2023": "RENT_PRIVATELY"
                },
                "total_wealth": {
                    "2023": null
                },
                "transport_consumption": {
                    "2023": 0
                },
                "tv_licence": {
                    "2023": null
                },
                "tv_licence_discount": {
                    "2023": null
                },
                "uc_migrated": {
                    "2023": 0
                },
                "vat": {
                    "2023": null
                },
                "vat_change": {
                    "2023": null
                },
                "water_and_sewerage_charges": {
                    "2023": 0
                },
                "wealth_tax": {
                    "2023": null
                },
                "winter_fuel_allowance": {
                    "2023": null
                },
                "would_evade_tv_licence_fee": {
                    "2023": null
                }
            }
        },
        "people": {
            "you": {
                "AA_reported": {
                    "2023": 0
                },
                "AFCS": {
                    "2023": null
                },
                "AFCS_reported": {
                    "2023": 0
                },
                "BSP": {
                    "2023": null
                },
                "BSP_reported": {
                    "2023": 0
                },
                "CB_HITC": {
                    "2023": null
                },
                "DLA_M_reported": {
                    "2023": 0
                },
                "DLA_SC_reported": {
                    "2023": 0
                },
                "ESA_contrib": {
                    "2023": null
                },
                "ESA_contrib_reported": {
                    "2023": 0
                },
                "ESA_income_reported": {
                    "2023": 0
                },
                "HB_individual_non_dep_deduction": {
                    "2023": null
                },
                "IIDB": {
                    "2023": null
                },
                "IIDB_reported": {
                    "2023": 0
                },
                "ISA_interest_income": {
                    "2023": 0
                },
                "JSA_contrib": {
                    "2023": null
                },
                "JSA_contrib_reported": {
                    "2023": 0
                },
                "JSA_income_reported": {
                    "2023": 0
                },
                "NI_class_2": {
                    "2023": null
                },
                "NI_class_4": {
                    "2023": null
                },
                "NI_exempt": {
                    "2023": null
                },
                "PIP_DL_reported": {
                    "2023": 0
                },
                "PIP_M_reported": {
                    "2023": 0
                },
                "SDA_reported": {
                    "2023": 0
                },
                "SMP": {
                    "2023": 0
                },
                "SSP": {
                    "2023": 0
                },
                "UC_MIF_applies": {
                    "2023": null
                },
                "UC_MIF_capped_earned_income": {
                    "2023": null
                },
                "UC_individual_child_element": {
                    "2023": null
                },
                "UC_individual_disabled_child_element": {
                    "2023": null
                },
                "UC_individual_non_dep_deduction": {
                    "2023": null
                },
                "UC_individual_severely_disabled_child_element": {
                    "2023": null
                },
                "UC_minimum_income_floor": {
                    "2023": null
                },
                "UC_non_dep_deduction_exempt": {
                    "2023": null
                },
                "aa_category": {
                    "2023": null
                },
                "access_fund": {
                    "2023": 0
                },
                "add_rate_earned_income": {
                    "2023": null
                },
                "add_rate_earned_income_tax": {
                    "2023": null
                },
                "add_rate_savings_income": {
                    "2023": null
                },
                "adjusted_net_income": {
                    "2023": null
                },
                "adult_ema": {
                    "2023": 0
                },
                "adult_index": {
                    "2023": null
                },
                "age": {
                    "2023": 40
                },
                "age_18_64": {
                    "2023": null
                },
                "age_over_64": {
                    "2023": null
                },
                "age_under_18": {
                    "2023": null
                },
                "allowances": {
                    "2023": null
                },
                "armed_forces_independence_payment": {
                    "2023": 0
                },
                "attendance_allowance": {
                    "2023": null
                },
                "base_net_income": {
                    "2023": 0
                },
                "basic_income": {
                    "2023": null
                },
                "basic_rate_earned_income": {
                    "2023": null
                },
                "basic_rate_earned_income_tax": {
                    "2023": null
                },
                "basic_rate_savings_income": {
                    "2023": null
                },
                "basic_rate_savings_income_pre_starter": {
                    "2023": null
                },
                "benefits": {
                    "2023": null
                },
                "benefits_modelling": {
                    "2023": null
                },
                "benefits_reported": {
                    "2023": null
                },
                "bi_household_phaseout": {
                    "2023": null
                },
                "bi_individual_phaseout": {
                    "2023": null
                },
                "bi_maximum": {
                    "2023": null
                },
                "bi_phaseout": {
                    "2023": null
                },
                "birth_year": {
                    "2023": null
                },
                "blind_persons_allowance": {
                    "2023": 0
                },
                "capital_allowances": {
                    "2023": 0
                },
                "capital_income": {
                    "2023": null
                },
                "capped_mcad": {
                    "2023": null
                },
                "care_hours": {
                    "2023": 0
                },
                "carers_allowance": {
                    "2023": null
                },
                "carers_allowance_reported": {
                    "2023": 0
                },
                "charitable_investment_gifts": {
                    "2023": 0
                },
                "child_benefit_reported": {
                    "2023": 0
                },
                "child_benefit_respective_amount": {
                    "2023": null
                },
                "child_ema": {
                    "2023": 0
                },
                "child_index": {
                    "2023": null
                },
                "child_tax_credit_reported": {
                    "2023": 0
                },
                "childcare_expenses": {
                    "2023": 0
                },
                "cliff_evaluated": {
                    "2023": null
                },
                "cliff_gap": {
                    "2023": null
                },
                "council_tax_benefit_reported": {
                    "2023": 0
                },
                "covenanted_payments": {
                    "2023": 0
                },
                "current_education": {
                    "2023": null
                },
                "deficiency_relief": {
                    "2023": 0
                },
                "dividend_allowance": {
                    "2023": null
                },
                "dividend_income": {
                    "2023": 0
                },
                "dividend_income_tax": {
                    "2023": null
                },
                "dla": {
                    "2023": null
                },
                "dla_m": {
                    "2023": null
                },
                "dla_m_category": {
                    "2023": null
                },
                "dla_sc": {
                    "2023": null
                },
                "dla_sc_category": {
                    "2023": null
                },
                "dla_sc_middle_plus": {
                    "2023": null
                },
                "earned_income": {
                    "2023": null
                },
                "earned_income_tax": {
                    "2023": null
                },
                "earned_taxable_income": {
                    "2023": null
                },
                "education_grants": {
                    "2023": 0
                },
                "employee_NI": {
                    "2023": null
                },
                "employee_NI_class_1": {
                    "2023": null
                },
                "employer_NI": {
                    "2023": null
                },
                "employer_NI_class_1": {
                    "2023": null
                },
                "employer_pension_contributions": {
                    "2023": 0
                },
                "employment_benefits": {
                    "2023": null
                },
                "employment_deductions": {
                    "2023": null
                },
                "employment_expenses": {
                    "2023": 0
                },
                "employment_income": {
                    "2023": 55000
                },
                "employment_status": {
                    "2023": "UNEMPLOYED"
                },
                "family_benefits": {
                    "2023": null
                },
                "family_benefits_reported": {
                    "2023": 0
                },
                "gender": {
                    "2023": "MALE"
                },
                "gift_aid": {
                    "2023": 0
                },
                "gross_income": {
                    "2023": null
                },
                "higher_rate_earned_income": {
                    "2023": null
                },
                "higher_rate_earned_income_tax": {
                    "2023": null
                },
                "higher_rate_savings_income": {
                    "2023": null
                },
                "highest_education": {
                    "2023": "UPPER_SECONDARY"
                },
                "hours_worked": {
                    "2023": 0
                },
                "housing_benefit_reported": {
                    "2023": 0
                },
                "in_FE": {
                    "2023": false
                },
                "in_HE": {
                    "2023": false
                },
                "in_social_housing": {
                    "2023": null
                },
                "in_work": {
                    "2023": null
                },
                "incapacity_benefit": {
                    "2023": null
                },
                "incapacity_benefit_reported": {
                    "2023": 0
                },
                "income_decile": {
                    "2023": null
                },
                "income_support_reported": {
                    "2023": 0
                },
                "income_tax": {
                    "2023": null
                },
                "income_tax_pre_charges": {
                    "2023": null
                },
                "is_CTC_child_limit_exempt": {
                    "2023": null
                },
                "is_QYP": {
                    "2023": null
                },
                "is_SP_age": {
                    "2023": null
                },
                "is_WA_adult": {
                    "2023": null
                },
                "is_adult": {
                    "2023": null
                },
                "is_apprentice": {
                    "2023": false
                },
                "is_benunit_eldest_child": {
                    "2023": null
                },
                "is_benunit_head": {
                    "2023": null
                },
                "is_blind": {
                    "2023": false
                },
                "is_carer_for_benefits": {
                    "2023": null
                },
                "is_child": {
                    "2023": null
                },
                "is_child_born_before_child_limit": {
                    "2023": null
                },
                "is_child_for_CTC": {
                    "2023": null
                },
                "is_child_or_QYP": {
                    "2023": null
                },
                "is_disabled_for_benefits": {
                    "2023": null
                },
                "is_eldest_child": {
                    "2023": null
                },
                "is_enhanced_disabled_for_benefits": {
                    "2023": null
                },
                "is_female": {
                    "2023": null
                },
                "is_higher_earner": {
                    "2023": null
                },
                "is_household_head": {
                    "2023": null
                },
                "is_in_startup_period": {
                    "2023": false
                },
                "is_male": {
                    "2023": null
                },
                "is_older_child": {
                    "2023": null
                },
                "is_on_cliff": {
                    "2023": null
                },
                "is_severely_disabled_for_benefits": {
                    "2023": null
                },
                "is_young_child": {
                    "2023": null
                },
                "limited_capability_for_WRA": {
                    "2023": null
                },
                "loss_relief": {
                    "2023": null
                },
                "lump_sum_income": {
                    "2023": 0
                },
                "maintenance_expenses": {
                    "2023": 0
                },
                "maintenance_income": {
                    "2023": 0
                },
                "marginal_tax_rate": {
                    "2023": null
                },
                "marital_status": {
                    "2023": null
                },
                "market_income": {
                    "2023": null
                },
                "marriage_allowance": {
                    "2023": null
                },
                "married_couples_allowance": {
                    "2023": 0
                },
                "married_couples_allowance_deduction": {
                    "2023": null
                },
                "maternity_allowance": {
                    "2023": null
                },
                "maternity_allowance_reported": {
                    "2023": 0
                },
                "meets_marriage_allowance_income_conditions": {
                    "2023": null
                },
                "minimum_wage": {
                    "2023": null
                },
                "minimum_wage_category": {
                    "2023": null
                },
                "miscellaneous_income": {
                    "2023": 0
                },
                "national_insurance": {
                    "2023": null
                },
                "net_income": {
                    "2023": null
                },
                "occupational_pension_contributions": {
                    "2023": 0
                },
                "other_benefits": {
                    "2023": null
                },
                "other_deductions": {
                    "2023": 0
                },
                "over_16": {
                    "2023": null
                },
                "partners_unused_personal_allowance": {
                    "2023": null
                },
                "pays_scottish_income_tax": {
                    "2023": null
                },
                "pension_annual_allowance": {
                    "2023": null
                },
                "pension_contributions": {
                    "2023": null
                },
                "pension_contributions_relief": {
                    "2023": null
                },
                "pension_credit_reported": {
                    "2023": 0
                },
                "pension_income": {
                    "2023": 0
                },
                "people": {
                    "2023": 1
                },
                "person_benunit_id": {
                    "2023": 0
                },
                "person_benunit_role": {
                    "2023": null
                },
                "person_household_id": {
                    "2023": 0
                },
                "person_household_role": {
                    "2023": null
                },
                "person_id": {
                    "2023": 0
                },
                "person_state_id": {
                    "2023": 0
                },
                "person_state_role": {
                    "2023": null
                },
                "person_weight": {
                    "2023": null
                },
                "personal_allowance": {
                    "2023": null
                },
                "personal_benefits": {
                    "2023": null
                },
                "personal_benefits_reported": {
                    "2023": null
                },
                "personal_rent": {
                    "2023": null
                },
                "pip": {
                    "2023": null
                },
                "pip_dl": {
                    "2023": null
                },
                "pip_dl_category": {
                    "2023": null
                },
                "pip_m": {
                    "2023": null
                },
                "pip_m_category": {
                    "2023": null
                },
                "private_pension_contributions": {
                    "2023": 0
                },
                "private_transfer_income": {
                    "2023": 0
                },
                "property_allowance": {
                    "2023": null
                },
                "property_allowance_deduction": {
                    "2023": null
                },
                "property_income": {
                    "2023": 0
                },
                "raw_person_weight": {
                    "2023": 1
                },
                "receives_carers_allowance": {
                    "2023": null
                },
                "receives_enhanced_pip_dl": {
                    "2023": null
                },
                "receives_highest_dla_sc": {
                    "2023": null
                },
                "role": {
                    "2023": null
                },
                "savings_allowance": {
                    "2023": null
                },
                "savings_income_tax": {
                    "2023": null
                },
                "savings_interest_income": {
                    "2023": 0
                },
                "savings_starter_rate_income": {
                    "2023": null
                },
                "sda": {
                    "2023": null
                },
                "self_employed_NI": {
                    "2023": null
                },
                "self_employment_income": {
                    "2023": 0
                },
                "social_security_income": {
                    "2023": null
                },
                "ssmg": {
                    "2023": null
                },
                "ssmg_reported": {
                    "2023": 0
                },
                "state_pension": {
                    "2023": null
                },
                "state_pension_age": {
                    "2023": null
                },
                "state_pension_reported": {
                    "2023": null
                },
                "student_loans": {
                    "2023": 0
                },
                "student_payments": {
                    "2023": null
                },
                "sublet_income": {
                    "2023": 0
                },
                "tax": {
                    "2023": null
                },
                "tax_band": {
                    "2023": null
                },
                "tax_free_savings_income": {
                    "2023": null
                },
                "tax_modelling": {
                    "2023": null
                },
                "tax_reported": {
                    "2023": 0
                },
                "taxable_dividend_income": {
                    "2023": null
                },
                "taxable_employment_income": {
                    "2023": null
                },
                "taxable_miscellaneous_income": {
                    "2023": null
                },
                "taxable_pension_income": {
                    "2023": null
                },
                "taxable_property_income": {
                    "2023": null
                },
                "taxable_savings_interest_income": {
                    "2023": null
                },
                "taxable_self_employment_income": {
                    "2023": null
                },
                "taxable_social_security_income": {
                    "2023": null
                },
                "taxed_dividend_income": {
                    "2023": null
                },
                "taxed_income": {
                    "2023": null
                },
                "taxed_savings_income": {
                    "2023": null
                },
                "total_NI": {
                    "2023": null
                },
                "total_income": {
                    "2023": null
                },
                "total_pension_income": {
                    "2023": null
                },
                "trading_allowance": {
                    "2023": null
                },
                "trading_allowance_deduction": {
                    "2023": null
                },
                "trading_loss": {
                    "2023": 0
                },
                "triple_lock_uprating": {
                    "2023": null
                },
                "universal_credit_reported": {
                    "2023": 0
                },
                "unused_personal_allowance": {
                    "2023": null
                },
                "weekly_NI_class_2": {
                    "2023": null
                },
                "weekly_childcare_expenses": {
                    "2023": null
                },
                "weekly_hours": {
                    "2023": null
                },
                "winter_fuel_allowance_reported": {
                    "2023": 0
                },
                "working_tax_credit_reported": {
                    "2023": 0
                }
            }
        }
    }',
	"QEUX6UiNwq+ICNX2KhyvAWI5OOp1dxaA4wO1WXvVvZc="
);