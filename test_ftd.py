import sys, os

# ✅ Make sure Python knows where "src" folder is
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from ftd_model import select_ftd_candidates, format_ftd_message

# 🧪 Test run
if __name__ == "__main__":
    candidates = select_ftd_candidates()
    print(format_ftd_message(candidates))
