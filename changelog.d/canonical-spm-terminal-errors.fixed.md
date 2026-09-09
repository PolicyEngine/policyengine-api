Persist typed canonical SPM worker failures for annual and budget-window requests,
including invalid segmented results, so later polls replay the same code and
message after API service recreation without contacting a vanished job. Preserve
canonical cache identity and existing cache lifetime and runtime refresh rules.
Preserve Stage 11 immutability for all stored households, including historical
households without saved SPM settings; changed inputs, labels or settings require
a new replacement household. Use a public worker PR documentation link.
