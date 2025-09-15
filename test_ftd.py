import sys, os
# Make Python see the ./src folder so we can import ftd_model
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from ftd_model import select_ftd_candidates, format_ftd_message

if __name__ == "__main__":
    cands = select_ftd_candidates()
    print(format_ftd_message(cands))
