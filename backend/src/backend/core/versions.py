"""Algorithm version constants (blueprint §37).

Every stored algorithm output carries its version; bumping a constant marks
all existing rows of that algorithm as outdated.
"""

ANALYSIS_VERSION = "2.0.0"
FINGERPRINT_VERSION = "1"
NORMALIZER_VERSION = "1"
SCORING_VERSION = "1"