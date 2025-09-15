import sys, os
# Make Python see the ./src folder
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from ftd_model import select_ftd_candidates, format_ftd_message

if __name__ == "__main__":
    candidates = select_ftd_candidates()
    print(format_ftd_message(candidates))

