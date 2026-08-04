from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "stats" / "data"
GAME_RESULTS_PATH = DATA_DIR / "game_results.csv"
CREATURE_RESULTS_PATH = DATA_DIR / "creature_combat_results.csv"
LOG_PATH = DATA_DIR / "log.txt"
