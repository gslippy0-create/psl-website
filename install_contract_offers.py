
from pathlib import Path
import shutil
import py_compile

APP = Path("app.py")
if not APP.exists():
    raise SystemExit("app.py not found. Put this patch in the same folder as app.py.")

src = APP.read_text(encoding="utf-8")
backup = Path("app_before_contract_offers.py")
if not backup.exists():
    shutil.copy2(APP, backup)

if "import contract_offers" in src:
    print("contract_offers.py is already imported.")
else:
    marker = '\nif __name__ == "__main__":'
    if marker in src:
        src = src.replace(marker, '\nimport contract_offers\n' + marker, 1)
    else:
        # Fall back to inserting immediately before the first app.run call.
        idx = src.find("app.run(")
        if idx == -1:
            raise SystemExit("Could not find the Flask startup section in app.py.")
        line_start = src.rfind("\n", 0, idx) + 1
        src = src[:line_start] + "import contract_offers\n" + src[line_start:]
    APP.write_text(src, encoding="utf-8")

py_compile.compile(str(APP), doraise=True)
print("SUCCESS: Contract offer workflow installed.")
print("Backup:", backup)
print("Manager: /manager/contracts/offers")
print("Admin:   /admin/contracts/offers")
print("Player:  /contract-offers")
