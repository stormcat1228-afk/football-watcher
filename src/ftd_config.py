# --- Thresholds ---
EV_MIN_HALF = 0.12      # minimum EV for HALF stake
EV_MIN_FULL = 0.20      # minimum EV for FULL stake
MP_MIN_HALF = 0.10      # 10% minimum model probability for HALF stake
MP_MIN_FULL = 0.20      # 20% minimum model probability for FULL stake
EDGE_MIN = 0.01         # 1.0% model edge vs implied probability
PRICE_MIN = 9.0         # +900 minimum (decimal odds)

# --- Confidence labels ---
LABEL_FULL = "FULL STAKE"
LABEL_HALF = "HALF STAKE"

# --- Other settings ---
INCLUDE_BACKUP_IF_CLOSE = True
BACKUP_MP_DIFF_MAX = 0.015  # Show backup if within 1.5% MP of primary
