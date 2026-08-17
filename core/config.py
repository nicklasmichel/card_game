STARTING_LIFE = 15
COMBAT_DIE_SIDES = 6

AI_DEBUG = 1
AI_DEBUG_TOP_N = 5
AI_DEBUG_BUILD_TOP_N = 5
AI_DEBUG_FLOAT_PRECISION = 2
AI_DEBUG_INCLUDE_WEIGHTS = 1
AI_DEBUG_INCLUDE_FINGERPRINTS = 1

# A complete minimax-style search grows too quickly on full late-game boards.
# Stop before the UI's 30-second tolerance and return the best fully evaluated
# action found so far.
AI_THINKING_TIME_LIMIT_SECONDS = 25.0
